import logging,os
import time
import socket
import queue
import threading
import serial

#tail -f ~/printer_data/logs/klippy.log
#cat /sys/class/thermal/thermal_zone0/temp
#~/klippy-env/bin/pip install -v bitarray

class Xaar1003:
    def __init__(self,config):
        self.printer=config.get_printer()       
        self.reactor=self.printer.get_reactor()
        self.gcode=self.printer.lookup_object('gcode')
        self.virtual_sdcard=self.printer.lookup_object("virtual_sdcard")
        #---------------通信--------------------
        self.cmd_socket = None
        self.data_socket = None
        self.test_thread=None
        self.print_data_transfer=False
        #----------控制状态--------------------
        self.head_en="0"
        self.jet_en="0"
        self.print_done=False
        self.fifo_full=False    
        #---------gcode------------------- 
        self.gcode.register_command('PRINT_INIT',self.cmd_PRINT_INIT)
        self.gcode.register_command('LOAD_CONFIG',self.cmd_LOAD_CONFIG)
        self.gcode.register_command('LOAD_PRINT_DATA',self.cmd_LOAD_PRINT_DATA)

        self.gcode.register_command('JET_ENABLE',self.cmd_JET_ENABLE)
        self.gcode.register_command('JET_DISABLE',self.cmd_JET_DISABLE)
        
        self.gcode.register_command('HEAD_DISABLE',self.cmd_HEAD_DISABLE)
        self.gcode.register_command('TEST1',self.cmd_TEST1)
        self.gcode.register_command('TEST2',self.cmd_TEST2)
        self.gcode.register_command('TEST3',self.cmd_TEST3)

    #创建发送数据，高四位为1时发送控制数据，为0时发送打印数据       
    #控制信号DATA,从高到低 待定 待定 喷墨使能 主使能

    #喷头驱动主使能 禁用
    def cmd_HEAD_DISABLE(self,gcmd):
        if not self.cmd_socket==None:
            if not self.cmd_socket._closed:
                self.cmd_socket.send(b'\x10')
                self.cmd_socket.close()
        if not self.data_socket==None:
            if not self.data_socket._closed:
                self.data_socket.close()  
        self.print_done=True
        self.head_en="0"   
        self.jet_en="0"        
        time.sleep(0.5)
        self.gcode.respond_info("Head Disable")
    #喷墨使能 启用
    def cmd_JET_ENABLE(self,gcmd):
        self.cmd_socket.send(b'\x13')  
        self.jet_en="1" 
        self.gcode.respond_info("Jet Enable")
    #喷墨使能 禁用
    def cmd_JET_DISABLE(self,gcmd):
        self.cmd_socket.send(b'\x11')  
        self.jet_en="0"    
        self.gcode.respond_info("Jet Disable") 

    def cmd_LOAD_CONFIG(self,gcmd):
        PATH=gcmd.get('PATH')
        config_file_path = os.path.join(self.virtual_sdcard.sdcard_dirname, PATH)
        self.gcode.respond_info("Loading config file:%s"%(config_file_path))

        #发送一个重置信号
        self.cmd_socket.send(b'\x11')
        self.cmd_socket.send(b'\x10')
        time.sleep(0.5)
        self.cmd_socket.send(b'\x11')
        time.sleep(0.5)
        #设置主使能状态
        self.head_en="1"  
        #读取文件并发送数据
        with open(config_file_path,"r") as file:
            content=file.read()
            self.data_socket.sendall(content.encode('utf-8'))
        time.sleep(2)
        self.gcode.respond_info("Load config done")

    #初始化
    def cmd_PRINT_INIT(self,gcmd):
        self.print_done=False
        self.fifo_full=False
        self.head_en="0"
        self.jet_en="0"
        self.cmd_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.data_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM) 
        self.cmd_socket.connect(("10.10.10.3",20001))
        self.data_socket.connect(("10.10.10.3",20000))
        self.gcode.respond_info("Init finish.")
    #将一层打印数据通过网口发送
    def cmd_LOAD_PRINT_DATA(self,gcmd):
        PATH=gcmd.get('PATH')
        data_file_path = os.path.join(self.virtual_sdcard.sdcard_dirname, PATH)
        with open(data_file_path,"r") as file:
            content=file.read()
            self.data_socket.sendall(content.encode('utf-8'))
            self.gcode.respond_info("Load print data done.")

    # TEST
    def _print(self):
        while self.print_data_transfer:
            self.gcode.respond_info("TEST loop")
            time.sleep(5)
    def cmd_TEST1(self,gcmd):
        self.gcode.respond_info("start thread")
        self.print_data_transfer=True
        self.test_thread.start()
        

    def cmd_TEST2(self,gcmd):
        self.gcode.respond_info("stop thread")
        self.print_data_transfer=False


    def cmd_TEST3(self,gcmd):
        self.gcode.respond_info("creat thread")
        self.test_thread=threading.Thread(target=self._print)

        

def load_config(config):
        return Xaar1003(config)