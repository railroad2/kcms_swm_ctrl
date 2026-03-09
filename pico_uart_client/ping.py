#!/usr/bin/env python3

import json
import sys
import time

import serial


PORT = "/dev/serial0"
BAUDRATE = 115200
READ_TIMEOUT = 0.2
COMMAND_TIMEOUT = 2.0


def main() -> int:
    """Send one PING command to Pico and verify the JSON response."""
    try:
        ser = serial.Serial(
            port=PORT,
            baudrate=BAUDRATE,
            timeout=READ_TIMEOUT,
            write_timeout=1.0,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )
    except serial.SerialException as exc:
        print(f"FAIL: could not open serial port {PORT}: {exc}")
        return 1

    try:
        # Allow the UART link to settle.
        time.sleep(0.4)

        # Drain any startup or stale input.
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        # Build and send the JSON PING command.
        message = json.dumps({"cmd": "PING"}, separators=(",", ":")) + "\n"
        ser.write(message.encode("utf-8"))
        ser.flush()

        # Wait for one JSON response.
        deadline = time.monotonic() + COMMAND_TIMEOUT
        while time.monotonic() < deadline:
            raw = ser.readline()
            if not raw:
                continue

            line = raw.decode("utf-8", errors="replace").strip()
            print(f"RX: {line}")

            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                print("FAIL: response is not valid JSON")
                return 1

            if obj.get("ok") != 1:
                print(f"FAIL: device returned error response: {obj}")
                return 1

            if obj.get("cmd") != "PING":
                print(f"FAIL: unexpected cmd in response: {obj}")
                return 1

            if obj.get("pong") != 1:
                print(f"FAIL: missing or invalid pong field: {obj}")
                return 1

            print("PASS: PING succeeded")
            return 0

        print("FAIL: timeout waiting for PING response")
        return 1

    except serial.SerialException as exc:
        print(f"FAIL: serial communication error: {exc}")
        return 1

    finally:
        ser.close()


if __name__ == "__main__":
    sys.exit(main())
