import utime
from machine import Pin

class LED:
    led_pin = []

    def __init__(self):
        self.led_pin = Pin("LED", Pin.OUT)

    def on(self):
        self.led_pin.on()
    
    def off(self):
        self.led_pin.off()
    
    def indicate_sw(self, nsw):
        for i in range(nsw+1):
            self.on()
            utime.sleep(0.1)
            self.off()
            utime.sleep(0.1)

    def indicate_error(self, nblk=3):
        for i in range(nblk*2):
            self.led_pin.toggle()
            utime.sleep(0.5)

