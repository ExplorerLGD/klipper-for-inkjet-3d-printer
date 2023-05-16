import logging,os,cv2
import numpy as np
from . import bus

#tail -f ~/printer_data/logs/klippy.log
#cat /sys/class/thermal/thermal_zone0/temp

class Inkjet:
    def __init__(self,config):
        self.printer=config.get_printer()       
        self.reactor=self.printer.get_reactor()
        self.spi=bus.MCU_SPI_from_config(config,3)
        self.gcode=self.printer.lookup_object('gcode')
        self.virtual_sdcard=self.printer.lookup_object("virtual_sdcard")
        #self.cancel = self.printer.lookup_object("CANCEL_PRINT")

        #self.cancel.register_command("INK_SPI_STOP", self.cmd_INK_SPI_STOP)

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

        self.x_num_per_frame=2
        self.y_num_per_frame=2
        self.print_x=1
        self.print_y=1
        

    def _handle_spi(self,eventtime): 
        if(self.ink_spi_enable):       
            str_test="abdc"
            send_data=""
            for y in range(self.print_y,self.y_num_per_frame+self.print_y):
                for x in range(self.print_x,self.x_num_per_frame+self.print_x):
                    for channel in range(1,self.channels):
                        send_data=send_data+str(int(self.image[y,x,channel]>0)) #可修改为不判断
            self.spi.spi_send(bytes(send_data,'utf-8'))
            self.gcode.respond_info("SPI DATA=%s"%(send_data))
            #self.gcode.respond_info("spi2 sending")
            self.print_x=self.x_num_per_frame+self.print_x+1
            self.print_y=self.y_num_per_frame+self.print_y+1
            if print_x<width and print_y<height:
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
        
        
        

    # def spi_send(self,data):
    #     self.spi.spi_send(data)

    def cmd_INK_SPI_START(self,gcmd):
        self.ink_spi_enable=True
        self.reactor.register_callback(self._handle_spi)       
        self.gcode.respond_info("Inkjet SPI enable")

    def cmd_INK_SPI_STOP(self,gcmd):
        self.ink_spi_enable=False
        self.gcode.respond_info("Inkjet SPI disable")

    def cmd_TEST_COMMAND(self,gcmd):
        self.gcode.respond_info("simple test")







def load_config(config):
    return Inkjet(config)