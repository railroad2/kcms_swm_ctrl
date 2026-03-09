#!/usr/bin/env python3

import argparse
import json
import sys
import time
from typing import List

import serial


PORT = "/dev/serial0"
BAUDRATE = 115200
READ_TIMEOUT = 0.2
COMMAND_TIMEOUT = 3.0


def read_response(ser: serial.Serial) -> dict:
    """Read one JSON response line from UART."""
    deadline = time.monotonic() + COMMAND_TIMEOUT

    while time.monotonic() < deadline:
        raw = ser.readline()
        if not raw:
            continue

        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue

        try:
            return json.loads(line)
        except json.JSONDecodeError:
            # Ignore non-JSON noise lines.
            continue

    raise RuntimeError("timeout waiting for response")


def send_command(ser: serial.Serial, payload: dict) -> dict:
    """Send one JSON command and wait for one JSON response."""
    line = json.dumps(payload, separators=(",", ":")) + "\n"
    ser.write(line.encode("utf-8"))
    ser.flush()
    return read_response(ser)


def colorize(text: str, enabled: bool, present: int) -> str:
    """Apply ANSI color to one PCF cell."""
    if not enabled:
        return text

    if present:
        return f"\033[32m{text}\033[0m"
    return f"\033[31m{text}\033[0m"


def print_frame_line(width: int) -> None:
    """Print one horizontal frame line."""
    print("+" + "-" * width + "+")


def print_pcf_all(present: List[int], frame: bool, color: bool) -> None:
    """Print all 16 PCF presence states."""
    if len(present) != 16:
        raise ValueError("ALL mode requires 16 entries")

    cells = []
    for i, value in enumerate(present):
        label = f"{i:02d}:{value}"
        cells.append(colorize(label, color, value))

    body = " ".join(cells)

    if frame:
        print_frame_line(len(body))
        print("|" + body + "|")
        print_frame_line(len(body))
    else:
        print(body)


def print_pcf_one(pcf_id: int, present: int, frame: bool, color: bool) -> None:
    """Print one PCF presence state."""
    body = colorize(f"{pcf_id:02d}:{present}", color, present)

    if frame:
        print_frame_line(len(body))
        print("|" + body + "|")
        print_frame_line(len(body))
    else:
        print(body)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Read PCFSTAT from Pico over UART."
    )

    parser.add_argument(
        "item",
        nargs="?",
        default="ALL",
        help="ALL or one PCF id (0..15)",
    )

    parser.add_argument(
        "--port",
        default=PORT,
        help=f"Serial port (default: {PORT})",
    )

    parser.add_argument(
        "--baudrate",
        type=int,
        default=BAUDRATE,
        help=f"UART baudrate (default: {BAUDRATE})",
    )

    parser.add_argument(
        "--noframe",
        action="store_true",
        help="Disable frame output.",
    )

    parser.add_argument(
        "--nocolor",
        action="store_true",
        help="Disable ANSI color output.",
    )

    parser.add_argument(
        "-v",
        action="store_true",
        help="Verbose mode.",
    )

    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_args()

    frame = not args.noframe
    color = not args.nocolor

    if args.item.upper() == "ALL":
        which = "ALL"
        mode = "ALL"
    else:
        try:
            which = int(args.item)
        except ValueError:
            print("error: item must be ALL or integer pcf id")
            return 1

        if which < 0 or which > 15:
            print("error: pcf id out of range (0..15)")
            return 1

        mode = "ONE"

    try:
        ser = serial.Serial(
            port=args.port,
            baudrate=args.baudrate,
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
        print(f"error opening serial port: {exc}")
        return 1

    try:
        # Let the UART link settle, then clear stale input.
        time.sleep(0.3)
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        payload = {
            "cmd": "PCFSTAT",
            "which": which,
        }

        if args.v:
            print("TX:", json.dumps(payload, separators=(",", ":")))

        resp = send_command(ser, payload)

        if args.v:
            print("RX:", json.dumps(resp))

        if resp.get("ok") != 1:
            print("device error:", resp)
            return 1

        if resp.get("cmd") != "PCFSTAT":
            print("unexpected response:", resp)
            return 1

        if mode == "ALL":
            present = resp.get("present")
            if not isinstance(present, list):
                print("invalid response: missing present list")
                return 1

            print_pcf_all(
                present=present,
                frame=frame,
                color=color,
            )

        else:
            present = resp.get("present")
            if not isinstance(present, int):
                print("invalid response: missing single present value")
                return 1

            print_pcf_one(
                pcf_id=which,
                present=present,
                frame=frame,
                color=color,
            )

        return 0

    except RuntimeError as exc:
        print("error:", exc)
        return 1

    finally:
        ser.close()


if __name__ == "__main__":
    sys.exit(main())
