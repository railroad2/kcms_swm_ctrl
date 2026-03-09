#!/usr/bin/env python3

import sys
import json
import time
import serial


PORT = "/dev/serial0"
BAUDRATE = 115200
READ_TIMEOUT = 0.2
COMMAND_TIMEOUT = 2.0


def read_response(ser):
    """Read one JSON response line."""
    deadline = time.monotonic() + COMMAND_TIMEOUT

    while time.monotonic() < deadline:

        raw = ser.readline()

        if not raw:
            continue

        line = raw.decode("utf-8", errors="replace").strip()

        if not line:
            continue

        print("RX:", line)

        try:
            return json.loads(line)

        except json.JSONDecodeError:
            continue

    raise RuntimeError("timeout waiting for response")


def main():

    if len(sys.argv) < 2:
        print("usage: on.py <pin> [pin...]")
        return 1

    try:
        pins = [int(x) for x in sys.argv[1:]]
    except ValueError:
        print("error: pins must be integers")
        return 1

    for p in pins:
        if p < 0 or p > 255:
            print(f"error: pin out of range: {p}")
            return 1

    try:
        ser = serial.Serial(
            PORT,
            BAUDRATE,
            timeout=READ_TIMEOUT,
            write_timeout=1.0,
        )
    except serial.SerialException as e:
        print("error opening serial:", e)
        return 1

    try:

        time.sleep(0.3)

        ser.reset_input_buffer()
        ser.reset_output_buffer()

        payload = {
            "cmd": "ON",
            "pins": pins,
        }

        line = json.dumps(payload, separators=(",", ":")) + "\n"

        print("TX:", line.strip())

        ser.write(line.encode())
        ser.flush()

        resp = read_response(ser)

        if resp.get("ok") != 1:
            print("device error:", resp)
            return 1

        if resp.get("cmd") != "ON":
            print("unexpected response:", resp)
            return 1

        print("SUCCESS")

        return 0

    finally:
        ser.close()


if __name__ == "__main__":
    sys.exit(main())
