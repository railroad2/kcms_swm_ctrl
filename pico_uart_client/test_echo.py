from pico_uart_client import PicoUARTClient

with PicoUARTClient(port="/dev/serial0", baudrate=115200, debug=True) as pico:
    resp = pico.echo("hello")
    print(resp)
