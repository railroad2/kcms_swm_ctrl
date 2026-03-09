# 2026-03-09
# assisted by ChatGPT 5.4

import utime
from machine import UART, Pin

from picocmd import Controller, PicoState, CommandError


# UART configuration
UART_ID = 0
UART_BAUDRATE = 115200
UART_TX_PIN = 0
UART_RX_PIN = 1

# Input handling
MAX_LINE_LENGTH = 512
POLL_DELAY_MS = 2


def uart_write_line(uart: UART, text: str) -> None:
    """Write one newline-terminated line to UART."""
    uart.write(text)
    uart.write("\n")


def discard_until_newline(uart: UART, timeout_ms: int = 100) -> None:
    """
    Discard input bytes until newline or timeout.

    This is used after overlong input to reduce framing damage.
    """
    start = utime.ticks_ms()

    while utime.ticks_diff(utime.ticks_ms(), start) < timeout_ms:
        if not uart.any():
            utime.sleep_ms(1)
            continue

        chunk = uart.read(1)
        if chunk is None:
            utime.sleep_ms(1)
            continue

        if chunk == b"\n":
            return


def main() -> None:
    uart = UART(
        UART_ID,
        baudrate=UART_BAUDRATE,
        tx=Pin(UART_TX_PIN),
        rx=Pin(UART_RX_PIN),
    )

    ctl = Controller()
    rx_buf = bytearray()

    ctl.set_state(PicoState.IDLE)
    uart_write_line(uart, ctl.build_ok(event="READY"))

    while True:
        try:
            if not uart.any():
                ctl.set_state(PicoState.IDLE)
                utime.sleep_ms(POLL_DELAY_MS)
                continue

            ctl.set_state(PicoState.RECEIVING)

            chunk = uart.read(1)
            if chunk is None:
                utime.sleep_ms(POLL_DELAY_MS)
                continue

            # Ignore CR to support CRLF input safely
            if chunk == b"\r":
                continue

            # Process one complete line
            if chunk == b"\n":
                ctl.set_state(PicoState.PROCESSING)

                try:
                    raw_line = bytes(rx_buf)
                    rx_buf = bytearray()

                    if not raw_line:
                        raise CommandError("empty line")

                    try:
                        line = raw_line.decode("utf-8")
                    except UnicodeError:
                        raise CommandError("invalid UTF-8")

                    response = ctl.handle_json_line(line)
                    uart_write_line(uart, response)

                    ctl.set_state(PicoState.IDLE)

                except CommandError as exc:
                    ctl.set_state(PicoState.ERROR)
                    uart_write_line(uart, ctl.build_error(str(exc)))
                    ctl.set_state(PicoState.IDLE)

                except Exception as exc:
                    ctl.set_state(PicoState.ERROR)
                    uart_write_line(
                        uart,
                        ctl.build_error(
                            "unhandled exception",
                            detail=str(exc),
                        ),
                    )
                    ctl.set_state(PicoState.IDLE)

                continue

            # Protect against oversized lines
            if len(rx_buf) >= MAX_LINE_LENGTH:
                rx_buf = bytearray()
                ctl.set_state(PicoState.ERROR)
                uart_write_line(
                    uart,
                    ctl.build_error(
                        "input line too long",
                        max_len=MAX_LINE_LENGTH,
                    ),
                )
                discard_until_newline(uart)
                ctl.set_state(PicoState.IDLE)
                continue

            rx_buf.extend(chunk)

        except Exception as exc:
            # Main-loop safety net
            rx_buf = bytearray()
            ctl.set_state(PicoState.ERROR)
            uart_write_line(
                uart,
                ctl.build_error(
                    "main loop failure",
                    detail=str(exc),
                ),
            )
            ctl.set_state(PicoState.IDLE)
            utime.sleep_ms(10)


if __name__ == "__main__":
    main()

