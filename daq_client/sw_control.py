#!/usr/bin/env python3

"""
sw_control.py

Remote CLI for the switching matrix WebSocket gateway.

This tool is intended to run on the DAQ PC or on the Raspberry Pi itself.
All switch control goes through the WebSocket gateway, which should be the
only owner of the Pico UART port.

Supported commands
------------------
ping
    Ping the gateway and Pico.

on <pin expressions...>
    Turn ON one or more channels.

off <pin expressions...>
    Turn OFF one or more channels.

off all
    Turn OFF all channels.

alloff
    Turn OFF all channels.

route <pin expression>
    Perform exclusive routing:
        1) ALLOFF
        2) ON exactly one target

pinstat [ALL|pcf_id|active]
    Query pin status.

pcfstat [ALL|pcf_id]
    Query PCF presence.

map
    Print matrix label -> linear pin mapping.

watch
    Subscribe to gateway state updates and redraw the matrix continuously.
"""

import argparse
import json
import sys
from typing import Dict, List

from daq_client_sync import DAQClientSync


def ansi(text: str, code: str, enable: bool = True) -> str:
    """Wrap text with ANSI color code."""
    if not enable:
        return text
    return f"\033[{code}m{text}\033[0m"


def clear_screen() -> None:
    """Clear terminal screen and move cursor to home position."""
    print("\033[2J\033[H", end="")


def print_matrix(pins: List[int], color: bool = True, frame: bool = True) -> None:
    """
    Pretty-print a 16x16 PINSTAT matrix.

    Visual rules:
    - Rows are A..P
    - Columns are 00..15
    - OFF cells are dim gray
    - ON cells are bright green
    """
    if len(pins) != 256:
        print(f"invalid pin array length: {len(pins)}")
        return

    cell_w = 3

    header_cells = [" " * cell_w]
    for col in range(16):
        header_cells.append(f"{col:>{cell_w}d}")
    header = " ".join(header_cells)

    if frame:
        border = "+" + "-" * (len(header) + 2) + "+"
        print(border)
        print("| " + header + " |")
        print("|-" + "-" * len(header) + "-|")
    else:
        print(header)

    for row in range(16):
        row_letter = chr(ord("A") + row)
        row_cells = [f"{row_letter:>{cell_w}s}"]

        for col in range(16):
            pin = row * 16 + col
            value = pins[pin]
            text = f"{value:>{cell_w}d}"

            if value:
                text = ansi(text, "1;32", enable=color)
            else:
                text = ansi(text, "90", enable=color)

            row_cells.append(text)

        line = " ".join(row_cells)

        if frame:
            print("| " + line + " |")
        else:
            print(line)

    if frame:
        print("+" + "-" * (len(header) + 2) + "+")


def print_active_labels(labels: List[str]) -> None:
    """Print active matrix labels, one per line."""
    for label in labels:
        print(label)


def print_pcf_all(present: List[int], color: bool = True, frame: bool = True) -> None:
    """Pretty-print all 16 PCF presence values."""
    if len(present) != 16:
        print(f"invalid PCF list length: {len(present)}")
        return

    cells = []
    for i, value in enumerate(present):
        text = f"{i:02d}:{value}"
        if value:
            text = ansi(text, "1;32", enable=color)
        else:
            text = ansi(text, "1;31", enable=color)
        cells.append(text)

    body = " ".join(cells)

    if frame:
        print("+" + "-" * (len(body) + 2) + "+")
        print("| " + body + " |")
        print("+" + "-" * (len(body) + 2) + "+")
    else:
        print(body)


def print_map(mapping: Dict[str, int]) -> None:
    """Print mapping as a 16x16 table."""
    header = "   " + " ".join(f"{i:02d}" for i in range(16))
    print(header)

    for row in range(16):
        row_letter = chr(ord("A") + row)
        line = [row_letter]

        for col in range(16):
            label = f"{row_letter}{col:02d}"
            pin = mapping[label]
            line.append(f"{pin:03d}")

        print(" ".join(line))


def extract_pins_from_event(event: Dict[str, object]) -> List[int]:
    """
    Extract pin array from gateway event payload.

    Supported event types:
    - get
    - pinstat_snapshot
    - pinstat_update
    """
    name = event.get("event")

    if name in ("get", "pinstat_snapshot", "pinstat_update"):
        data = event.get("data")
        if isinstance(data, dict):
            pins = data.get("pins")
            if isinstance(pins, list):
                return pins

    raise ValueError(f"event does not contain pins: {event}")


def active_labels_from_pins(pins: List[int]) -> List[str]:
    """
    Convert active pin indices to matrix labels.

    Example:
        pin 0   -> A00
        pin 57  -> D09
        pin 255 -> P15
    """
    labels = []

    for pin, value in enumerate(pins):
        if value:
            row = pin // 16
            col = pin % 16
            labels.append(f"{chr(ord('A') + row)}{col:02d}")

    return labels


def draw_watch_screen(uri: str, pins: List[int], event_name: str, color: bool, frame: bool) -> None:
    """
    Redraw terminal watch screen with matrix and active-channel list.
    """
    clear_screen()

    active = active_labels_from_pins(pins)

    print("Switching Matrix Watch")
    print(f"Gateway: {uri}")
    print(f"Event: {event_name}")
    print(f"Active channels: {len(active)}")
    print("Press Ctrl+C to exit.\n")

    print_matrix(pins, color=color, frame=frame)

    print()
    print("Active list:")

    if not active:
        print("(none)")
        return

    per_line = 12
    for i in range(0, len(active), per_line):
        print(" ".join(active[i:i + per_line]))


