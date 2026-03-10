#!/usr/bin/env python3

"""
test_ws.py

Manual test client for the split WebSocket gateway protocol.

Supported endpoints:
- /monitor
- /control

This tool is intended for protocol verification and debugging.
"""

import argparse
import asyncio
import json
from typing import Any, Dict, Optional

import websockets


def pretty(obj: Any) -> str:
    """Return pretty JSON string."""
    return json.dumps(obj, indent=2, ensure_ascii=False)


async def recv_json(ws, timeout: Optional[float] = 5.0) -> Dict[str, Any]:
    """Receive one JSON object from websocket."""
    if timeout is None:
        raw = await ws.recv()
    else:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)

    print("\n<<< RAW")
    print(raw)

    obj = json.loads(raw)

    print("\n<<< JSON")
    print(pretty(obj))

    if not isinstance(obj, dict):
        raise RuntimeError("received JSON is not an object")

    return obj


async def send_json(ws, payload: Dict[str, Any]) -> None:
    """Send one JSON object to websocket."""
    print("\n>>> JSON")
    print(pretty(payload))
    await ws.send(json.dumps(payload))


async def open_ws(uri: str):
    """Open websocket and print initial hello event."""
    print(f"\n=== CONNECT {uri} ===")
    ws = await websockets.connect(uri)
    hello = await recv_json(ws)
    return ws, hello


async def test_monitor_basic(base_uri: str) -> None:
    """Test monitor endpoint basic commands."""
    uri = base_uri.rstrip("/") + "/monitor"
    ws, _ = await open_ws(uri)

    try:
        await send_json(ws, {"gateway": "ping"})
        await recv_json(ws)

        await send_json(ws, {"gateway": "map"})
        await recv_json(ws)

        await send_json(ws, {"gateway": "get"})
        await recv_json(ws)

        await send_json(ws, {"gateway": "subscribe"})
        snapshot = await recv_json(ws)
        subscribed = await recv_json(ws)

        print("\n=== MONITOR SUBSCRIBE CHECK ===")
        print(f"First event after subscribe: {snapshot.get('event')}")
        print(f"Second event after subscribe: {subscribed.get('event')}")

        await send_json(ws, {"gateway": "unsubscribe"})
        await recv_json(ws)

    finally:
        await ws.close()
        print(f"\n=== CLOSED {uri} ===")


async def test_monitor_reject_control(base_uri: str) -> None:
    """Verify that monitor endpoint rejects control commands."""
    uri = base_uri.rstrip("/") + "/monitor"
    ws, _ = await open_ws(uri)

    try:
        await send_json(ws, {"cmd": "ON", "pins": [0]})
        resp = await recv_json(ws)

        print("\n=== EXPECTED RESULT ===")
        if resp.get("ok") == 0:
            print("PASS: /monitor rejected control command.")
        else:
            print("FAIL: /monitor accepted control command.")
    finally:
        await ws.close()
        print(f"\n=== CLOSED {uri} ===")


async def test_control_basic(base_uri: str) -> None:
    """Test control endpoint read-only commands that still go to Pico."""
    uri = base_uri.rstrip("/") + "/control"
    ws, _ = await open_ws(uri)

    try:
        await send_json(ws, {"cmd": "PING"})
        await recv_json(ws)

        await send_json(ws, {"cmd": "PINSTAT", "which": "ALL"})
        await recv_json(ws)

        await send_json(ws, {"cmd": "PCFSTAT", "which": "ALL"})
        await recv_json(ws)

    finally:
        await ws.close()
        print(f"\n=== CLOSED {uri} ===")


async def test_control_reject_gateway(base_uri: str) -> None:
    """Verify that control endpoint rejects gateway commands."""
    uri = base_uri.rstrip("/") + "/control"
    ws, _ = await open_ws(uri)

    try:
        await send_json(ws, {"gateway": "subscribe"})
        resp = await recv_json(ws)

        print("\n=== EXPECTED RESULT ===")
        if resp.get("ok") == 0:
            print("PASS: /control rejected gateway command.")
        else:
            print("FAIL: /control accepted gateway command.")
    finally:
        await ws.close()
        print(f"\n=== CLOSED {uri} ===")


async def test_event_flow(base_uri: str, pin: int) -> None:
    """
    Subscribe on /monitor, then send ON and OFF on /control,
    and verify that pinstat_update events arrive.
    """
    mon_uri = base_uri.rstrip("/") + "/monitor"
    ctl_uri = base_uri.rstrip("/") + "/control"

    mon_ws, _ = await open_ws(mon_uri)
    ctl_ws, _ = await open_ws(ctl_uri)

    try:
        await send_json(mon_ws, {"gateway": "subscribe"})
        await recv_json(mon_ws)  # snapshot
        await recv_json(mon_ws)  # subscribed

        await send_json(ctl_ws, {"cmd": "ON", "pins": [pin]})
        await recv_json(ctl_ws)  # ON response
        await recv_json(mon_ws, timeout=5.0)  # pinstat_update

        await send_json(ctl_ws, {"cmd": "OFF", "pins": [pin]})
        await recv_json(ctl_ws)  # OFF response
        await recv_json(mon_ws, timeout=5.0)  # pinstat_update

    finally:
        await mon_ws.close()
        await ctl_ws.close()
        print(f"\n=== CLOSED {mon_uri} ===")
        print(f"=== CLOSED {ctl_uri} ===")


