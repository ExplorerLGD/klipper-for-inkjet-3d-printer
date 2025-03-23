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
import zipfile
import tempfile
import shutil
# import gpiod
# from gpiod.line import Edge

#import binascii
class Channel:
    def __init__(self,printer,port):
        self.channel_idx=0
        self.printer=printer       
        self.reactor=self.printer.get_reactor()
        self.gcode=self.printer.lookup_object('gcode')
        self.virtual_sdcard=self.printer.lookup_object("virtual_sdcard")
        #---------------数据通信--------------------
        self.port=port
        self.process_exit=multiprocessing.Value('i', 0)
        self.file_queue=multiprocessing.Queue()
        self.cmd_queue=multiprocessing.Queue()
        #----------控制状态--------------------
        self.head_en=False
        self.jet_en=False
        self.print_done=False  
        #----------多线程----------------------
        self.process = multiprocessing.Process(target=self._serial_process, args=(self.cmd_queue,self.file_queue,self.process_exit,))
        self.process.daemon=True
        self.process.start()
    def _clear_queue(self,queue):
        while not queue.empty():
            queue.get()
    def LOAD_CONFIG(self,file_path):       
        #发送一个重置信号
        self.cmd_queue.put(b'\x11')
        self.cmd_queue.put(b'\x10')
        time.sleep(0.5)
        self.cmd_queue.put(b'\x11')
        time.sleep(1)
        self.file_queue.put(file_path)

    def LOAD_PRINT_DATA(self,file_path):
        self.file_queue.put(file_path)

    #喷墨使能 启用
    def JET_ENABLE(self):
        #self.reactor.pause(self.reactor.monotonic()+1.0)
        self.cmd_queue.put(b'\x13')  
        self.jet_en=True 
        self.gcode.respond_info("Channel %s Jet Enable"%(self.channel_idx))
    #喷墨使能 禁用
    def JET_DISABLE(self):
        self.cmd_queue.put(b'\x11')  
        self.jet_en=False    
        self.gcode.respond_info("Channel %s Jet Disable"%(self.channel_idx)) 
    #喷头驱动主使能 禁用
    def HEAD_DISABLE(self):
        self.cmd_queue.put(b'\x10')
        self.print_done=True
        self.head_en=False  
        self.jet_en=False 
        time.sleep(1)
        with self.process_exit.get_lock():
            self.process_exit.value=1
        self.gcode.respond_info("Head Disable")

    def _serial_process(self,cmd_queue,file_queue,process_exit):
        fifo_valid=True
        data_queue=queue.Queue()
        try:
            ser=serial.Serial(port=self.port)
        except serial.SerialException as e:
            self.gcode.respond_info(f"Failed to open serial port: {e}")
            return

        while True: 
            if process_exit.value==1:
                ser.flushInput()  # 清除接收缓冲区
                ser.flushOutput()  # 清除发送缓冲区
                ser.close()
                self.gcode.respond_info("serial close.")
                time.sleep(1)
                break   
            if not cmd_queue.empty():
                cmd = cmd_queue.get()
                try:
                    ser.write(bytes(cmd))
                    self.gcode.respond_info("Send cmd:%s"%(cmd))
                except serial.SerialException as e:
                    self.gcode.respond_info(f"Failed to send cmd: {e}")
            if not file_queue.empty():
                data_file_path=file_queue.get()
                try:
                    with open(data_file_path,"r",encoding="utf-8-sig") as file:
                        sendtime=0
                        while True:                     
                            if process_exit.value==1:
                                break 
                            if not cmd_queue.empty():
                                cmd = cmd_queue.get()
                                try:
                                    ser.write(bytes(cmd))
                                    self.gcode.respond_info("Send cmd:%s"%(cmd))
                                except serial.SerialException as e:
                                    self.gcode.respond_info(f"Failed to send cmd: {e}")
                            #读取串口返回数据   
                            if ser.in_waiting>0:
                                try:
                                    rev = ser.read(ser.in_waiting)
                                    if rev[-1] == 17:  
                                        fifo_valid = True                              
                                    elif rev[-1] == 16:  
                                        fifo_valid = False
                                    else:
                                        self.gcode.respond_info("FIFO rev wrong state.")
                                except serial.SerialException as e:
                                    self.gcode.respond_info(f"Failed to read from serial: {e}")

                            #如果fifo没满则发送多个数据           
                            if fifo_valid:
                                chunk = file.read(64)
                                sendtime+=1
                                if not chunk:                         
                                    break  # 文件已读完
                                try:
                                    hex_data=[int(s,16) for s in chunk]
                                    bytes_data=bytes(hex_data)
                                    ser.write(bytes_data)
                                except ValueError as e:
                                    self.gcode.respond_info(f"Failed to convert data to hex: {e}")
                                except serial.SerialException as e:
                                    self.gcode.respond_info(f"Failed to send data: {e}")
                
                        self.gcode.respond_info("Load file finish:%s"%(os.path.basename(data_file_path)))
                        self.gcode.respond_info("this file send times:%i"%(sendtime))
                except FileNotFoundError as e:
                    self.gcode.respond_info(f"File not found: {e}")
                except IOError as e:
                    self.gcode.respond_info(f"Failed to read file: {e}")
                except Exception as e:
                    self.gcode.respond_info(f"Unexpected error: {e}")

