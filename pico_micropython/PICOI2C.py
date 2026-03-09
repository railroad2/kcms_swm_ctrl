from machine import I2C, Pin


class PICOI2C:
    def __init__(self):
        self.i2c = {}
        #Pin(4, mode=Pin.OUT)
        #Pin(5, mode=Pin.OUT)
        #Pin(6, mode=Pin.OUT)
        #Pin(7, mode=Pin.OUT)
        #self.i2c[0] = I2C(0, sda=Pin(0), scl=Pin(1))
        self.i2c[0] = I2C(0, sda=Pin(4), scl=Pin(5))
        self.i2c[1] = I2C(1, sda=Pin(6), scl=Pin(7))

    def scan(self,i2c_id=0):
        self.i2c[i2c_id].scan()

    def get_all_address(self):
        for i2c_id in [0, 1]:
            addresses = self.i2c[i2c_id].scan()
            for addr in addresses:
                yield i2c_id, self.i2c[i2c_id], addr

