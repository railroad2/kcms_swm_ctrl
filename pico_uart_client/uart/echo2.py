import serial
import time

ser = serial.Serial("/dev/serial0",115200,timeout=1)

counter = 0

while True:

    msg = f"PKT:{counter}\n"
    ser.write(msg.encode())

    #line = ser.readline().decode(errors='ignore').strip()
    line = ser.readline().decode().strip()

    if line == msg.strip():
        print("OK", line)
    else:
        print("ERROR", line)

    counter += 1
    time.sleep(0.5)
