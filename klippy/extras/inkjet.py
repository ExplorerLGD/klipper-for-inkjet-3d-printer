import logging,os,cv2
import numpy as np
from . import bus

#tail -f ~/printer_data/logs/klippy.log
class Inkjet:
    def __init__(self,config):
        self.printer=config.get_printer()
        self.virtual_sdcard=self.printer.lookup_object("virtual_sdcard")
        self.reactor=self.printer.get_reactor()
        self.spi=bus.MCU_SPI_from_config(config,3)
        self.gcode=self.printer.lookup_object('gcode')

        self.gcode.register_command('INIT_INKJET',self.cmd_INIT_INKJET)
        self.gcode.register_command('INK_SPI_START',self.cmd_INK_SPI_START)
        self.gcode.register_command('INK_SPI_STOP',self.cmd_INK_SPI_STOP)
        self.gcode.register_command('READ_LAYER_IMAGE',self.cmd_READ_LAYER_IMAGE)
        self.gcode.register_command('TEST_COMMAND',self.cmd_TEST_COMMAND)

        self.ink_spi_enable=False
        self.print_file_folder=" "
        self.image=np.array([])
        self.height=0
        self.width=0
        self.channels=0
        

    def _handle_spi(self,eventtime): 
        if(self.ink_spi_enable):       
            str_test="abdc"
            self.spi_send(bytes(str_test,'utf-8'))
            self.gcode.respond_info("spi2 sending")
            next_time=eventtime+1.0   
            self.reactor.register_callback(self._handle_spi, next_time)

    def cmd_INIT_INKJET(self,gcmd):
        PATH = gcmd.get('PATH')
        if PATH.startswith('/'):
            PATH = PATH[1:]
        self.print_file_folder = os.path.join(self.virtual_sdcard.sdcard_dirname, PATH)
        self.gcode.respond_info("Inkjet task init: %s"% (self.print_file_folder))


    def cmd_READ_LAYER_IMAGE(self,gcmd):
        image_name = gcmd.get('IMAGE')
        file_path=os.path.join(self.print_file_folder, image_name)
        self.gcode.respond_info("file path: %s"% (file_path))
        try:
            self.image=cv2.imread(file_path,cv2.IMREAD_UNCHANGED)
            self.height, self.width, self.channels = self.image.shape
            self.gcode.respond_info("image info: %s %s %s"% (self.height,self.width,self.channels))
        except:
            logging.exception("virtual_sdcard image file open")
            raise gcmd.error("%s Unable to open file"%(image_name))
        
        
        

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
        DATA = gcmd.get('DATA')
        #path=self.virtual_sdcard.sdcard_dirname
        fname = os.path.join(self.virtual_sdcard.sdcard_dirname, DATA)
        #self.gcode.respond_info("info %s"% (fname))
        image=cv2.imread(fname,cv2.IMREAD_UNCHANGED)
        height, width, channels = image.shape
        self.gcode.respond_info("info %s %s %s"% (height,width,channels))





def load_config(config):
    return Inkjet(config)