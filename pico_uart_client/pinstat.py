#!/usr/bin/env python3

import argparse
import json
import sys
import time
from typing import List, Optional

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


def colorize(text: str, enabled: bool, state: int, highlight: bool) -> str:
    """Apply ANSI color to one pin cell."""
    if not enabled:
        return text

    if highlight:
        if state:
            return f"\033[1;42;30m{text}\033[0m"
        return f"\033[1;41;37m{text}\033[0m"

    if state:
        return f"\033[32m{text}\033[0m"
    return f"\033[90m{text}\033[0m"


def print_frame_line(width: int) -> None:
    """Print one horizontal frame line."""
    print("+" + "-" * width + "+")


def print_pins_all(
    pins: List[int],
    highlight_channels: Optional[List[int]],
    frame: bool,
    color: bool,
) -> None:
    """Print all 256 pins as a 16x16 grid."""
    if len(pins) != 256:
        raise ValueError("ALL mode requires 256 pins")

    # Each row: "000: 0 0 0 ... 0"
    row_width = 4 + 16 * 2 - 1

    if frame:
        print_frame_line(row_width)

    for row in range(16):
        base = row * 16
        cells = []

        for col in range(16):
            ch = base + col
            state = pins[ch]
            text = str(state)

            highlight = highlight_channels is not None and ch in highlight_channels
            cells.append(colorize(text, color, state, highlight))

        line = f"{base:03d}: " + " ".join(cells)

        if frame:
            print("|" + line + "|")
        else:
            print(line)

    if frame:
        print_frame_line(row_width)


def print_pins_pcf(
    pcf_id: int,
    pins: List[int],
    highlight_channels: Optional[List[int]],
    frame: bool,
    color: bool,
) -> None:
    """Print one 16-channel PCF block."""
    if len(pins) != 16:
        raise ValueError("PCF mode requires 16 pins")

    start = pcf_id * 16
    entries = []

    for i, state in enumerate(pins):
        ch = start + i
        label = f"{ch:03d}:{state}"
        highlight = highlight_channels is not None and ch in highlight_channels
        entries.append(colorize(label, color, state, highlight))

    body = " ".join(entries)

    if frame:
        print_frame_line(len(body))
        print("|" + body + "|")
        print_frame_line(len(body))
    else:
        print(body)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Read PINSTAT from Pico over UART."
    )

    parser.add_argument(
        "items",
        nargs="*",
        help=(
            "Selection list. "
            "Examples: ALL / 2 / 3 17 45. "
            "If one integer in range 0..15 is given, it is treated as PCF id query. "
            "If multiple integers are given, ALL is queried and those channels are highlighted."
        ),
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

    # Selection policy:
    # - no args            -> ALL
    # - "ALL"              -> ALL
    # - one integer 0..15  -> query that PCF block
    # - multiple integers  -> query ALL and highlight those channels
    mode = "ALL"
    which = "ALL"
    highlight_channels: Optional[List[int]] = None

    if len(args.items) == 0:
        mode = "ALL"
        which = "ALL"

    elif len(args.items) == 1 and args.items[0].upper() == "ALL":
        mode = "ALL"
        which = "ALL"

    elif len(args.items) == 1:
        try:
            value = int(args.items[0])
        except ValueError:
            print("error: argument must be ALL, one PCF id, or channel numbers")
            return 1

        if 0 <= value <= 15:
            mode = "PCF"
            which = value
        elif 0 <= value <= 255:
            mode = "ALL"
            which = "ALL"
            highlight_channels = [value]
        else:
            print("error: value out of range")
            return 1

    else:
        try:
            highlight_channels = [int(x) for x in args.items]
        except ValueError:
            print("error: all items must be integers or ALL")
            return 1

        for ch in highlight_channels:
            if ch < 0 or ch > 255:
                print(f"error: channel out of range: {ch}")
                return 1

        mode = "ALL"
        which = "ALL"

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
            "cmd": "PINSTAT",
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

        if resp.get("cmd") != "PINSTAT":
            print("unexpected response:", resp)
            return 1

        pins = resp.get("pins")
        if not isinstance(pins, list):
            print("invalid response: missing pins list")
            return 1

        if mode == "ALL":
            print_pins_all(
                pins=pins,
                highlight_channels=highlight_channels,
                frame=frame,
                color=color,
            )
        else:
            print_pins_pcf(
                pcf_id=int(which),
                pins=pins,
                highlight_channels=highlight_channels,
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
