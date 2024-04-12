import logging,os
import numpy as np
from bitarray import bitarray
from . import bus
import serial
import time
import queue

#tail -f ~/printer_data/logs/klippy.log
#cat /sys/class/thermal/thermal_zone0/temp
#~/klippy-env/bin/pip install -v bitarray

class Xaar1003:
    def __init__(self,config):
        self.printer=config.get_printer()       
        self.reactor=self.printer.get_reactor()
        #self.spi=bus.MCU_SPI_from_config(config,3)
        self.gcode=self.printer.lookup_object('gcode')
        self.virtual_sdcard=self.printer.lookup_object("virtual_sdcard")
        self.ser=serial.Serial(port='/dev/ttyUSB0',baudrate=1500000,bytesize=serial.FIVEBITS,parity=serial.PARITY_NONE,stopbits=serial.STOPBITS_ONE,timeout=0,)
        #----------控制状态--------------------
        self.head_en="0"
        self.jet_en="0"
        self.ph1="0" #占位
        self.ph2="0" #占位
        self.print_done=False
        self.fifo_full=False
        #------------------------------
        self.ctl_queue = queue.Queue()
        self.data_queue = queue.Queue()
        
        #----------------------------
        #self.gcode.register_command('HEAD_ENABLE',self.cmd_HEAD_ENABLE)    
        self.gcode.register_command('PRINT_INIT',self.cmd_PRINT_INIT)
        self.gcode.register_command('LOAD_CONFIG',self.cmd_LOAD_CONFIG)
        self.gcode.register_command('LOAD_PRINT_DATA',self.cmd_LOAD_PRINT_DATA)

        self.gcode.register_command('JET_ENABLE',self.cmd_JET_ENABLE)
        self.gcode.register_command('JET_DISABLE',self.cmd_JET_DISABLE)
        
        self.gcode.register_command('HEAD_DISABLE',self.cmd_HEAD_DISABLE)
        self.gcode.register_command('JET_TEST',self.cmd_JET_TEST)
        
    #创建发送数据，ctr_data_flag为1时发送控制数据，为0时发送打印数据
    #控制信号DATA,从低到高 主使能 喷墨使能 待定 待定
    def _make_byte(self,data,ctr_data_flag):
        try:
            data_value = int(data, 16)
            combined_value=(ctr_data_flag << 4) | data_value
            data_as_bytes = combined_value.to_bytes(1, byteorder='big')
            return data_as_bytes
        except Exception as exception_error:
            self.gcode.respond_info("data:%s"%(data))
            self.gcode.respond_info("data:%s"%(data_value))
            self.gcode.respond_info("data:%s"%(combined_value))

            self.gcode.respond_info("Error:"+str(exception_error))

    #喷头驱动主使能 禁用
    def cmd_HEAD_DISABLE(self,gcmd):
        self.print_done=True
        self.head_en="0"   
        self.jet_en="0"    
        binary_string=self.ph2+self.ph1+self.jet_en+self.head_en
        hex_string = hex(int(binary_string, 2))[2:]
        self.ctl_queue.put(self._make_byte(hex_string,1))
        time.sleep(0.5)
        self.gcode.respond_info("Head Disable")
    #喷墨使能 启用
    def cmd_JET_ENABLE(self,gcmd):
        self.jet_en="1"       
        binary_string=self.ph2+self.ph1+self.jet_en+self.head_en
        hex_string = hex(int(binary_string, 2))[2:]
        self.ctl_queue.put(self._make_byte(hex_string,1))
        self.gcode.respond_info("Jet Enable")
    #喷墨使能 禁用
    def cmd_JET_DISABLE(self,gcmd):
        self.jet_en="0"       
        binary_string=self.ph2+self.ph1+self.jet_en+self.head_en
        hex_string = hex(int(binary_string, 2))[2:]
        self.ctl_queue.put(self._make_byte(hex_string,1))
        self.gcode.respond_info("Jet Disable")

    def cmd_LOAD_CONFIG(self,gcmd):
        PATH=gcmd.get('PATH')
        config_file_path = os.path.join(self.virtual_sdcard.sdcard_dirname, PATH)
        self.gcode.respond_info("Loading config file:%s"%(config_file_path))
        #send reset signal 首先发送一个重置信号
        self.ser.write(self._make_byte("1",1))
        self.ser.write(self._make_byte("0",1))
        time.sleep(0.5)
        self.ser.write(self._make_byte("1",1))
        #设置主使能状态
        self.head_en="1"  
        #read data from file and send 读取文件并发送数据
        with open(config_file_path,"r") as file:
            content=file.read()
            for char in content:
                self.ser.write(self._make_byte(char,0))
                #self.gcode.respond_info("data:%s"%(binary_string))
        self.gcode.respond_info("Load config done")
    #通过串口发送数据
    def _serial_callback(self,eventtime):
        if not self.ctl_queue.empty():
            self.ser.write(self.ctl_queue.get())
            self.gcode.respond_info("send ctl signal")
        else:
            # 根据接收到的数据判定驱动fifo是否为满状态
            data = self.ser.read(1)  
            if data:
                if(data==b'\x1F'):
                    self.fifo_full=True
                    #self.gcode.respond_info("fifo full")
                else:
                    if(data==b'\x00'):
                        self.fifo_full=False
                        #self.gcode.respond_info("fifo not full")
            #如果fifo没满则发送多个数据           
            if self.fifo_full==False:
                queue_size=self.data_queue.qsize()
                if queue_size>0:
                    times=1024 if queue_size>1024 else queue_size
                    for _ in range(times):
                        self.ser.write(self.data_queue.get())
                    #self.gcode.respond_info("send batch data")
        #如果打印工作未结束，则注册下一次发送事件
        if(self.print_done==False):
            next_time=self.reactor.monotonic()+0.001
            self.reactor.register_callback(self._serial_callback, next_time)
    #初始化
    def cmd_PRINT_INIT(self,gcmd):
        self.print_done=False
        self.fifo_full=False
        self.head_en="0"
        self.jet_en="0"
        self.ph1="0" 
        self.ph2="0" 
        self.ctl_queue.queue.clear()
        self.data_queue.queue.clear()
        self.ser.flushOutput()
        self.ser.flushInput()
        self.reactor.register_callback(self._serial_callback)
        self.gcode.respond_info("Init finish.")
    #将一层打印数据加载进数据队列
    def cmd_LOAD_PRINT_DATA(self,gcmd):
        PATH=gcmd.get('PATH')
        data_file_path = os.path.join(self.virtual_sdcard.sdcard_dirname, PATH)
        with open(data_file_path,"r") as file:
            content=file.read()
            for char in content:
                self.data_queue.put(self._make_byte(char,0))
        d=self.data_queue.qsize()
        self.gcode.respond_info("queue size:%s"%(d))
        self.gcode.respond_info("Load print data done")

    # TEST
    def cmd_JET_TEST(self,gcmd):
        self.gcode.respond_info("TEST")

        

def load_config(config):
        return Xaar1003(config)