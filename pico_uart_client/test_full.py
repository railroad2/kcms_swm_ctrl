#!/usr/bin/env python3
#!/usr/bin/env python3

import json
import sys
import time
from typing import Any, Dict, Optional

import serial


PORT = "/dev/serial0"
BAUDRATE = 115200
READ_TIMEOUT = 0.2
COMMAND_TIMEOUT = 2.0
DEBUG = True


class TestFailure(Exception):
    """Raised when a test assertion fails."""
    pass


def dlog(message: str) -> None:
    """Print debug logs when enabled."""
    if DEBUG:
        print(f"[DEBUG] {message}")


class PicoTester:
    """UART tester for Pico JSON command firmware."""

    def __init__(self, port: str, baudrate: int) -> None:
        self.port = port
        self.baudrate = baudrate
        self.ser: Optional[serial.Serial] = None

    def open(self) -> None:
        """Open the serial port."""
        self.ser = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            timeout=READ_TIMEOUT,
            write_timeout=1.0,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()

    def close(self) -> None:
        """Close the serial port."""
        if self.ser is not None:
            self.ser.close()
            self.ser = None

    def require_serial(self) -> serial.Serial:
        """Return the active serial object."""
        if self.ser is None or not self.ser.is_open:
            raise RuntimeError("Serial port is not open")
        return self.ser

    def drain(self, duration: float = 0.3) -> None:
        """Drain pending input from the serial port."""
        ser = self.require_serial()
        deadline = time.monotonic() + duration

        while time.monotonic() < deadline:
            raw = ser.readline()
            if not raw:
                time.sleep(0.01)
                continue

            line = raw.decode("utf-8", errors="replace").strip()
            if line:
                dlog(f"DRAIN: {line}")

    def read_line(self, timeout: float = COMMAND_TIMEOUT) -> Optional[str]:
        """Read one line and return it, or None on timeout."""
        ser = self.require_serial()
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            raw = ser.readline()
            if not raw:
                continue

            line = raw.decode("utf-8", errors="replace").strip()
            dlog(f"RX: {line}")
            return line

        return None

    def send_raw_line(self, line: str) -> None:
        """Send one raw line terminated by newline."""
        ser = self.require_serial()
        dlog(f"TX RAW: {line}")
        ser.write(line.encode("utf-8"))
        ser.write(b"\n")
        ser.flush()

    def send_json(self, obj: Dict[str, Any]) -> None:
        """Send one JSON object as one newline-delimited line."""
        line = json.dumps(obj, separators=(",", ":"))
        self.send_raw_line(line)

    def send_json_and_expect_json(
        self,
        obj: Dict[str, Any],
        timeout: float = COMMAND_TIMEOUT,
    ) -> Dict[str, Any]:
        """Send one JSON command and wait for one JSON response."""
        self.send_json(obj)

        line = self.read_line(timeout=timeout)
        if line is None:
            raise TestFailure(f"Timeout waiting for response to {obj}")

        if line == "":
            raise TestFailure(f"Empty response for {obj}")

        try:
            resp = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TestFailure(f"Non-JSON response for {obj}: {line}") from exc

        return resp

    def wait_ready(self, timeout: float = 0.7) -> Optional[Dict[str, Any]]:
        """Wait briefly for READY event. Return None if not observed."""
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            line = self.read_line(timeout=0.2)
            if line is None or line == "":
                continue

            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            if obj.get("event") == "READY" and obj.get("ok") == 1:
                return obj

        return None

    def assert_ok(self, resp: Dict[str, Any], cmd: Optional[str] = None) -> None:
        """Assert that response is successful."""
        if resp.get("ok") != 1:
            raise TestFailure(f"Expected ok=1, got: {resp}")

        if cmd is not None and resp.get("cmd") != cmd:
            raise TestFailure(f"Expected cmd={cmd}, got: {resp}")

    def assert_error(self, resp: Dict[str, Any]) -> None:
        """Assert that response is an error."""
        if resp.get("ok") != 0:
            raise TestFailure(f"Expected ok=0, got: {resp}")

        if "error" not in resp:
            raise TestFailure(f"Expected error field, got: {resp}")

    def warmup(self) -> None:
        """
        Stabilize the UART link before real tests.

        Strategy:
        - wait a little after open
        - drain startup garbage
        - try PING up to a few times
        """
        time.sleep(0.4)
        self.drain(0.4)

        last_error = None

        for attempt in range(3):
            try:
                resp = self.send_json_and_expect_json({"cmd": "PING"}, timeout=1.0)
                self.assert_ok(resp, "PING")
                return
            except Exception as exc:
                last_error = exc
                dlog(f"WARMUP attempt {attempt + 1} failed: {exc}")
                self.drain(0.2)
                time.sleep(0.1)

        raise TestFailure(f"Warmup failed: {last_error}")


