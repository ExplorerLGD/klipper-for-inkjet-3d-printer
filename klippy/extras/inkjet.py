from pynq import Overlay
from pynq import PL

class Inkjet:
    def __init__(self,config):
        self.printer=config.get_printer()       
        self.reactor=self.printer.get_reactor()
        self.gcode=self.printer.lookup_object('gcode')
        #----------
        self.gcode.register_command('WAIT',self.cmd_WAIT)
        self.gcode.register_command('UV_LED',self.cmd_UV_LED)
        self.gcode.register_command('RESET_FPGA',self.cmd_RESET_FPGA)

    def cmd_WAIT(self,gcmd):
        time = gcmd.get_float('TIME')
        self.gcode.respond_info("Wait for %f seconds."%(time))
        self.reactor.pause(self.reactor.monotonic()+time)
        self.gcode.respond_info("Wait finish.")
        

    def cmd_UV_LED(self,gcmd):
        value = gcmd.get_int('VALUE', 0, minval=0, maxval=1)
        delay_time = gcmd.get_float('DELAY_TIME')
        if(value):
            current_time = self.reactor.monotonic() 
            target_time = current_time + delay_time
            self.gcode.respond_info("Wait for %f seconds."%(delay_time))
            #call_back = lambda eventtime: self.gcode.run_script_from_command("SET_PIN PIN=uv_led VALUE=1")
            self.reactor.register_callback(self._led_callback, target_time)
        else:
            self.gcode.run_script_from_command("SET_PIN PIN=uv_led VALUE=0")
    def _led_callback(self, eventtime):
        self.gcode.run_script_from_command("SET_PIN PIN=uv_led VALUE=1")  
        self.gcode.respond_info("led on.")  

    def cmd_RESET_FPGA(self,gcmd):
        PL.reset()
        Overlay("/home/xilinx/zynq.bit")
        self.gcode.respond_info("FPGA reset finish.")

def load_config(config):
    return Inkjet(config)