def cmd_ping(client: DAQClientSync, args: argparse.Namespace) -> int:
    """Handle ping command."""
    client.gateway_ping()
    client.ping()
    print("PONG")
    return 0


def cmd_on(client: DAQClientSync, args: argparse.Namespace) -> int:
    """Handle on command."""
    client.on(*args.pins)
    print("SUCCESS")
    return 0


def cmd_off(client: DAQClientSync, args: argparse.Namespace) -> int:
    """Handle off command."""
    if len(args.pins) == 1 and args.pins[0].strip().lower() == "all":
        client.alloff()
    else:
        client.off(*args.pins)
    print("SUCCESS")
    return 0


def cmd_alloff(client: DAQClientSync, args: argparse.Namespace) -> int:
    """Handle alloff command."""
    client.alloff()
    print("SUCCESS")
    return 0


def cmd_route(client: DAQClientSync, args: argparse.Namespace) -> int:
    """Handle route command."""
    client.route(*args.target)
    print("SUCCESS")
    return 0


def cmd_pinstat(client: DAQClientSync, args: argparse.Namespace) -> int:
    """Handle pinstat command."""
    arg = args.arg

    if arg == "active":
        labels = client.active_labels()
        print_active_labels(labels)
        return 0

    if arg is None or arg.upper() == "ALL":
        resp = client.pinstat("ALL")
        pins = resp["pins"]
        print_matrix(
            pins,
            color=not args.no_color,
            frame=not args.no_frame,
        )
        return 0

    which = int(arg)
    resp = client.pinstat(which)
    pins = resp["pins"]
    print(json.dumps(pins))
    return 0


def cmd_pcfstat(client: DAQClientSync, args: argparse.Namespace) -> int:
    """Handle pcfstat command."""
    arg = args.arg

    if arg is None or arg.upper() == "ALL":
        resp = client.pcfstat("ALL")
        present = resp["present"]
        print_pcf_all(
            present,
            color=not args.no_color,
            frame=not args.no_frame,
        )
        return 0

    which = int(arg)
    resp = client.pcfstat(which)
    print(resp["present"])
    return 0


def cmd_map(client: DAQClientSync, args: argparse.Namespace) -> int:
    """Handle map command."""
    mapping = client.pin_map()
    print_map(mapping)
    return 0


def cmd_watch(client: DAQClientSync, args: argparse.Namespace) -> int:
    """
    Handle watch command.

    Behavior:
    - subscribe to gateway updates
    - use subscribe snapshot as initial state
    - wait indefinitely for pinstat_update / pinstat_snapshot events
    """
    color = not args.no_color
    frame = not args.no_frame

    sub_resp = client.subscribe()

    try:
        snapshot = sub_resp["snapshot"]
        pins = extract_pins_from_event(snapshot)
        draw_watch_screen(args.uri, pins, "pinstat_snapshot", color=color, frame=frame)

        while True:
            event = client.recv_event(timeout=None)
            name = event.get("event")

            if name not in ("pinstat_update", "pinstat_snapshot"):
                continue

            pins = extract_pins_from_event(event)
            draw_watch_screen(args.uri, pins, str(name), color=color, frame=frame)

    finally:
        try:
            client.unsubscribe()
        except Exception:
            pass


def build_parser() -> argparse.ArgumentParser:
    """Build CLI parser."""
    parser = argparse.ArgumentParser(description="Remote switching matrix CLI via WebSocket")

    parser.add_argument(
        "--uri",
        default="ws://127.0.0.1:8765",
        help="gateway websocket URI",
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="request timeout in seconds",
    )

    sub = parser.add_subparsers(dest="cmd")

    p_ping = sub.add_parser("ping", help="ping gateway and Pico")
    p_ping.set_defaults(func=cmd_ping)

    p_on = sub.add_parser("on", help="turn on pins")
    p_on.add_argument("pins", nargs="+", help="pin expressions")
    p_on.set_defaults(func=cmd_on)

    p_off = sub.add_parser("off", help="turn off pins or all")
    p_off.add_argument("pins", nargs="+", help="pin expressions or 'all'")
    p_off.set_defaults(func=cmd_off)

    p_alloff = sub.add_parser("alloff", help="turn off all pins")
    p_alloff.set_defaults(func=cmd_alloff)

    p_route = sub.add_parser("route", help="ALLOFF then ON exactly one target")
    p_route.add_argument("target", nargs="+", help="single target expression")
    p_route.set_defaults(func=cmd_route)

    p_pinstat = sub.add_parser("pinstat", help="query pin status")
    p_pinstat.add_argument("arg", nargs="?", help="ALL, active, or pcf id")
    p_pinstat.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    p_pinstat.add_argument("--no-frame", action="store_true", help="disable frame border")
    p_pinstat.set_defaults(func=cmd_pinstat)

    p_pcfstat = sub.add_parser("pcfstat", help="query PCF presence")
    p_pcfstat.add_argument("arg", nargs="?", help="ALL or pcf id")
    p_pcfstat.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    p_pcfstat.add_argument("--no-frame", action="store_true", help="disable frame border")
    p_pcfstat.set_defaults(func=cmd_pcfstat)

    p_map = sub.add_parser("map", help="print matrix label to pin mapping")
    p_map.set_defaults(func=cmd_map)

    p_watch = sub.add_parser("watch", help="subscribe and watch live state updates")
    p_watch.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    p_watch.add_argument("--no-frame", action="store_true", help="disable frame border")
    p_watch.set_defaults(func=cmd_watch)

    return parser


def main() -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if args.cmd is None:
        parser.print_help()
        return 1

    try:
        with DAQClientSync(args.uri, timeout=args.timeout) as client:
            return args.func(client, args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