def print_result(name: str, passed: bool, detail: str = "") -> None:
    """Print one test result."""
    status = "PASS" if passed else "FAIL"
    if detail:
        print(f"[{status}] {name}: {detail}")
    else:
        print(f"[{status}] {name}")


def test_ping(t: PicoTester) -> None:
    """Test PING command."""
    resp = t.send_json_and_expect_json({"cmd": "PING"})
    t.assert_ok(resp, "PING")
    if resp.get("pong") != 1:
        raise TestFailure(f"Expected pong=1, got: {resp}")


def test_echo(t: PicoTester) -> None:
    """Test ECHO command."""
    resp = t.send_json_and_expect_json({"cmd": "ECHO", "msg": "hello"})
    t.assert_ok(resp, "ECHO")
    if resp.get("echo") != "hello":
        raise TestFailure(f"Unexpected echo payload: {resp}")


def test_on_off(t: PicoTester) -> None:
    """Test ON and OFF commands."""
    resp_on = t.send_json_and_expect_json({"cmd": "ON", "pins": [3, 5]})
    t.assert_ok(resp_on, "ON")

    results_on = resp_on.get("results")
    if not isinstance(results_on, list) or len(results_on) != 2:
        raise TestFailure(f"Invalid ON results: {resp_on}")

    resp_off = t.send_json_and_expect_json({"cmd": "OFF", "pins": [3]})
    t.assert_ok(resp_off, "OFF")

    results_off = resp_off.get("results")
    if not isinstance(results_off, list) or len(results_off) != 1:
        raise TestFailure(f"Invalid OFF results: {resp_off}")


def test_alloff(t: PicoTester) -> None:
    """Test ALLOFF command."""
    _ = t.send_json_and_expect_json({"cmd": "ON", "pins": [1, 2, 3]})
    resp = t.send_json_and_expect_json({"cmd": "ALLOFF"})
    t.assert_ok(resp, "ALLOFF")

    stat = t.send_json_and_expect_json({"cmd": "PINSTAT", "which": "ALL"})
    t.assert_ok(stat, "PINSTAT")

    pins = stat.get("pins")
    if not isinstance(pins, list) or len(pins) != 256:
        raise TestFailure(f"Invalid PINSTAT ALL response: {stat}")

    if any(pins):
        raise TestFailure("ALLOFF failed, some channels are still ON")


def test_pinstat_all(t: PicoTester) -> None:
    """Test PINSTAT ALL."""
    _ = t.send_json_and_expect_json({"cmd": "ALLOFF"})
    _ = t.send_json_and_expect_json({"cmd": "ON", "pins": [0, 15, 16, 31, 255]})

    resp = t.send_json_and_expect_json({"cmd": "PINSTAT", "which": "ALL"})
    t.assert_ok(resp, "PINSTAT")

    pins = resp.get("pins")
    if not isinstance(pins, list) or len(pins) != 256:
        raise TestFailure(f"PINSTAT ALL invalid: {resp}")

    expected_on = {0, 15, 16, 31, 255}
    for i in range(256):
        expected = 1 if i in expected_on else 0
        if pins[i] != expected:
            raise TestFailure(f"PINSTAT ALL mismatch at pin {i}: got {pins[i]}, expected {expected}")


def test_pinstat_one_pcf(t: PicoTester) -> None:
    """Test PINSTAT for one PCF group."""
    _ = t.send_json_and_expect_json({"cmd": "ALLOFF"})
    _ = t.send_json_and_expect_json({"cmd": "ON", "pins": [32, 33, 47]})

    resp = t.send_json_and_expect_json({"cmd": "PINSTAT", "which": 2})
    t.assert_ok(resp, "PINSTAT")

    pins = resp.get("pins")
    if not isinstance(pins, list) or len(pins) != 16:
        raise TestFailure(f"PINSTAT one PCF invalid: {resp}")

    expected = [0] * 16
    expected[0] = 1
    expected[1] = 1
    expected[15] = 1

    if pins != expected:
        raise TestFailure(f"PINSTAT one PCF mismatch: got {pins}, expected {expected}")


def test_pcfstat_all(t: PicoTester) -> None:
    """Test PCFSTAT ALL."""
    resp = t.send_json_and_expect_json({"cmd": "PCFSTAT", "which": "ALL"})
    t.assert_ok(resp, "PCFSTAT")

    present = resp.get("present")
    if not isinstance(present, list) or len(present) != 16:
        raise TestFailure(f"PCFSTAT ALL invalid: {resp}")

    for value in present:
        if value not in (0, 1):
            raise TestFailure(f"PCFSTAT ALL contains invalid value: {resp}")


def test_pcfstat_one(t: PicoTester) -> None:
    """Test PCFSTAT single query."""
    resp = t.send_json_and_expect_json({"cmd": "PCFSTAT", "which": 0})
    t.assert_ok(resp, "PCFSTAT")

    present = resp.get("present")
    if present not in (0, 1):
        raise TestFailure(f"PCFSTAT single invalid: {resp}")


