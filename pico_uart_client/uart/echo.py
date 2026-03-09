import serial
import time
ser = serial.Serial(
        "/dev/serial0",
        115200,
        timeout=1
        )

ser.write("echo hello pico\n".encode())
line = ser.readline()
if line:
    print("echo: ", line.decode('utf-8'))



