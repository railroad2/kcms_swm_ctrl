#!/usr/bin/env python3

"""
sw.py

Command line interface for the 256-channel switching matrix controller.

This tool runs on Raspberry Pi and communicates with the Pico firmware
using newline-delimited JSON over UART.

Main goals:
- Human friendly CLI
- Robust communication
- Easy matrix visualization
"""

import argparse
import json
import re
import serial
import sys
import time

# ----------------------------------------------------------------------
# Serial configuration
# ----------------------------------------------------------------------

PORT = "/dev/serial0"
BAUDRATE = 115200

READ_TIMEOUT = 0.2
CMD_TIMEOUT = 3.0

# Short delay to allow UART to stabilize after opening
STARTUP_SETTLE = 0.02

# ----------------------------------------------------------------------
# Matrix constants
# ----------------------------------------------------------------------

ROWS = 16
COLS = 16
TOTAL_PINS = 256

# Matrix label format: A00 .. P15
MATRIX_RE = re.compile(r"^([A-Pa-p])(0[0-9]|1[0-5])$")

# ----------------------------------------------------------------------
# ANSI color helper
# ----------------------------------------------------------------------

def ansi(text, code, enable=True):
    """
    Wrap text with ANSI color code.

    Parameters
    ----------
    text : str
        Text to colorize
    code : str
        ANSI code (e.g. '1;32')
    enable : bool
        Enable/disable coloring
    """
    if not enable:
        return text

    return f"\033[{code}m{text}\033[0m"


# ----------------------------------------------------------------------
# Matrix coordinate helpers
# ----------------------------------------------------------------------

def row_col_to_pin(row, col):
    """
    Convert matrix coordinate to linear pin index.

    pin = row * 16 + col
    """
    return row * COLS + col


def parse_matrix_label(token):
    """
    Parse matrix label such as A00 or D09.

    Example:
        A00 -> pin 0
        D09 -> pin 57
    """

    m = MATRIX_RE.match(token)

    if not m:
        raise ValueError("invalid matrix label")

    row = ord(m.group(1).upper()) - ord("A")
    col = int(m.group(2))

    return row_col_to_pin(row, col)


# ----------------------------------------------------------------------
# Numeric pin expression parser
# ----------------------------------------------------------------------

def parse_numeric(expr):
    """
    Parse numeric pin expressions.

    Supported formats:
        17
        3,5,7
        10-20
        0-3,7,10-12
    """

    pins = set()

    for part in expr.split(","):

        part = part.strip()

        if "-" in part:

            a, b = part.split("-")

            for p in range(int(a), int(b) + 1):
                pins.add(p)

        else:

            pins.add(int(part))

    return pins


# ----------------------------------------------------------------------
# Main pin token parser
# ----------------------------------------------------------------------

def parse_pins(tokens):
    """
    Convert CLI tokens into a list of pin numbers.

    Supported tokens:
        17
        3,5,7
        10-20
        A00
        D09
        row A
        col 9
    """

    pins = set()

    i = 0

    while i < len(tokens):

        tok = tokens[i]

        # Matrix coordinate
        if MATRIX_RE.match(tok):

            pins.add(parse_matrix_label(tok))
            i += 1
            continue

        # Row selection
        if tok == "row":

            r = ord(tokens[i+1].upper()) - 65

            for c in range(COLS):
                pins.add(row_col_to_pin(r, c))

            i += 2
            continue

        # Column selection
        if tok == "col":

            c = int(tokens[i+1])

            for r in range(ROWS):
                pins.add(row_col_to_pin(r, c))

            i += 2
            continue

        # Numeric pin expressions
        pins.update(parse_numeric(tok))
        i += 1

    return sorted(pins)


# ----------------------------------------------------------------------
# UART communication
# ----------------------------------------------------------------------

def open_serial():
    """
    Open UART connection to Pico.
    """

    ser = serial.Serial(
        PORT,
        BAUDRATE,
        timeout=READ_TIMEOUT
    )

    # Allow line discipline to settle
    time.sleep(STARTUP_SETTLE)

    ser.reset_input_buffer()

    return ser


def read_json(ser):
    """
    Read JSON response from UART.
    """

    deadline = time.time() + CMD_TIMEOUT

    while time.time() < deadline:

        line = ser.readline()

        if not line:
            continue

        try:
            obj = json.loads(line.decode())
        except:
            continue

        if isinstance(obj, dict):
            return obj

    raise RuntimeError("timeout waiting for device response")


def send(payload):
    """
    Send command to Pico and wait for response.
    """

    ser = open_serial()

    ser.write((json.dumps(payload) + "\n").encode())

    resp = read_json(ser)

    ser.close()

    return resp


