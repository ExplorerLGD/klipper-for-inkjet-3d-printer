import logging
import cv2
from . import bus

#tail -f ~/printer_data/logs/klippy.log
class Inkjet:
    def __init__(self,config):
        self.printer=config.get_printer()
        self.reactor=self.printer.get_reactor()
        self.spi=bus.MCU_SPI_from_config(config,3)
        self.gcode=self.printer.lookup_object('gcode')
        self.gcode.register_command('INK_SPI_START',self.cmd_INK_SPI_START)
        self.gcode.register_command('INK_SPI_STOP',self.cmd_INK_SPI_STOP)
        self.gcode.register_command('TEST_COMMAND',self.cmd_TEST_COMMAND)
        self.ink_spi_enable=False
        

    def _handle_spi(self,eventtime):        
        str_test="abdc"
        self.spi_send(bytes(str_test,'utf-8'))
        self.gcode.respond_info("spi2 sending")
        next_time=eventtime+1.0
        if(self.ink_spi_enable):
            self.reactor.register_callback(self._handle_spi, next_time)

    

    def spi_send(self,data):
        self.spi.spi_send(data)

    def cmd_INK_SPI_START(self,gcmd):
        self.reactor.register_callback(self._handle_spi)
        self.ink_spi_enable=True
        self.gcode.respond_info("Inkjet SPI enable")

    def cmd_INK_SPI_STOP(self,gcmd):
        self.ink_spi_enable=False
        self.gcode.respond_info("Inkjet SPI disable")

    def cmd_TEST_COMMAND(self,gcmd):
        DATA = gcmd.get_int('DATA')
        self.state=DATA
        #self.spi_send(DATA.encode())
        self.gcode.respond_info("coddntinue=%i"% (DATA,))





def load_config(config):
    return Inkjet(config)