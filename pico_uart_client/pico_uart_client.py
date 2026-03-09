
import json
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import serial


class PicoClientError(Exception):
    """Base exception for Pico UART client errors."""
    pass


class PicoTimeoutError(PicoClientError):
    """Raised when a command response does not arrive in time."""
    pass


class PicoProtocolError(PicoClientError):
    """Raised when the device returns an invalid or unexpected response."""
    pass


class PicoTransportError(PicoClientError):
    """Raised when the UART transport layer fails."""
    pass


class PicoUARTClient:
    """
    UART JSON client for Pico command processor.

    Design principles:
    - One command at a time
    - One JSON line request -> one JSON line response
    - Ignore non-JSON noise lines
    - Use strict request-response matching by 'cmd'
    """

    def __init__(
        self,
        port: str = "/dev/serial0",
        baudrate: int = 115200,
        read_timeout: float = 0.05,
        write_timeout: float = 1.0,
        command_timeout: float = 2.0,
        auto_open: bool = True,
        debug: bool = False,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.read_timeout = read_timeout
        self.write_timeout = write_timeout
        self.command_timeout = command_timeout
        self.debug = debug

        self._ser: Optional[serial.Serial] = None
        self._lock = threading.Lock()
        self._noise_lines: List[str] = []

        if auto_open:
            self.open()

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------
    def open(self) -> None:
        """Open the UART port if it is not already open."""
        if self._ser is not None and self._ser.is_open:
            return

        try:
            self._ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.read_timeout,
                write_timeout=self.write_timeout,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
            )
            self._ser.reset_input_buffer()
            self._ser.reset_output_buffer()
        except serial.SerialException as exc:
            raise PicoTransportError(f"Failed to open serial port {self.port}: {exc}") from exc

    def close(self) -> None:
        """Close the UART port."""
        if self._ser is not None:
            try:
                if self._ser.is_open:
                    self._ser.close()
            finally:
                self._ser = None

    def __enter__(self) -> "PicoUARTClient":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # -------------------------------------------------------------------------
    # Utilities
    # -------------------------------------------------------------------------
    def _log(self, message: str) -> None:
        """Print debug messages when debug mode is enabled."""
        if self.debug:
            print(f"[PicoUARTClient] {message}")

    def _require_serial(self) -> serial.Serial:
        """Return the active serial object or raise an error."""
        if self._ser is None or not self._ser.is_open:
            raise PicoTransportError("Serial port is not open")
        return self._ser

    def _drain_input(self, duration: float = 0.2) -> List[str]:
        """
        Drain any pending input lines for a short period.

        This is used for re-sync and startup cleanup.
        """
        ser = self._require_serial()
        drained: List[str] = []
        deadline = time.monotonic() + duration

        while time.monotonic() < deadline:
            try:
                raw = ser.readline()
            except serial.SerialException as exc:
                raise PicoTransportError(f"Serial read failed during drain: {exc}") from exc

            if not raw:
                time.sleep(0.005)
                continue

            line = raw.decode("utf-8", errors="replace").strip()
            if line:
                drained.append(line)
                self._log(f"drain: {line}")

        return drained

    def resync(self, settle_time: float = 0.2) -> List[str]:
        """
        Re-synchronize the serial stream by draining pending lines.

        This does not assume any specific device command exists.
        """
        with self._lock:
            self._log("resync start")
            lines = self._drain_input(duration=settle_time)
            self._noise_lines.extend(lines)
            self._log(f"resync done, drained {len(lines)} line(s)")
            return lines

    def get_noise_lines(self) -> List[str]:
        """Return a copy of accumulated non-JSON/noise lines."""
        return list(self._noise_lines)

    # -------------------------------------------------------------------------
    # Parsing
    # -------------------------------------------------------------------------
    def _read_one_line(self) -> Optional[str]:
        """
        Read one line from UART.

        Returns:
          - str: decoded line without trailing newline
          - None: no line received within the read timeout
        """
        ser = self._require_serial()

        try:
            raw = ser.readline()
        except serial.SerialException as exc:
            raise PicoTransportError(f"Serial read failed: {exc}") from exc

        if not raw:
            return None

        line = raw.decode("utf-8", errors="replace").strip()
        self._log(f"rx raw: {line}")
        return line

    def _parse_json_line(self, line: str) -> Optional[Dict[str, Any]]:
        """
        Parse a JSON line if possible.

        Non-JSON lines are treated as noise and returned as None.
        """
        if not line:
            return None

        if not line.startswith("{"):
            self._noise_lines.append(line)
            self._log(f"noise line: {line}")
            return None

        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            self._noise_lines.append(line)
            self._log(f"invalid json line: {line}")
            return None

        if not isinstance(obj, dict):
            self._noise_lines.append(line)
            self._log(f"json root is not object: {line}")
            return None

        return obj

    def _is_matching_response(self, expected_cmd: str, obj: Dict[str, Any]) -> bool:
        """
        Check whether a received JSON object matches the command we are waiting for.
        """
        cmd = obj.get("cmd")
        if not isinstance(cmd, str):
            return False
        return cmd.strip().upper() == expected_cmd.strip().upper()

    # -------------------------------------------------------------------------
    # Core request-response
    # -------------------------------------------------------------------------
    def send_command(
        self,
        payload: Dict[str, Any],
        timeout: Optional[float] = None,
        resync_before_send: bool = False,
    ) -> Dict[str, Any]:
        """
        Send one JSON command and wait for the matching JSON response.

        Args:
            payload: JSON object to send. Must contain 'cmd'.
            timeout: Per-command timeout override.
            resync_before_send: Drain pending input before sending.

        Returns:
            Parsed JSON response object.

        Raises:
            PicoProtocolError, PicoTimeoutError, PicoTransportError
        """
        if not isinstance(payload, dict):
            raise PicoProtocolError("Command payload must be a dict")

        cmd = payload.get("cmd")
        if not isinstance(cmd, str) or not cmd.strip():
            raise PicoProtocolError("Command payload must contain non-empty 'cmd'")

        effective_timeout = self.command_timeout if timeout is None else timeout

        with self._lock:
            ser = self._require_serial()

            if resync_before_send:
                self._log("resync requested before send")
                self._drain_input(duration=0.2)

            try:
                message = json.dumps(payload, separators=(",", ":")) + "\n"
            except (TypeError, ValueError) as exc:
                raise PicoProtocolError(f"Failed to serialize JSON payload: {exc}") from exc

            self._log(f"tx: {message.strip()}")

            try:
                ser.write(message.encode("utf-8"))
                ser.flush()
            except serial.SerialTimeoutException as exc:
                raise PicoTransportError(f"Serial write timeout: {exc}") from exc
            except serial.SerialException as exc:
                raise PicoTransportError(f"Serial write failed: {exc}") from exc

            deadline = time.monotonic() + effective_timeout
            last_json_obj: Optional[Dict[str, Any]] = None

            while time.monotonic() < deadline:
                line = self._read_one_line()
                if line is None:
                    continue

                obj = self._parse_json_line(line)
                if obj is None:
                    continue

                last_json_obj = obj

                if self._is_matching_response(cmd, obj):
                    return obj

                # Keep unmatched JSON as noise-like diagnostic data.
                self._noise_lines.append(line)
                self._log(f"unmatched json response: {obj}")

            detail = {
                "expected_cmd": cmd,
                "last_json_obj": last_json_obj,
            }
            raise PicoTimeoutError(f"Timed out waiting for response: {detail}")

    # -------------------------------------------------------------------------
    # High-level command helpers
    # -------------------------------------------------------------------------
    def echo(self, msg: Any, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Send ECHO command and return the JSON response."""
        return self.send_command(
            {
                "cmd": "ECHO",
                "msg": msg,
            },
            timeout=timeout,
        )

    def ping(self, timeout: Optional[float] = None) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Basic health check using ECHO.

        Returns:
            (True, response) on success
            (False, None) on failure
        """
        try:
            response = self.echo("PING", timeout=timeout)
            return True, response
        except PicoClientError as exc:
            self._log(f"ping failed: {exc}")
            return False, None

