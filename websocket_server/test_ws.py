#!/usr/bin/env python3

import asyncio
import json
import sys

import websockets


WS_URL = "ws://127.0.0.1:8765"


def ensure(condition, message):
    """Raise RuntimeError if condition is false."""
    if not condition:
        raise RuntimeError(message)


async def recv_json(ws):
    """Receive one WebSocket message and parse it as JSON."""
    msg = await ws.recv()
    print("RX:", msg)
    return json.loads(msg)


async def main():
    async with websockets.connect(WS_URL) as ws:
        # Receive initial connected event
        hello = await recv_json(ws)
        ensure(hello.get("ok") == 1, "connected event failed")

        # -------------------------------------------------------------
        # Test gateway ping
        # -------------------------------------------------------------
        ping_req = {"gateway": "ping"}
        print("TX:", json.dumps(ping_req))
        await ws.send(json.dumps(ping_req))

        ping_resp = await recv_json(ws)
        ensure(ping_resp.get("ok") == 1, "gateway ping failed")
        ensure(ping_resp.get("event") == "gateway_pong", "unexpected gateway ping response")

        # -------------------------------------------------------------
        # Test PINSTAT ALL forwarded to Pico
        # -------------------------------------------------------------
        pinstat_req = {"cmd": "PINSTAT", "which": "ALL"}
        print("TX:", json.dumps(pinstat_req))
        await ws.send(json.dumps(pinstat_req))

        pinstat_resp = await recv_json(ws)
        ensure(pinstat_resp.get("ok") == 1, "PINSTAT failed")
        ensure(pinstat_resp.get("cmd") == "PINSTAT", "unexpected cmd for PINSTAT")
        ensure(pinstat_resp.get("which") == "ALL", "unexpected which for PINSTAT")

        pins = pinstat_resp.get("pins")
        ensure(isinstance(pins, list), "pins is not a list")
        ensure(len(pins) == 256, f"pins length is not 256: {len(pins)}")

        # -------------------------------------------------------------
        # Test gateway get
        # -------------------------------------------------------------
        get_req = {"gateway": "get"}
        print("TX:", json.dumps(get_req))
        await ws.send(json.dumps(get_req))

        get_resp_1 = await recv_json(ws)
        ensure(get_resp_1.get("ok") == 1, "first get failed")
        ensure(get_resp_1.get("event") == "get", "unexpected first get event")

        data_1 = get_resp_1.get("data")
        ensure(isinstance(data_1, dict), "first get data is not object")
        ensure(data_1.get("cmd") == "PINSTAT", "first get data cmd mismatch")
        ensure(data_1.get("which") == "ALL", "first get data which mismatch")
        ensure(isinstance(data_1.get("pins"), list), "first get pins missing")
        ensure(len(data_1["pins"]) == 256, "first get pins length mismatch")

        # Second get should usually come from cache
        print("TX:", json.dumps(get_req))
        await ws.send(json.dumps(get_req))

        get_resp_2 = await recv_json(ws)
        ensure(get_resp_2.get("ok") == 1, "second get failed")
        ensure(get_resp_2.get("event") == "get", "unexpected second get event")

        data_2 = get_resp_2.get("data")
        ensure(isinstance(data_2, dict), "second get data is not object")
        ensure(data_2.get("cmd") == "PINSTAT", "second get data cmd mismatch")
        ensure(data_2.get("which") == "ALL", "second get data which mismatch")
        ensure(isinstance(data_2.get("pins"), list), "second get pins missing")
        ensure(len(data_2["pins"]) == 256, "second get pins length mismatch")

        print("PASS: gateway ping, PINSTAT, and get all succeeded")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print("FAIL:", exc)
        sys.exit(1)