# ----------------------------------------------------------------------
# Command implementations
# ----------------------------------------------------------------------

def cmd_ping():
    """Check communication with Pico."""

    r = send({"cmd":"PING"})

    if r.get("ok") == 1:
        print("PONG")
    else:
        print(r)


def cmd_on(args):
    """Turn ON pins."""

    pins = parse_pins(args)

    r = send({"cmd":"ON", "pins":pins})

    if r.get("ok") == 1:
        print("SUCCESS")
    else:
        print(r)


def cmd_off(args):
    """Turn OFF pins."""

    if args == ["all"]:
        r = send({"cmd":"ALLOFF"})
    else:
        pins = parse_pins(args)
        r = send({"cmd":"OFF","pins":pins})

    if r.get("ok") == 1:
        print("SUCCESS")
    else:
        print(r)


def cmd_route(args):
    """
    Exclusive route.

    Turn OFF all channels then enable exactly one.
    """

    pins = parse_pins(args)

    if len(pins) != 1:
        print("route requires exactly one target")
        return

    send({"cmd":"ALLOFF"})
    r = send({"cmd":"ON","pins":pins})

    if r.get("ok") == 1:
        print("SUCCESS")


# ----------------------------------------------------------------------
# Matrix visualization
# ----------------------------------------------------------------------

def print_matrix(pins, color=True):
    """
    Pretty-print 16x16 pin matrix.

    - Rows labeled A..P
    - Columns labeled 00..15
    - ON pins shown in green
    """

    header = "   " + " ".join(f"{i:02d}" for i in range(COLS))
    print(header)

    for r in range(ROWS):

        row_letter = chr(65 + r)
        line = [row_letter]

        for c in range(COLS):

            pin = r * COLS + c
            v = pins[pin]

            txt = f"{v:2d}"

            if v:
                txt = ansi(txt,"1;32",color)
            else:
                txt = ansi(txt,"90",color)

            line.append(txt)

        print(" ".join(line))


def cmd_pinstat(arg):
    """
    Query pin state from Pico.
    """

    # Only show active channels
    if arg == "active":

        r = send({"cmd":"PINSTAT","which":"ALL"})
        pins = r["pins"]

        for i,v in enumerate(pins):

            if v:
                row = chr(65 + i//16)
                col = i%16
                print(f"{row}{col:02d}")

        return

    # Full matrix
    if arg is None:

        r = send({"cmd":"PINSTAT","which":"ALL"})
        print_matrix(r["pins"])
        return

    # One PCF block
    r = send({"cmd":"PINSTAT","which":int(arg)})
    print(r["pins"])


def cmd_pcfstat(arg):
    """
    Query PCF chip presence.
    """

    if arg is None:

        r = send({"cmd":"PCFSTAT","which":"ALL"})
        print(r["present"])

    else:

        r = send({"cmd":"PCFSTAT","which":int(arg)})
        print(r["present"])


# ----------------------------------------------------------------------
# Mapping visualization
# ----------------------------------------------------------------------

def cmd_map():
    """
    Print static matrix-to-pin mapping.
    """

    header = "   " + " ".join(f"{i:02d}" for i in range(COLS))
    print(header)

    for r in range(ROWS):

        row_letter = chr(65+r)
        line = [row_letter]

        for c in range(COLS):

            pin = r*COLS+c
            line.append(f"{pin:03d}")

        print(" ".join(line))


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def main():

    parser = argparse.ArgumentParser()

    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("ping")

    p_on = sub.add_parser("on")
    p_on.add_argument("pins", nargs="+")

    p_off = sub.add_parser("off")
    p_off.add_argument("pins", nargs="+")

    p_route = sub.add_parser("route")
    p_route.add_argument("pins", nargs="+")

    p_ps = sub.add_parser("pinstat")
    p_ps.add_argument("arg", nargs="?")

    p_pc = sub.add_parser("pcfstat")
    p_pc.add_argument("arg", nargs="?")

    sub.add_parser("map")

    args = parser.parse_args()

    if args.cmd == "ping":
        cmd_ping()

    elif args.cmd == "on":
        cmd_on(args.pins)

    elif args.cmd == "off":
        cmd_off(args.pins)

    elif args.cmd == "route":
        cmd_route(args.pins)

    elif args.cmd == "pinstat":
        cmd_pinstat(args.arg)

    elif args.cmd == "pcfstat":
        cmd_pcfstat(args.arg)

    elif args.cmd == "map":
        cmd_map()


if __name__ == "__main__":
    main()
