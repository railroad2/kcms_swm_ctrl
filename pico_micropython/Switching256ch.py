import utime
import pcf8575

from PICOI2C import PICOI2C
from pin_v2 import *

DEBUG=1

class Switching256ch:
    def __init__(self):
        self.PCFs = {}  # will use 16 PCF8575 chips in the end
        self.pico_i2c = PICOI2C() 

        self.__init_pcfs()  # TODO use error handle for the case no i2c found
        self.disable_all_switches()

    def __init_pcfs(self):
        for i2c_id, i2c, address in self.pico_i2c.get_all_address():
            pcf_id = i2c_to_pcf_map[f'{i2c_id}_{address}']
            self.PCFs[pcf_id] = pcf8575.PCF8575(i2c, address)

    def _switch_to_pin_num(self, switch_num):
        pin_num = switch_num % 16
        if pin_num > 7:
            pin_num += 2
        return pin_num

    def print_connected_pcfs(self):
        for key in self.PCFs:
            print(f'#{key} PCF is connected')

    def pcf_stat(self, pcf_id):
        if pcf_id in self.PCFs.keys():
            return 1
        else:
            return 0

    def print_pin_status_on_pcf(self, pcf_id=0):
        try:
            self.PCFs[pcf_id].print_pins()
        except KeyError:
            print(f'No PCF of id {pcf_id} is detected.')

    # report all switch status
    def report_switch_status(self):
        #print(f'#ALL PCF pin status')
        for key in self.PCFs:
            self.print_pin_status_on_pcf(key)

    def enable_switch(self, nsw, exclusive=False):
        if exclusive:
            self.disable_all_switches()
        pin_num = self._switch_to_pin_num(nsw)
        pcf_num = switch_to_pcf_map[nsw]
        try:
            self.PCFs[pcf_num].pin(pin_num, ON)
        except KeyError:
            if DEBUG: 
                print (f'PCF {pcf_num} is not available')
            return -1
            
        return 0

    def disable_switch(self, nsw):
        pin_num = self._switch_to_pin_num(nsw)
        pcf_num = switch_to_pcf_map[nsw]
        try:
            self.PCFs[pcf_num].pin(pin_num, OFF)
        except KeyError:
            if DEBUG: 
                print (f'PCF {pcf_num} is not available')
            return -1

        return 0

    def disable_all_switches(self):
        for key in self.PCFs:
            self.PCFs[key].port = 0x0000

