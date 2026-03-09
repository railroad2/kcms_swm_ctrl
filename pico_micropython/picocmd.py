#2026-03-09 
# assisted by ChatGPT 5.4
import json

from Switching256ch import Switching256ch


class PicoState:
    """State names for the command processor."""

    IDLE = "IDLE"
    RECEIVING = "RECEIVING"
    PROCESSING = "PROCESSING"
    ERROR = "ERROR"


class CommandError(Exception):
    """Raised when a command is invalid or cannot be processed."""
    pass


class Controller:
    """
    JSON command controller for the switching matrix.

    Responsibilities:
    - Validate JSON commands
    - Execute hardware actions
    - Maintain 256-channel shadow state
    - Build one-line JSON responses
    """

    def __init__(self) -> None:
        self.state = PicoState.IDLE
        self.sw = Switching256ch()
        self.shadow = [0] * 256

    # -------------------------------------------------------------------------
    # State helpers
    # -------------------------------------------------------------------------
    def set_state(self, state: str) -> None:
        """Update internal state."""
        self.state = state

    # -------------------------------------------------------------------------
    # Response builders
    # -------------------------------------------------------------------------
    def build_ok(self, **payload) -> str:
        """Build a success JSON response."""
        out = {
            "ok": 1,
            "state": self.state,
        }
        out.update(payload)
        return json.dumps(out)

    def build_error(self, error: str, **payload) -> str:
        """Build an error JSON response."""
        out = {
            "ok": 0,
            "state": self.state,
            "error": str(error),
        }
        out.update(payload)
        return json.dumps(out)

    # -------------------------------------------------------------------------
    # Validators
    # -------------------------------------------------------------------------
    def _validate_pin(self, pin) -> int:
        """Validate and return one pin index."""
        if not isinstance(pin, int):
            raise CommandError("pin must be integer")

        if pin < 0 or pin > 255:
            raise CommandError("pin out of range")

        return pin

    def _validate_pins(self, pins) -> list:
        """Validate and return a non-empty pin list."""
        if not isinstance(pins, list):
            raise CommandError("pins must be list")

        if len(pins) == 0:
            raise CommandError("pins list is empty")

        validated = []
        for pin in pins:
            validated.append(self._validate_pin(pin))

        return validated

    def _validate_pcf(self, pcf) -> int:
        """Validate and return one PCF index."""
        if not isinstance(pcf, int):
            raise CommandError("pcf id must be integer")

        if pcf < 0 or pcf > 15:
            raise CommandError("pcf id out of range")

        return pcf

    # -------------------------------------------------------------------------
    # Commands
    # -------------------------------------------------------------------------
    def cmd_echo(self, msg):
        """Return the given payload unchanged."""
        return self.build_ok(
            cmd="ECHO",
            echo=msg,
        )

    def cmd_ping(self):
        """Simple liveness check."""
        return self.build_ok(
            cmd="PING",
            pong=1,
        )

    def cmd_on(self, pins):
        """Turn ON a list of channels."""
        validated_pins = self._validate_pins(pins)
        results = []

        for pin in validated_pins:
            res = self.sw.enable_switch(pin)

            if res != 0:
                raise CommandError("hardware failure on pin {}".format(pin))

            self.shadow[pin] = 1
            results.append({
                "pin": pin,
                "state": 1,
            })

        return self.build_ok(
            cmd="ON",
            results=results,
        )

    def cmd_off(self, pins):
        """Turn OFF a list of channels."""
        validated_pins = self._validate_pins(pins)
        results = []

        for pin in validated_pins:
            res = self.sw.disable_switch(pin)

            if res != 0:
                raise CommandError("hardware failure on pin {}".format(pin))

            self.shadow[pin] = 0
            results.append({
                "pin": pin,
                "state": 0,
            })

        return self.build_ok(
            cmd="OFF",
            results=results,
        )

    def cmd_alloff(self):
        """Turn OFF all channels."""
        self.sw.disable_all_switches()
        self.shadow = [0] * 256

        return self.build_ok(
            cmd="ALLOFF",
        )

    def cmd_pinstat(self, which):
        """
        Return switch shadow state.

        Supported forms:
        - {"cmd":"PINSTAT","which":"ALL"}
        - {"cmd":"PINSTAT","which":0}
        """
        if which == "ALL":
            return self.build_ok(
                cmd="PINSTAT",
                which="ALL",
                pins=self.shadow,
            )

        pcf = self._validate_pcf(which)
        start = pcf * 16
        end = start + 16

        return self.build_ok(
            cmd="PINSTAT",
            which=pcf,
            pcf=pcf,
            pins=self.shadow[start:end],
        )

    def cmd_pcfstat(self, which):
        """
        Return PCF presence state.

        Supported forms:
        - {"cmd":"PCFSTAT","which":"ALL"}
        - {"cmd":"PCFSTAT","which":0}
        """
        if which == "ALL":
            present = []
            for pcf in range(16):
                present.append(int(self.sw.pcf_stat(pcf)))

            return self.build_ok(
                cmd="PCFSTAT",
                which="ALL",
                present=present,
            )

        pcf = self._validate_pcf(which)

        return self.build_ok(
            cmd="PCFSTAT",
            which=pcf,
            pcf=pcf,
            present=int(self.sw.pcf_stat(pcf)),
        )

    # -------------------------------------------------------------------------
    # Dispatcher
    # -------------------------------------------------------------------------
    def handle_json_object(self, obj) -> str:
        """Validate and dispatch one parsed JSON object."""
        if not isinstance(obj, dict):
            raise CommandError("JSON root must be object")

        cmd = obj.get("cmd")
        if not isinstance(cmd, str):
            raise CommandError("missing or invalid cmd")

        cmd = cmd.strip().upper()
        if not cmd:
            raise CommandError("empty cmd")

        if cmd == "ECHO":
            if "msg" not in obj:
                raise CommandError("missing msg")
            return self.cmd_echo(obj.get("msg"))

        if cmd == "PING":
            return self.cmd_ping()

        if cmd == "ON":
            if "pins" not in obj:
                raise CommandError("missing pins")
            return self.cmd_on(obj.get("pins"))

        if cmd == "OFF":
            if "pins" not in obj:
                raise CommandError("missing pins")
            return self.cmd_off(obj.get("pins"))

        if cmd == "ALLOFF":
            return self.cmd_alloff()

        if cmd == "PINSTAT":
            if "which" not in obj:
                raise CommandError("missing which")
            return self.cmd_pinstat(obj.get("which"))

        if cmd == "PCFSTAT":
            if "which" not in obj:
                raise CommandError("missing which")
            return self.cmd_pcfstat(obj.get("which"))

        raise CommandError("unknown command")

    def handle_json_line(self, line: str) -> str:
        """Parse and handle one JSON command line."""
        if not isinstance(line, str):
            raise CommandError("internal error: line must be string")

        stripped = line.strip()
        if not stripped:
            raise CommandError("empty line")

        try:
            obj = json.loads(stripped)
        except ValueError:
            raise CommandError("invalid JSON")

        return self.handle_json_object(obj)

