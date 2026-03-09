#!/usr/bin/env python3

"""
DAQ client library for the switching-matrix WebSocket gateway.

This client talks to ws_gateway.py running on Raspberry Pi.

Main features
-------------
- Async WebSocket client
- Strict request-response handling
- Matrix label support (A00 .. P15)
- Convenience methods for ON/OFF/ROUTE/PINSTAT/PCFSTAT/GET/MAP
- Optional subscription for state updates
"""

import asyncio
import json
import re
from typing import Any, Dict, List, Optional, Sequence, Union

import websockets


# Match matrix label like A00, D09, P15
_MATRIX_RE = re.compile(r"^([A-Pa-p])(0[0-9]|1[0-5])$")


class DAQClientError(Exception):
    """Base error for DAQ client."""
    pass


class DAQTransportError(DAQClientError):
    """Transport-level error."""
    pass


class DAQProtocolError(DAQClientError):
    """Protocol-level error."""
    pass


PinInput = Union[int, str]


def row_col_to_pin(row: int, col: int) -> int:
    """Convert matrix coordinate to linear pin index."""
    if not (0 <= row <= 15):
        raise ValueError(f"row out of range: {row}")
    if not (0 <= col <= 15):
        raise ValueError(f"col out of range: {col}")
    return row * 16 + col


def parse_matrix_label(token: str) -> int:
    """Parse matrix label such as A00 or D09."""
    m = _MATRIX_RE.match(token.strip())
    if not m:
        raise ValueError(f"invalid matrix label: {token}")

    row = ord(m.group(1).upper()) - ord("A")
    col = int(m.group(2))
    return row_col_to_pin(row, col)


def pin_to_label(pin: int) -> str:
    """Convert linear pin index to matrix label."""
    if not (0 <= pin <= 255):
        raise ValueError(f"pin out of range: {pin}")
    row = pin // 16
    col = pin % 16
    return f"{chr(ord('A') + row)}{col:02d}"


def parse_pin_tokens(tokens: Sequence[PinInput]) -> List[int]:
    """
    Parse pin expressions into sorted unique linear pin indices.

    Supported inputs
    ----------------
    17
    "17"
    "3,5,7"
    "10-20"
    "A00"
    "D09"
    ["row", "A"]
    ["col", "9"]
    ["A00", "D09", 57]
    """
    pins = set()
    i = 0
    parts = list(tokens)

    while i < len(parts):
        tok = parts[i]

        if isinstance(tok, int):
            if not (0 <= tok <= 255):
                raise ValueError(f"pin out of range: {tok}")
            pins.add(tok)
            i += 1
            continue

        s = str(tok).strip()
        lower = s.lower()

        if lower == "row":
            if i + 1 >= len(parts):
                raise ValueError("row requires label A..P")
            row_label = str(parts[i + 1]).strip().upper()
            if len(row_label) != 1 or not ("A" <= row_label <= "P"):
                raise ValueError(f"invalid row label: {row_label}")
            row = ord(row_label) - ord("A")
            for col in range(16):
                pins.add(row_col_to_pin(row, col))
            i += 2
            continue

        if lower in ("col", "column"):
            if i + 1 >= len(parts):
                raise ValueError("col requires label 0..15")
            try:
                col = int(str(parts[i + 1]).strip())
            except ValueError as exc:
                raise ValueError(f"invalid column label: {parts[i + 1]}") from exc
            if not (0 <= col <= 15):
                raise ValueError(f"column out of range: {col}")
            for row in range(16):
                pins.add(row_col_to_pin(row, col))
            i += 2
            continue

        if _MATRIX_RE.match(s):
            pins.add(parse_matrix_label(s))
            i += 1
            continue

        for part in s.split(","):
            part = part.strip()
            if not part:
                continue

            if _MATRIX_RE.match(part):
                pins.add(parse_matrix_label(part))
                continue

            if "-" in part:
                fields = [x.strip() for x in part.split("-")]
                if len(fields) != 2:
                    raise ValueError(f"invalid range expression: {part}")
                start = int(fields[0])
                end = int(fields[1])
                if start > end:
                    raise ValueError(f"range start > end: {part}")
                for pin in range(start, end + 1):
                    if not (0 <= pin <= 255):
                        raise ValueError(f"pin out of range: {pin}")
                    pins.add(pin)
            else:
                pin = int(part)
                if not (0 <= pin <= 255):
                    raise ValueError(f"pin out of range: {pin}")
                pins.add(pin)

        i += 1

    if not pins:
        raise ValueError("no pins specified")

    return sorted(pins)