async def test_alloff(base_uri: str) -> None:
    """Send ALLOFF through control endpoint."""
    uri = base_uri.rstrip("/") + "/control"
    ws, _ = await open_ws(uri)

    try:
        await send_json(ws, {"cmd": "ALLOFF"})
        await recv_json(ws)
    finally:
        await ws.close()
        print(f"\n=== CLOSED {uri} ===")


async def follow_monitor(base_uri: str) -> None:
    """Subscribe and print monitor events indefinitely."""
    uri = base_uri.rstrip("/") + "/monitor"
    ws, _ = await open_ws(uri)

    try:
        await send_json(ws, {"gateway": "subscribe"})
        await recv_json(ws)  # snapshot
        await recv_json(ws)  # subscribed

        print("\n=== FOLLOW MODE ===")
        print("Waiting for monitor events. Press Ctrl+C to stop.")

        while True:
            await recv_json(ws, timeout=None)

    finally:
        await ws.close()
        print(f"\n=== CLOSED {uri} ===")


async def send_control(base_uri: str, payload: Dict[str, Any]) -> None:
    """Send arbitrary control payload."""
    uri = base_uri.rstrip("/") + "/control"
    ws, _ = await open_ws(uri)

    try:
        await send_json(ws, payload)
        await recv_json(ws)
    finally:
        await ws.close()
        print(f"\n=== CLOSED {uri} ===")


async def send_monitor(base_uri: str, payload: Dict[str, Any]) -> None:
    """Send arbitrary monitor payload."""
    uri = base_uri.rstrip("/") + "/monitor"
    ws, _ = await open_ws(uri)

    try:
        await send_json(ws, payload)
        await recv_json(ws)
    finally:
        await ws.close()
        print(f"\n=== CLOSED {uri} ===")


def build_parser() -> argparse.ArgumentParser:
    """Build CLI parser."""
    parser = argparse.ArgumentParser(description="Test split WebSocket gateway protocol")
    parser.add_argument(
        "--base-uri",
        default="ws://127.0.0.1:8765",
        help="base websocket URI without endpoint suffix",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("monitor-basic", help="test basic /monitor commands")
    sub.add_parser("monitor-reject", help="verify /monitor rejects control commands")
    sub.add_parser("control-basic", help="test basic /control Pico commands")
    sub.add_parser("control-reject", help="verify /control rejects gateway commands")
    sub.add_parser("alloff", help="send ALLOFF on /control")
    sub.add_parser("follow", help="subscribe and print monitor events forever")

    p_flow = sub.add_parser("event-flow", help="subscribe on /monitor and toggle one pin on /control")
    p_flow.add_argument("--pin", type=int, default=0, help="linear pin index to toggle")

    p_raw_ctl = sub.add_parser("raw-control", help="send raw JSON payload to /control")
    p_raw_ctl.add_argument("json_payload", help='example: \'{"cmd":"PINSTAT","which":"ALL"}\'')

    p_raw_mon = sub.add_parser("raw-monitor", help="send raw JSON payload to /monitor")
    p_raw_mon.add_argument("json_payload", help='example: \'{"gateway":"get"}\'')

    return parser


async def async_main() -> int:
    """Async entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if args.cmd == "monitor-basic":
        await test_monitor_basic(args.base_uri)
        return 0

    if args.cmd == "monitor-reject":
        await test_monitor_reject_control(args.base_uri)
        return 0

    if args.cmd == "control-basic":
        await test_control_basic(args.base_uri)
        return 0

    if args.cmd == "control-reject":
        await test_control_reject_gateway(args.base_uri)
        return 0

    if args.cmd == "event-flow":
        await test_event_flow(args.base_uri, args.pin)
        return 0

    if args.cmd == "alloff":
        await test_alloff(args.base_uri)
        return 0

    if args.cmd == "follow":
        await follow_monitor(args.base_uri)
        return 0

    if args.cmd == "raw-control":
        payload = json.loads(args.json_payload)
        if not isinstance(payload, dict):
            raise RuntimeError("raw control payload must be a JSON object")
        await send_control(args.base_uri, payload)
        return 0

    if args.cmd == "raw-monitor":
        payload = json.loads(args.json_payload)
        if not isinstance(payload, dict):
            raise RuntimeError("raw monitor payload must be a JSON object")
        await send_monitor(args.base_uri, payload)
        return 0

    raise RuntimeError(f"unknown command: {args.cmd}")


def main() -> int:
    """Sync wrapper for async main."""
    try:
        return asyncio.run(async_main())
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"\nERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