def test_empty_line(t: PicoTester) -> None:
    """Test empty line handling."""
    t.drain(0.1)
    t.send_raw_line("")
    line = t.read_line(timeout=1.5)
    if line is None:
        raise TestFailure("Timeout waiting for empty-line response")

    resp = json.loads(line)
    t.assert_error(resp)
    t.drain(0.1)


def test_invalid_json(t: PicoTester) -> None:
    """Test malformed JSON handling with definitely-invalid input."""
    t.drain(0.1)
    t.send_raw_line("{")
    line = t.read_line(timeout=1.5)
    if line is None:
        raise TestFailure("Timeout waiting for invalid-JSON response")

    resp = json.loads(line)
    t.assert_error(resp)
    t.drain(0.1)


def test_long_line(t: PicoTester) -> None:
    """Test overlong line handling."""
    t.drain(0.1)
    long_msg = "a" * 700
    raw = '{"cmd":"ECHO","msg":"' + long_msg + '"}'
    t.send_raw_line(raw)

    line = t.read_line(timeout=3.0)
    if line is None:
        raise TestFailure("Timeout waiting for long-line response")

    resp = json.loads(line)
    t.assert_error(resp)
    t.drain(0.1)


def test_invalid_pin(t: PicoTester) -> None:
    """Test invalid pin handling."""
    resp = t.send_json_and_expect_json({"cmd": "ON", "pins": [999]})
    t.assert_error(resp)


def test_invalid_pcf(t: PicoTester) -> None:
    """Test invalid PCF handling."""
    resp = t.send_json_and_expect_json({"cmd": "PINSTAT", "which": 99})
    t.assert_error(resp)


def test_burst_sequential(t: PicoTester, count: int = 20) -> None:
    """Test safe sequential request-response burst."""
    for i in range(count):
        resp = t.send_json_and_expect_json({"cmd": "ECHO", "msg": i}, timeout=2.0)
        t.assert_ok(resp, "ECHO")
        if resp.get("echo") != i:
            raise TestFailure(f"Burst mismatch at index {i}: {resp}")


def test_burst_unsafe(t: PicoTester, count: int = 50) -> None:
    """
    Diagnostic stress test that intentionally violates protocol discipline.

    This is not a pass/fail requirement for the firmware.
    """
    ser = t.require_serial()
    t.drain(0.2)

    for i in range(count):
        line = json.dumps({"cmd": "ECHO", "msg": i}, separators=(",", ":")) + "\n"
        ser.write(line.encode("utf-8"))
    ser.flush()

    received = 0
    deadline = time.monotonic() + 5.0

    while time.monotonic() < deadline:
        line = t.read_line(timeout=0.2)
        if line is None or line == "":
            continue

        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        if isinstance(obj, dict) and "ok" in obj:
            received += 1

    print_result(
        "burst unsafe diagnostic",
        True,
        f"received {received}/{count} responses (expected stress behavior)",
    )

    t.drain(0.3)


def run_test(name: str, fn, tester: PicoTester) -> bool:
    """Run one test function and print result."""
    try:
        tester.drain(0.1)
        fn(tester)
        print_result(name, True)
        return True
    except Exception as exc:
        print_result(name, False, str(exc))
        tester.drain(0.2)
        return False


def main() -> int:
    """Run the full firmware test suite."""
    tester = PicoTester(PORT, BAUDRATE)

    try:
        tester.open()

        ready = tester.wait_ready(timeout=0.7)
        if ready is not None:
            print_result("ready event", True, str(ready))
        else:
            print_result("ready event", True, "not observed (acceptable if Pico already booted)")

        tester.warmup()
        print_result("warmup", True)

        tests = [
            ("ping", test_ping),
            ("echo", test_echo),
            ("on/off", test_on_off),
            ("alloff", test_alloff),
            ("pinstat all", test_pinstat_all),
            ("pinstat one pcf", test_pinstat_one_pcf),
            ("pcfstat all", test_pcfstat_all),
            ("pcfstat one", test_pcfstat_one),
            ("empty line", test_empty_line),
            ("invalid json", test_invalid_json),
            ("long line", test_long_line),
            ("invalid pin", test_invalid_pin),
            ("invalid pcf", test_invalid_pcf),
            ("burst sequential", test_burst_sequential),
        ]

        passed = 0
        failed = 0

        for name, fn in tests:
            ok = run_test(name, fn, tester)
            if ok:
                passed += 1
            else:
                failed += 1

        test_burst_unsafe(tester, count=50)

        print()
        print(f"SUMMARY: passed={passed}, failed={failed}")

        return 0 if failed == 0 else 1

    finally:
        tester.close()


if __name__ == "__main__":
    sys.exit(main())