class Xaar1003:
    def __init__(self,config):
        self.printer=config.get_printer()        
        self.reactor=self.printer.get_reactor()
        self.gcode=self.printer.lookup_object('gcode')
        self.virtual_sdcard=self.printer.lookup_object("virtual_sdcard")
        #----------channel--------------------
        self.channels=[]
        #---------gcode------------------- 
        self.gcode.register_command('PRINT_INIT',self.cmd_PRINT_INIT)
        self.gcode.register_command('LOAD_CONFIG',self.cmd_LOAD_CONFIG)
        self.gcode.register_command('WAIT',self.cmd_WAIT)
        self.gcode.register_command('LOAD_PRINT_DATA',self.cmd_LOAD_PRINT_DATA)

        #self.gcode.register_command('JET_STATE',self.cmd_JET_STATE)
        self.gcode.register_command('JET_ENABLE',self.cmd_JET_ENABLE)
        self.gcode.register_command('JET_DISABLE',self.cmd_JET_DISABLE)
        self.gcode.register_command('HEAD_DISABLE',self.cmd_HEAD_DISABLE)
        #self.gcode.register_command('WAIT_ENCODER',self.cmd_WAIT_ENCODER)

        self.gcode.register_command('TEST1',self.cmd_TEST1)
        self.gcode.register_command('TEST2',self.cmd_TEST2)
        self.gcode.register_command('TEST3',self.cmd_TEST3)

    def _extract_compressed_file(self, compressed_file_path):
        extracted_files = {}  
        try:
            # 检查文件类型并处理
            if compressed_file_path.endswith('.zip'):
                subfolder_name = os.path.splitext(os.path.basename(compressed_file_path))[0]
                subfolder_path = os.path.join(os.path.dirname(compressed_file_path), subfolder_name)
                
                # 检查子目录是否存在
                if os.path.exists(subfolder_path):
                    self.gcode.respond_info(f"Subdirectory already exists: {subfolder_path}")
                    return extracted_files, subfolder_path
                
                with zipfile.ZipFile(compressed_file_path, 'r') as zip_ref:
                    os.makedirs(subfolder_path, exist_ok=True)
                    
                    # 提取所有文件到子文件夹
                    for file_name in zip_ref.namelist():
                        if not file_name.endswith('/'):  # 不是目录
                            extracted_path = os.path.join(subfolder_path, file_name)
                            os.makedirs(os.path.dirname(extracted_path), exist_ok=True)
                            with zip_ref.open(file_name) as source, open(extracted_path, 'wb') as target:
                                shutil.copyfileobj(source, target)
                            extracted_files[file_name] = extracted_path
            else:
                gcmd.error(f"不支持的压缩文件格式: {compressed_file_path}")
                
        except Exception as e:
            gcmd.error(f"解压文件出错: {str(e)}")
            shutil.rmtree(subfolder_path)
            return {}
            
        return extracted_files, subfolder_path

    def cmd_PRINT_INIT(self,gcmd):
        # 获取参数，如果没有提供，则使用默认值1
        channel_num = gcmd.get_int('CHANNEL_NUM', 1)
        # 先清理现有通道资源（如果有）
        for channel in self.channels:
            if hasattr(channel, 'HEAD_DISABLE'):
                channel.HEAD_DISABLE()
        directory = os.path.dirname(self.virtual_sdcard.current_file.name)
        self.channels = []
        # 根据channel_num创建多个Channel实例
        for i in range(channel_num):
            # 构建串口设备路径
            port = f'/dev/print_ch{i+1}'           
            # 创建Channel实例
            channel = Channel(self.printer,port) 
            channel.channel_idx = i+1          
            # 将实例添加到通道列表
            self.channels.append(channel)
            file_name=f'CH{i+1}.zip'
            channel_file_path = os.path.join(directory, file_name)
            self._extract_compressed_file(channel_file_path)
        self.gcode.respond_info("Init finish.")

    def cmd_LOAD_CONFIG(self,gcmd):
        file_name = gcmd.get('FILE')
        channel_idx = gcmd.get_int('CHANNEL_IDX')
        directory = os.path.dirname(self.virtual_sdcard.current_file.name)
        config_file_path = os.path.join(directory, file_name)
        self.channels[channel_idx-1].LOAD_CONFIG(config_file_path)
        self.gcode.respond_info("Loading config:%s"%(file_name)) 

    def cmd_LOAD_PRINT_DATA(self,gcmd):
        file_name = gcmd.get('FILE')
        channel_idx = gcmd.get_int('CHANNEL_IDX')
        directory = os.path.dirname(self.virtual_sdcard.current_file.name)
        subfolder_name=f'CH{channel_idx}'
        file_path = os.path.join(directory,subfolder_name, file_name)
        self.channels[channel_idx-1].LOAD_PRINT_DATA(file_path)
        self.gcode.respond_info("Loading print data:%s"%(file_name)) 

    def _jet_task(self,channel):
        channel.JET_ENABLE()

    def cmd_JET_ENABLE(self,gcmd):
        delay_time=gcmd.get_float('DELAY_TIME')
        current_time = self.reactor.monotonic() 
        target_time = current_time + delay_time
        
        for channel in self.channels:
            call_back=lambda e, s=self, ch=channel: s._jet_task(ch)
            self.reactor.register_callback(call_back, target_time)
            target_time=target_time+ delay_time

    def cmd_JET_DISABLE(self,gcmd):
        for channel in self.channels:
            channel.JET_DISABLE()

    def cmd_HEAD_DISABLE(self,gcmd):
        for channel in self.channels:
            channel.HEAD_DISABLE()
        self.channels = []

    def cmd_WAIT(self,gcmd):
        time = gcmd.get_float('TIME')
        self.reactor.pause(self.reactor.monotonic()+time)

    def cmd_TEST1(self,gcmd):
        #ser=serial.Serial(port='/dev/ttyCH9344USB3',baudrate=4000000,bytesize=serial.FIVEBITS,parity=serial.PARITY_EVEN,stopbits=serial.STOPBITS_ONE,timeout=0,)
        ser=serial.Serial(port='/dev/ttyACM0')
        ser.write(b'\x11')
        ser.close()
        self.gcode.respond_info("test1")

    def cmd_TEST2(self,gcmd):
        #ser=serial.Serial(port='/dev/ttyCH9344USB3',baudrate=12000000,bytesize=serial.FIVEBITS,parity=serial.PARITY_EVEN,stopbits=serial.STOPBITS_ONE,timeout=0,)
        ser=serial.Serial(port='/dev/ttyACM0')
        ser.write(b'\x10')
        ser.close()
        self.gcode.respond_info("test2")

    def cmd_TEST3(self,gcmd):
        ser=serial.Serial(port='/dev/ttyACM0')
        ser.write(b'\x01\x02\x03')
        ser.close()
        self.gcode.respond_info("test3")

def load_config(config):
        return Xaar1003(config)
