#!/usr/bin/env python3
# usbcomm_client.py
# Robust host-side client for Pico over USB CDC
# - Sends CRLF line endings (max compatibility)
# - Supports both raw-text commands and JSON commands
# - Collects multi-line replies with idle-timeout
# - Optionally extracts and prints only the first JSON line in the reply
# - More robust Pico port detection (manufacturer/description/VID-PID heuristics)

import sys
import json
import time
import argparse
import serial
from serial.tools import list_ports


def find_pico_ports():
    """Return a list of candidate serial device names for Pico/MicroPython."""
    candidates = []
    for i in list_ports.comports():
        m = (i.manufacturer or "").lower()
        d = (i.description or "").lower()
        vid = i.vid or 0
        pid = i.pid or 0
        # Heuristics: match on manufacturer/description or known VID/PID
        if (
            "micropython" in m
            or "raspberry" in m
            or "pico" in d
            or "rp2" in d
            or (vid, pid) in {(0x2E8A, 0x0005), (0x2E8A, 0x000A)}  # examples
        ):
            candidates.append(i.device)
    return candidates


def list_all_ports():
    """Return all serial device names."""
    return [i.device for i in list_ports.comports()]


class USBSerial:
    """Thin wrapper around pyserial with CRLF send and multi-line read."""

    def __init__(self, port, baud=115200, timeout=1.0):
        self.ser = serial.Serial(port=port, baudrate=baud, timeout=timeout)

    def send_line(self, line: str):
        """Send a single logical line terminated with CRLF."""
        payload = f"{line}\r\n".encode()
        self.ser.write(payload)
        self.ser.flush()

    def read_reply(self, read_timeout=0.2, idle_loops=3):
        """
        Collect multi-line reply.
        We keep reading lines until 'idle_loops' consecutive timeouts occur.
        Returns the whole reply as a string (may contain multiple lines).
        """
        old_timeout = self.ser.timeout
        self.ser.timeout = read_timeout
        lines = []
        idle = 0
        while idle < idle_loops:
            chunk = self.ser.read_until()  # up to '\n' or timeout
            if chunk:
                try:
                    s = chunk.decode(errors="replace").rstrip("\r\n")
                except Exception:
                    s = repr(chunk)
                lines.append(s)
                idle = 0
            else:
                idle += 1
        self.ser.timeout = old_timeout
        return "\n".join(lines)

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass


def first_json_line(text: str):
    """Return the first line that parses as JSON; None if not found."""
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("{") or s.startswith("[") or s.startswith('"') or s[:1].isdigit() or s[:1] in "tfn":  # true/false/null/number
            try:
                return json.loads(s)
            except Exception:
                continue
    return None


def main():
    parser = argparse.ArgumentParser(description="Send data to Pico over USB CDC")
    parser.add_argument("args", nargs="*", help="Raw tokens or a JSON string (when --json or startswith '{')")
    parser.add_argument("--port", help="Serial port (auto-detect if omitted)")
    parser.add_argument("--baud", type=int, default=115200, help="Baudrate (default 115200)")
    parser.add_argument("--timeout", type=float, default=1.0, help="Open/read timeout in seconds")
    parser.add_argument("--read-timeout", type=float, default=0.2, help="Per-line read timeout in seconds")
    parser.add_argument("--idle-loops", type=int, default=3, help="Consecutive empty reads to stop collecting")
    parser.add_argument("--json", action="store_true", help="Treat input as a JSON command (string or tokens)")
    parser.add_argument("--json-only", action="store_true", help="Print only the first JSON line from the reply")
    parser.add_argument("--file", help="Read command content from a file (raw or JSON)")
    parser.add_argument("--echo", action="store_true", help="Echo the command being sent")
    args = parser.parse_args()

    # Resolve port
    port = args.port
    if not port:
        cands = find_pico_ports()
        if not cands:
            allp = list_all_ports()
            if not allp:
                print("ERROR: No serial ports found", file=sys.stderr)
                sys.exit(2)
            port = allp[0]
            print(f"WARNING: Pico not detected; falling back to {port}", file=sys.stderr)
        else:
            port = cands[0]

    # Build the command line to send
    if args.file:
        try:
            with open(args.file, "r", encoding="utf-8") as f:
                content = f.read().strip()
        except Exception as e:
            print(f"ERROR: Failed to read {args.file}: {e}", file=sys.stderr)
            sys.exit(3)
        # If --json not forced, auto-detect JSON by leading '{' or '['
        is_json = args.json or (content[:1] in "{[")
        line_to_send = content if is_json else " ".join(content.split())
    else:
        # If --json set, join remaining args as a single string (could be full JSON)
        if args.json:
            # If user passed a literal JSON string, just use it.
            if len(args.args) == 1 and args.args[0].lstrip().startswith(("{", "[")):
                line_to_send = args.args[0]
            else:
                # Or construct a minimal JSON from tokens, e.g. --json ON 1 2 3 -> {"cmd":"ON","pins":[1,2,3]}
                toks = args.args[:]
                if not toks:
                    print("ERROR: --json used but no tokens provided", file=sys.stderr)
                    sys.exit(4)
                cmd = toks[0].upper()
                if cmd in ("ON", "ONX", "OFF"):
                    # Parse remaining tokens as ints when possible
                    pins = []
                    for t in toks[1:]:
                        try:
                            pins.append(int(t))
                        except Exception:
                            print(f"ERROR: Non-integer pin token: {t}", file=sys.stderr)
                            sys.exit(5)
                    obj = {"cmd": cmd, "pins": pins}
                elif cmd in ("PINSTAT", "PCFSTAT"):
                    if len(toks) < 2:
                        print(f"ERROR: {cmd} requires argument (ALL or <id>)", file=sys.stderr)
                        sys.exit(6)
                    which_tok = toks[1]
                    try:
                        which = int(which_tok)
                    except Exception:
                        which = which_tok  # allow "ALL"
                    obj = {"cmd": cmd, "which": which}
                elif cmd in ("ALLOFF", "PICOSTAT", "HELP"):
                    obj = {"cmd": cmd}
                else:
                    print(f"ERROR: Unknown command for JSON scaffolding: {cmd}", file=sys.stderr)
                    sys.exit(7)
                line_to_send = json.dumps(obj)
        else:
            # Raw text mode: join tokens with single spaces
            if not args.args:
                print("ERROR: No command provided", file=sys.stderr)
                sys.exit(8)
            # Auto-detect if a single JSON string was provided even without --json
            if len(args.args) == 1 and args.args[0].lstrip().startswith(("{", "[")):
                line_to_send = args.args[0]
            else:
                line_to_send = " ".join(args.args)

    if args.echo:
        print("Send", line_to_send)

    # Connect, send, read
    try:
        comm = USBSerial(port=port, baud=args.baud, timeout=args.timeout)
    except Exception as e:
        print(f"ERROR: Failed to open {port}: {e}", file=sys.stderr)
        sys.exit(9)

    try:
        comm.send_line(line_to_send)
        reply = comm.read_reply(read_timeout=args.read_timeout, idle_loops=args.idle_loops)
        if args.json_only:
            obj = first_json_line(reply)
            if obj is None:
                print("ERROR: No JSON line found in reply", file=sys.stderr)
                print(reply)
                sys.exit(10)
            print(json.dumps(obj))
        else:
            print(reply)
    finally:
        comm.close()


if __name__ == "__main__":
    main()
