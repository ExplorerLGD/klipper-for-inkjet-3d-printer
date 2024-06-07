    #创建发送数据，高四位为1时发送控制数据，为0时发送打印数据       
    #控制信号DATA,从高到低 待定 待定 喷墨使能 主使能
import logging,os
import time
import socket
import queue
import threading
import serial
import multiprocessing

#tail -f ~/printer_data/logs/klippy.log
#cat /sys/class/thermal/thermal_zone0/temp
#~/klippy-env/bin/pip install -v bitarray

class Xaar1003:
    def __init__(self,config):
        self.printer=config.get_printer()       
        self.reactor=self.printer.get_reactor()
        self.gcode=self.printer.lookup_object('gcode')
        self.virtual_sdcard=self.printer.lookup_object("virtual_sdcard")
        #---------------数据通信--------------------
        #self.ser=serial.Serial(port='/dev/ttyCH9344USB3',baudrate=6000000,bytesize=serial.FIVEBITS,parity=serial.PARITY_EVEN,stopbits=serial.STOPBITS_ONE,timeout=0,)
        self.cmd_queue = multiprocessing.Queue()
        self.data_queue = multiprocessing.Queue()
        self.process_exit=multiprocessing.Value('i', 0)
        self.parent_conn, self.child_conn = multiprocessing.Pipe()

        #----------控制状态--------------------
        self.head_en=False
        self.jet_en=False
        self.print_done=False  
        #---------gcode------------------- 
        self.gcode.register_command('PRINT_INIT',self.cmd_PRINT_INIT)
        self.gcode.register_command('LOAD_CONFIG',self.cmd_LOAD_CONFIG)
        self.gcode.register_command('CREAT_PROCESS',self.cmd_CREAT_PROCESS)
        self.gcode.register_command('LOAD_PRINT_DATA',self.cmd_LOAD_PRINT_DATA)

        self.gcode.register_command('JET_ENABLE',self.cmd_JET_ENABLE)
        self.gcode.register_command('JET_DISABLE',self.cmd_JET_DISABLE)
        
        self.gcode.register_command('HEAD_DISABLE',self.cmd_HEAD_DISABLE)
        self.gcode.register_command('TEST1',self.cmd_TEST1)
        self.gcode.register_command('TEST2',self.cmd_TEST2)
        self.gcode.register_command('TEST3',self.cmd_TEST3)



        #初始化
    def cmd_PRINT_INIT(self,gcmd):
        self.print_done=False
        self.head_en=False
        self.jet_en=False
        self._clear_queue(self.data_queue)
        self._clear_queue(self.cmd_queue)
        with self.process_exit.get_lock():
            self.process_exit.value=0
        process = multiprocessing.Process(target=self._serial_process, args=(self.cmd_queue, self.data_queue,self.process_exit,))
        process.daemon=True
        process.start()
        self.gcode.respond_info("Process created.")      
        self.gcode.respond_info("Init finish.")

    def cmd_LOAD_CONFIG(self,gcmd):
        PATH=gcmd.get('PATH')
        config_file_path = os.path.join(self.virtual_sdcard.sdcard_dirname, PATH)
        self.gcode.respond_info("Loading config file:%s"%(config_file_path)) 
        retry_count=0
        while True:
            try:
                #发送一个重置信号
                self.cmd_queue.put(b'\x11')
                self.cmd_queue.put(b'\x10')
                time.sleep(0.5)
                self.cmd_queue.put(b'\x11')
                time.sleep(0.5)
                self.gcode.respond_info("Config data loading...")

                #读取文件并发送数据
                with open(config_file_path,"r") as file:
                    content=file.read()
                    while content:
                        chunk = content[:64]
                        hex_data=[int(s,16) for s in chunk]
                        bytes_data=bytes(hex_data)
                        self.data_queue.put(bytes_data)
                        content = content[64:] 
                        #读取返回信息，从高到低为: 0 满信号 tx校验 rx校验，如果是正确的校验，则返回的值应该是0
                        while self.parent_conn.poll():
                            rev=self.parent_conn.recv()
                            if rev!=0:
                                raise gcmd.error("Config data error,auto try agin...") 
                time.sleep(0.5)
                self.gcode.respond_info("Load config done")
                return
            except:
                retry_count += 1
                if retry_count >= 10:
                    raise gcmd.error("Config max retry count exceeded,Please try agin later.")
                time.sleep(1)   
    
        #将一层打印数据加载到data_queue
    
    def cmd_CREAT_PROCESS(self,gcmd):
        with self.process_exit.get_lock():
            self.process_exit.value=0
        process = multiprocessing.Process(target=self._serial_process, args=(self.cmd_queue, self.data_queue,self.process_exit,))
        process.daemon=True
        process.start()
        self.gcode.respond_info("Process created.")
    
    def cmd_LOAD_PRINT_DATA(self,gcmd):
        PATH=gcmd.get('PATH')
        data_file_path = os.path.join(self.virtual_sdcard.sdcard_dirname, PATH)
        self.data_trans_en=True
        with open(data_file_path,"r") as file:
            content=file.read()
            while content:
                    chunk = content[:512]
                    hex_data=[int(s,16) for s in chunk]
                    bytes_data=bytes(hex_data)
                    self.data_queue.put(bytes_data)
                    content = content[512:]  
        self.gcode.respond_info("Load print data done. Data size:%s"%(self.data_queue.qsize()))
    
    #喷头驱动主使能 禁用
    def cmd_HEAD_DISABLE(self,gcmd):
        self.cmd_queue.put(b'\x10')
        self.print_done=True
        self.head_en=False  
        self.jet_en=False 
        time.sleep(0.5)
        with self.process_exit.get_lock():
            self.process_exit.value=1
        self.gcode.respond_info("Head Disable")
    #喷墨使能 启用
    def cmd_JET_ENABLE(self,gcmd):
        self.cmd_queue.put(b'\x13')  
        self.jet_en=True 
        self.gcode.respond_info("Jet Enable")
    #喷墨使能 禁用
    def cmd_JET_DISABLE(self,gcmd):
        self.cmd_queue.put(b'\x11')  
        self.jet_en=False    
        self.gcode.respond_info("Jet Disable") 

    def _verify_parity(self,data_byte):
        
        data_bits = data_byte[:-1]  # 提取前4位数据位
        parity_bit = int(data_byte[-1])  # 提取最低位奇偶校验位
        calculated_parity  = 0
        for bit in data_bits:
            calculated_parity  ^= int(bit)
        if calculated_parity == parity_bit:
            return True
        else:
            return False

    def _clear_queue(self,queue):
        while not queue.empty():
            queue.get()
    def _serial_process(self,cmd_queue,data_queue,process_exit):
        fifo_full=False
        ser=serial.Serial(port='/dev/ttyCH9344USB3',baudrate=6000000,bytesize=serial.FIVEBITS,parity=serial.PARITY_EVEN,stopbits=serial.STOPBITS_ONE,timeout=0,)
        while True: 
            if process_exit.value==1:
                ser.close()
                break        
            while not cmd_queue.empty():
                cmd = cmd_queue.get()
                ser.write(bytes(cmd))
                self.gcode.respond_info("Send cmd:%s"%(cmd))

            #读取串口返回数据   
            if ser.in_waiting>0: #循环读出，直到获得最新数据
                rev = ser.read(ser.in_waiting)
                if rev[-1]==5 or rev[-1]==6:   #即接收数据00101 00110，不关心tx奇偶校验结果
                    fifo_full=True
                    self.gcode.respond_info("FIFO full.")
                else:
                    fifo_full=False
                self.child_conn.send(fifo_full)
            #如果fifo没满则发送多个数据           
            if fifo_full==False:
                queue_size=data_queue.qsize()
                if queue_size>0:
                    d=data_queue.get()
                    ser.write(d)
                    self.gcode.respond_info("send data: %d"%len(d))     


    def cmd_TEST1(self,gcmd):
        process = multiprocessing.Process(target=self._serial_process, args=(self.ser,self.cmd_queue, self.data_queue,self.process_exit,))
        self.gcode.respond_info("process_exit:%s"%(str(self.process_exit.value)))
        process.daemon=True
        process.start()

            

    def cmd_TEST2(self,gcmd):
        self.cmd_queue.put(b'\x11')
        self.cmd_queue.put(b'\x10')
        




    def cmd_TEST3(self,gcmd):
        with self.process_exit.get_lock():
            self.process_exit.value=1



        

def load_config(config):
        return Xaar1003(config)


# PRINT_INIT  ;
# LOAD_CONFIG PATH=test/config.txt;
# LOAD_PRINT_DATA PATH=test/data.txt;