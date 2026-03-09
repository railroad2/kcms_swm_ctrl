# usbcomm.py (MicroPython)
# JSON-capable line reader for USB CDC (stdin)
# - Accepts both CR and LF as line terminators
# - Backward compatible: listen() returns a decoded line (str)
# - New: listen_json() returns parsed JSON (dict/list)
# - Optional soft timeout; robust against non-JSON noise lines
#
# Usage examples:
#   line = listen(timeout_ms=0)                 # get raw text line
#   obj  = listen_json(timeout_ms=2000)         # wait up to 2s for a JSON line
#   obj  = listen_json(timeout_ms=0, strict=False)  # return None on timeout/no JSON

import sys
import select
import utime

# Use ujson on MicroPython if available for speed
try:
    import ujson as json
except ImportError:
    import json  # fallback (CPython/other ports)

DEBUG = 0
OUT_DELAY = 0.005  # 5 ms
EOLS = (b'\n', b'\r')


def _dlog(msg):
    """Write debug logs to stderr when DEBUG is enabled."""
    if DEBUG:
        try:
            sys.stderr.write(str(msg) + "\n")
        except Exception:
            pass


def _readline_bytes(timeout_ms=0):
    """
    Read one line from stdin as raw bytes.
    Accepts both CR and LF as terminators.
    Returns b'' on soft timeout if timeout_ms > 0.
    """
    poll_obj = select.poll()
    poll_obj.register(sys.stdin, select.POLLIN)

    buf = bytearray()
    start = utime.ticks_ms()

    while True:
        if poll_obj.poll(1):
            ch = sys.stdin.read(1)
            if not ch:
                utime.sleep(OUT_DELAY)
                continue

            # Normalize to bytes if some port returns str
            if isinstance(ch, str):
                ch = ch.encode()

            if ch in EOLS:
                return bytes(buf)
            else:
                buf.extend(ch)

        if timeout_ms and utime.ticks_diff(utime.ticks_ms(), start) >= timeout_ms:
            return b""

        utime.sleep(OUT_DELAY)


def listen(timeout_ms=0):
    """
    Backward-compatible text line reader.
    Returns a decoded string ('' on timeout).
    """
    raw = _readline_bytes(timeout_ms=timeout_ms)
    if not raw:
        _dlog("listen: timeout")
        return ""
    # MicroPython's .decode() does not accept keyword args; keep it simple.
    try:
        return raw.decode().strip()
    except Exception:
        try:
            return raw.decode("utf-8").strip()
        except Exception:
            # Last resort: hex string to avoid crashing
            return raw.hex()


def listen_json(timeout_ms=0, strict=True, allow_comments=False):
    """
    JSON line reader.
    - Reads lines until one is valid JSON, or until soft timeout.
    - Returns parsed JSON (dict/list/str/number/bool/null) on success.
    - Returns None on timeout if strict=False, else raises ValueError.
    - If allow_comments=True, lines starting with '#' or '//' are ignored.
    - Ignores non-JSON garbage lines silently; DEBUG logs them.

    Notes:
    - Designed for one-JSON-per-line protocol.
    - Works well with host sending CRLF-terminated JSON strings.
    """
    start = utime.ticks_ms()

    while True:
        # Compute remaining time budget if timeout was requested
        rem = 0
        if timeout_ms:
            elapsed = utime.ticks_diff(utime.ticks_ms(), start)
            if elapsed >= timeout_ms:
                if strict:
                    raise ValueError("listen_json: timeout (no JSON received)")
                return None
            rem = timeout_ms - elapsed

        line = listen(timeout_ms=rem)
        if not line:
            # Timed out or empty line
            if timeout_ms == 0:
                # Blocking mode, ignore stray empties
                continue
            else:
                if strict:
                    raise ValueError("listen_json: timeout/empty line")
                return None

        s = line.strip()
        if not s:
            continue

        # Optional comment skipping
        if allow_comments and (s.startswith("#") or s.startswith("//")):
            _dlog("listen_json: skip comment line")
            continue

        # Quick prefilter: only try JSON on lines that look like JSON
        if not (s.startswith("{") or s.startswith("[") or s.startswith('"') or s[:1].isdigit() or s.startswith("t") or s.startswith("f") or s.startswith("n")):
            _dlog("listen_json: non-JSON line ignored: " + s[:40])
            continue

        try:
            obj = json.loads(s)
            return obj
        except Exception as e:
            # Not JSON; continue reading next line
            _dlog("listen_json: parse error, ignoring line: " + repr(e))
            continue


def listen_both(timeout_ms=0):
    """
    Read one line from stdin and return both raw text and JSON if possible.
    Returns (raw_str, json_obj)
      - raw_str: the line as string ('' on timeout)
      - json_obj: parsed JSON object if line is valid JSON, else None
    """
    raw_str = listen(timeout_ms=timeout_ms)
    if not raw_str:
        return "", None

    # Try JSON parsing
    try:
        obj = json.loads(raw_str)
        return raw_str, obj
    except Exception:
        return raw_str, None