class DAQClient:
    """Async DAQ client for the switching-matrix WebSocket gateway."""

    def __init__(
        self,
        uri: str,
        *,
        timeout: float = 5.0,
        connect_timeout: float = 5.0,
    ) -> None:
        self.uri = uri
        self.timeout = timeout
        self.connect_timeout = connect_timeout

        self._ws = None
        self._lock = asyncio.Lock()

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    async def connect(self) -> None:
        """Connect to the WebSocket gateway."""
        if self._ws is not None:
            return

        try:
            self._ws = await asyncio.wait_for(
                websockets.connect(self.uri),
                timeout=self.connect_timeout,
            )
        except Exception as exc:
            raise DAQTransportError(f"failed to connect to gateway: {exc}") from exc

        hello = await self._recv_json(timeout=self.timeout)
        if hello.get("ok") != 1 or hello.get("event") != "connected":
            raise DAQProtocolError(f"unexpected gateway hello: {hello}")

    async def close(self) -> None:
        """Close the WebSocket connection."""
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def __aenter__(self) -> "DAQClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    def _require_ws(self):
        """Return active websocket or raise."""
        if self._ws is None:
            raise DAQTransportError("client is not connected")
        return self._ws

    # -----------------------------------------------------------------
    # Low-level JSON transport
    # -----------------------------------------------------------------

    async def _recv_json(self, timeout: Optional[float] = None) -> Dict[str, Any]:
        """
        Receive one JSON object from gateway.

        If timeout is None, wait indefinitely.
        """
        ws = self._require_ws()

        try:
            if timeout is None:
                msg = await ws.recv()
            else:
                msg = await asyncio.wait_for(ws.recv(), timeout=timeout)
        except Exception as exc:
            raise DAQTransportError(f"failed to receive from gateway: {exc}") from exc

        try:
            obj = json.loads(msg)
        except json.JSONDecodeError as exc:
            raise DAQProtocolError(f"gateway returned non-JSON message: {msg!r}") from exc

        if not isinstance(obj, dict):
            raise DAQProtocolError(f"gateway returned non-object JSON: {obj!r}")

        return obj

    async def _send_and_recv(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send one JSON object and receive one JSON object.

        Access is serialized with an async lock.
        """
        ws = self._require_ws()

        async with self._lock:
            try:
                msg = json.dumps(payload, separators=(",", ":"))
            except (TypeError, ValueError) as exc:
                raise DAQProtocolError(f"failed to serialize payload: {exc}") from exc

            try:
                await asyncio.wait_for(ws.send(msg), timeout=self.timeout)
            except Exception as exc:
                raise DAQTransportError(f"failed to send to gateway: {exc}") from exc

            resp = await self._recv_json(timeout=self.timeout)
            return resp

    async def _send_pico_command(self, payload: Dict[str, Any], expected_cmd: str) -> Dict[str, Any]:
        """Send one Pico command and validate the response."""
        resp = await self._send_and_recv(payload)

        if resp.get("ok") != 1:
            raise DAQProtocolError(f"Pico command failed: {resp}")

        if resp.get("cmd") != expected_cmd:
            raise DAQProtocolError(
                f"unexpected command in response: expected {expected_cmd}, got {resp.get('cmd')}, resp={resp}"
            )

        return resp

    # -----------------------------------------------------------------
    # Gateway commands
    # -----------------------------------------------------------------

    async def gateway_ping(self) -> Dict[str, Any]:
        """Ping the gateway itself, not the Pico."""
        resp = await self._send_and_recv({"gateway": "ping"})

        if resp.get("ok") != 1 or resp.get("event") != "gateway_pong":
            raise DAQProtocolError(f"unexpected gateway ping response: {resp}")

        return resp

    async def get(self) -> Dict[str, Any]:
        """Get cached or freshly fetched PINSTAT ALL from the gateway."""
        resp = await self._send_and_recv({"gateway": "get"})

        if resp.get("ok") != 1 or resp.get("event") != "get":
            raise DAQProtocolError(f"unexpected get response: {resp}")

        return resp

    async def pin_map(self) -> Dict[str, int]:
        """Get gateway-side matrix label -> pin map."""
        resp = await self._send_and_recv({"gateway": "map"})

        if resp.get("ok") != 1 or resp.get("event") != "map":
            raise DAQProtocolError(f"unexpected map response: {resp}")

        mapping = resp.get("map")
        if not isinstance(mapping, dict):
            raise DAQProtocolError(f"missing map object: {resp}")

        return mapping

    async def subscribe(self) -> Dict[str, Any]:
        """
        Subscribe to state updates.

        After this call, the gateway sends:
        1) one pinstat_snapshot
        2) one subscribed ack

        This method consumes both and returns:
            {
                "ok": 1,
                "event": "subscribed",
                "snapshot": <pinstat_snapshot message>
            }
        """
        ws = self._require_ws()

        async with self._lock:
            await asyncio.wait_for(
                ws.send(json.dumps({"gateway": "subscribe"}, separators=(",", ":"))),
                timeout=self.timeout,
            )

            first = await self._recv_json(timeout=self.timeout)
            second = await self._recv_json(timeout=self.timeout)

        snapshot = None
        subscribed = None

        for msg in (first, second):
            if msg.get("event") == "pinstat_snapshot":
                snapshot = msg
            elif msg.get("event") == "subscribed":
                subscribed = msg

        if snapshot is None or subscribed is None:
            raise DAQProtocolError(
                f"unexpected subscribe sequence: first={first}, second={second}"
            )

        return {
            "ok": 1,
            "event": "subscribed",
            "snapshot": snapshot,
        }

    async def unsubscribe(self) -> Dict[str, Any]:
        """Unsubscribe from state updates."""
        resp = await self._send_and_recv({"gateway": "unsubscribe"})

        if resp.get("ok") != 1 or resp.get("event") != "unsubscribed":
            raise DAQProtocolError(f"unexpected unsubscribe response: {resp}")

        return resp

    async def recv_event(self, timeout: Optional[float] = None) -> Dict[str, Any]:
        """
        Receive one asynchronous event message.

        If timeout is None, wait indefinitely.
        """
        return await self._recv_json(timeout=timeout)

    # -----------------------------------------------------------------
    # Pico commands
    # -----------------------------------------------------------------

    async def ping(self) -> Dict[str, Any]:
        """Ping Pico."""
        resp = await self._send_pico_command({"cmd": "PING"}, "PING")

        if resp.get("pong") != 1:
            raise DAQProtocolError(f"missing or invalid pong field: {resp}")

        return resp

    async def on(self, *pins: PinInput) -> Dict[str, Any]:
        """Turn ON one or more pins."""
        parsed = parse_pin_tokens(pins)
        resp = await self._send_pico_command({"cmd": "ON", "pins": parsed}, "ON")

        if not isinstance(resp.get("results"), list):
            raise DAQProtocolError(f"missing results field: {resp}")

        return resp

    async def off(self, *pins: PinInput) -> Dict[str, Any]:
        """Turn OFF one or more pins."""
        if len(pins) == 1 and isinstance(pins[0], str) and pins[0].strip().lower() == "all":
            return await self.alloff()

        parsed = parse_pin_tokens(pins)
        resp = await self._send_pico_command({"cmd": "OFF", "pins": parsed}, "OFF")

        if not isinstance(resp.get("results"), list):
            raise DAQProtocolError(f"missing results field: {resp}")

        return resp

    async def alloff(self) -> Dict[str, Any]:
        """Turn OFF all pins."""
        return await self._send_pico_command({"cmd": "ALLOFF"}, "ALLOFF")

    async def route(self, *target: PinInput) -> Dict[str, Any]:
        """
        Exclusive route selection.

        Performs:
            1) ALLOFF
            2) ON exactly one target
        """
        parsed = parse_pin_tokens(target)
        if len(parsed) != 1:
            raise ValueError("route requires exactly one target")

        await self.alloff()
        return await self.on(parsed[0])

    async def pinstat(self, which: Union[str, int] = "ALL") -> Dict[str, Any]:
        """Query PINSTAT."""
        if which != "ALL":
            if not isinstance(which, int):
                raise ValueError("which must be 'ALL' or integer 0..15")
            if not (0 <= which <= 15):
                raise ValueError("pcf id out of range (0..15)")

        resp = await self._send_pico_command({"cmd": "PINSTAT", "which": which}, "PINSTAT")

        if not isinstance(resp.get("pins"), list):
            raise DAQProtocolError(f"missing pins list: {resp}")

        return resp

    async def pcfstat(self, which: Union[str, int] = "ALL") -> Dict[str, Any]:
        """Query PCFSTAT."""
        if which != "ALL":
            if not isinstance(which, int):
                raise ValueError("which must be 'ALL' or integer 0..15")
            if not (0 <= which <= 15):
                raise ValueError("pcf id out of range (0..15)")

        resp = await self._send_pico_command({"cmd": "PCFSTAT", "which": which}, "PCFSTAT")

        present = resp.get("present")
        if which == "ALL":
            if not isinstance(present, list):
                raise DAQProtocolError(f"missing present list: {resp}")
        else:
            if not isinstance(present, int):
                raise DAQProtocolError(f"missing single present value: {resp}")

        return resp

    # -----------------------------------------------------------------
    # Convenience helpers
    # -----------------------------------------------------------------

    async def active_pins(self) -> List[int]:
        """Return currently active linear pin indices."""
        resp = await self.pinstat("ALL")
        pins = resp["pins"]
        return [i for i, v in enumerate(pins) if v]

    async def active_labels(self) -> List[str]:
        """Return currently active matrix labels such as A00, D09."""
        return [pin_to_label(pin) for pin in await self.active_pins()]

