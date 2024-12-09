    #创建发送数据，高四位为1时发送控制数据，为0时发送打印数据       
    #控制信号DATA,从高到低 待定 待定 喷墨使能 主使能
#gpiod 需要创建用户组，创建规则文件及命令，并将当前用户添加
#FPGA USB也需要添加用户组sudo usermod -aG dialout $USER

import logging,os
import time
import socket
import queue
import threading
import serial
import multiprocessing
import gpiod
from gpiod.line import Edge

import binascii
class Xaar1003:
    def __init__(self,config):
        self.printer=config.get_printer()        
        self.reactor=self.printer.get_reactor()
        self.gcode=self.printer.lookup_object('gcode')
        self.virtual_sdcard=self.printer.lookup_object("virtual_sdcard")
        #---------------数据通信--------------------
        self.process = multiprocessing.Process()
        self.jet_state = multiprocessing.Value('i', 0)
        self.encoder_process = multiprocessing.Process()
        self.encoder_count = multiprocessing.Value('i', 0)
        self.process_exit=multiprocessing.Value('i', 0)
        self.file_queue=multiprocessing.Queue()
        self.cmd_queue=multiprocessing.Queue()

        #----------控制状态--------------------
        self.head_en=False
        self.jet_en=False
        self.print_done=False  
        #---------gcode------------------- 
        self.gcode.register_command('PRINT_INIT',self.cmd_PRINT_INIT)
        self.gcode.register_command('LOAD_CONFIG',self.cmd_LOAD_CONFIG)
        self.gcode.register_command('SET_PRINT_DATA_TYPE',self.cmd_SET_PRINT_DATA_TYPE)
        self.gcode.register_command('LOAD_PRINT_DATA',self.cmd_LOAD_PRINT_DATA)

        self.gcode.register_command('JET_STATE',self.cmd_JET_STATE)
        self.gcode.register_command('JET_ENABLE',self.cmd_JET_ENABLE)
        self.gcode.register_command('JET_DISABLE',self.cmd_JET_DISABLE)
        self.gcode.register_command('HEAD_DISABLE',self.cmd_HEAD_DISABLE)
        self.gcode.register_command('WAIT_ENCODER',self.cmd_WAIT_ENCODER)

        self.gcode.register_command('TEST1',self.cmd_TEST1)
        self.gcode.register_command('TEST2',self.cmd_TEST2)
        self.gcode.register_command('TEST3',self.cmd_TEST3)



        #初始化
    def cmd_PRINT_INIT(self,gcmd):
        self.print_done=False
        self.head_en=False
        self.jet_en=False
        self._clear_queue(self.file_queue)
        self._clear_queue(self.cmd_queue)
        self.encoder_count.value=0
        with self.process_exit.get_lock():
            self.process_exit.value=1
        
        time.sleep(1)
        with self.process_exit.get_lock():
            self.process_exit.value=0
        self.process = multiprocessing.Process(target=self._serial_process, args=(self.cmd_queue,self.file_queue,self.process_exit,))
        self.process.daemon=True
        self.process.start()
        self.encoder_process = multiprocessing.Process(target=self._encoder_process, args=(self.jet_state,self.cmd_queue,self.encoder_count,self.process_exit,))
        self.encoder_process.daemon=True
        self.encoder_process.start()
        self.gcode.respond_info("Process created.")      
        self.gcode.respond_info("Init finish.")

    def cmd_LOAD_CONFIG(self,gcmd):
        file_name=gcmd.get('FILE')
        directory = os.path.dirname(self.virtual_sdcard.current_file.name)
        config_file_path = os.path.join(directory, file_name)
        self.gcode.respond_info("Loading config file:%s"%(config_file_path)) 

        #发送一个重置信号
        self.cmd_queue.put(b'\x11')
        self.cmd_queue.put(b'\x10')
        time.sleep(0.5)
        self.cmd_queue.put(b'\x11')
        # self.cmd_queue.put(b'\x15')#数据类型配置为config数据
        time.sleep(1)
        self.file_queue.put(config_file_path)
    
    
    def cmd_LOAD_PRINT_DATA(self,gcmd):
        file_name=gcmd.get('FILE')
        directory = os.path.dirname(self.virtual_sdcard.current_file.name)
        data_file_path = os.path.join(directory, file_name)
        self.gcode.respond_info("Loading data file:%s"%(data_file_path)) 
        self.file_queue.put(data_file_path)
    #配置数据类型为打印数据
    def cmd_SET_PRINT_DATA_TYPE(self,gcmd):
        self.cmd_queue.put(b'\x11')
        self.gcode.respond_info("Set Print Data Type")
    #喷头驱动主使能 禁用
    def cmd_HEAD_DISABLE(self,gcmd):
        self.cmd_queue.put(b'\x10')
        self.print_done=True
        self.head_en=False  
        self.jet_en=False 
        self.jet_state.value=0
        time.sleep(1)
        with self.process_exit.get_lock():
            self.process_exit.value=1
        self.gcode.respond_info("Head Disable")
    def cmd_JET_STATE(self,gcmd):
        self.jet_state.value=gcmd.get_int('VALUE')
            
    #喷墨使能 启用
    def cmd_JET_ENABLE(self,gcmd):
        self.reactor.pause(self.reactor.monotonic()+1.0)
        self.cmd_queue.put(b'\x13')  
        self.jet_en=True 
        self.gcode.respond_info("Jet Enable")
    #喷墨使能 禁用
    def cmd_JET_DISABLE(self,gcmd):
        self.cmd_queue.put(b'\x11')  
        self.jet_en=False    
        self.gcode.respond_info("Jet Disable") 

    def cmd_WAIT_ENCODER(self,gcmd):
        value=gcmd.get_int('VALUE')
        while True:
            if self.encoder_count.value==value:
                self.gcode.respond_info("encoder number:%i"%(value))
                break
            else:
                self.reactor.pause(self.reactor.monotonic()+0.01)

    def _clear_queue(self,queue):
        while not queue.empty():
            queue.get()



    def _serial_process(self,cmd_queue,file_queue,process_exit):
        fifo_full=False
        data_queue=queue.Queue()
        #ser=serial.Serial(port='/dev/ttyACM0')
        ser=serial.Serial(port='/dev/ttyCH9344USB3',baudrate=12000000,bytesize=serial.FIVEBITS,parity=serial.PARITY_EVEN,stopbits=serial.STOPBITS_ONE,timeout=0,)
        while True: 
            #time.sleep(0.1)
            if process_exit.value==1:
                ser.flushInput()  # 清除接收缓冲区
                ser.flushOutput()  # 清除发送缓冲区
                ser.close()
                self.gcode.respond_info("serila close.")
                time.sleep(1)
                break   
            if not cmd_queue.empty():
                cmd = cmd_queue.get()
                ser.write(bytes(cmd))
                self.gcode.respond_info("Send cmd:%s"%(cmd))
            if not file_queue.empty():
                data_file_path=file_queue.get()
                with open(data_file_path,"r",encoding="utf-8-sig") as file:
                    sendtime=0
                    while True:                     
                        if process_exit.value==1:
                            break 
                        if not cmd_queue.empty():
                            cmd = cmd_queue.get()
                            ser.write(bytes(cmd))
                            self.gcode.respond_info("Send cmd:%s"%(cmd))
                        #读取串口返回数据   
                        if ser.in_waiting>0:
                            rev = ser.read(ser.in_waiting)
                            if rev[-1] == 17:  # 即接收数据10001
                                # if not fifo_full:
                                #     self.gcode.respond_info("FIFO full")
                                fifo_full = True                              
                            elif rev[-1] == 16:  # 即接收数据10000
                                # if fifo_full:
                                #     self.gcode.respond_info("FIFO not full,send time:%s"%(sendtime))
                                fifo_full = False
                            else:
                                self.gcode.respond_info("FIFO rev wrong state.")

                        #如果fifo没满则发送多个数据           
                        if fifo_full==False:
                            chunk = file.read(512)
                            sendtime+=1
                            if not chunk:                         
                                break  # 文件已读完
                            hex_data=[int(s,16) for s in chunk]
                            bytes_data=bytes(hex_data)
                            ser.write(bytes_data)
                        
                    self.gcode.respond_info("Load file finish:%s"%(os.path.basename(data_file_path)))
                    self.gcode.respond_info("this file send times:%i"%(sendtime))

    def _encoder_process(self,jet_state,cmd_queue,encoder_count,process_exit):
        ch_I = 24
        ch_A = 23
        ch_B = 22
        line_offsets=[ch_I,ch_A]
        with gpiod.request_lines(
            "/dev/gpiochip1",
            consumer="platform-encoder",
            config={tuple(line_offsets): gpiod.LineSettings(edge_detection=Edge.RISING)},
        ) as request:
            while True:
                if process_exit.value==1:
                    break 
                for event in request.read_edge_events():
                    if event.line_offset == ch_I:
                        encoder_count.value = 0
                    elif event.line_offset == ch_A:
                        encoder_count.value += 1 
                match encoder_count.value:
                    case 0:
                        if jet_state.value==1:
                            cmd_queue.put(b'\x13')
                            self.gcode.respond_info("Jet start")
                    case 1980:
                        if jet_state.value==1:
                            cmd_queue.put(b'\x11')
                            self.gcode.respond_info("Jet end")
                # if jet_state.value==1:
                #     self.gcode.respond_info("encoder number:%i"%(encoder_count.value))
                    # case 1951:
                    #     #self.z_move_queue.put(1)
                    #     self.gcode.respond_info("z move")
                    # case 1100:
                    #     self.led_queue.put(0.5)                       
                    # case 1800:
                    #     self.led_queue.put(0.0)

                    

    def cmd_TEST1(self,gcmd):
        ser=serial.Serial(port='/dev/ttyCH9344USB3',baudrate=4000000,bytesize=serial.FIVEBITS,parity=serial.PARITY_EVEN,stopbits=serial.STOPBITS_ONE,timeout=0,)
        ser.write(b'\x11')
        ser.close()
        self.gcode.respond_info("test1")

        



    def cmd_TEST2(self,gcmd):
        ser=serial.Serial(port='/dev/ttyCH9344USB3',baudrate=12000000,bytesize=serial.FIVEBITS,parity=serial.PARITY_EVEN,stopbits=serial.STOPBITS_ONE,timeout=0,)
        ser.write(b'\x10')

        ser.close()
        self.gcode.respond_info("test2")




    def cmd_TEST3(self,gcmd):
        with self.process_exit.get_lock():
            self.process_exit.value=1
        self.gcode.respond_info("process_exit:%i"%(self.process_exit.value))
        with self.process_exit.get_lock():
            self.process_exit.value=0
        self.gcode.respond_info("process_exit:%i"%(self.process_exit.value))
        self.gcode.respond_info("test3")

        

def load_config(config):
        return Xaar1003(config)
