import logging,os
import numpy as np
from bitarray import bitarray
from . import bus

#tail -f ~/printer_data/logs/klippy.log
#cat /sys/class/thermal/thermal_zone0/temp
#~/klippy-env/bin/pip install -v bitarray

class Inkjet:
    def __init__(self,config):
        self.printer=config.get_printer()       
        self.reactor=self.printer.get_reactor()
        self.spi=bus.MCU_SPI_from_config(config,3)
        self.gcode=self.printer.lookup_object('gcode')
        self.virtual_sdcard=self.printer.lookup_object("virtual_sdcard")

        self.gcode.register_command('INIT_INKJET',self.cmd_INIT_INKJET)
        self.gcode.register_command('INK_SPI_START',self.cmd_INK_SPI_START)
        self.gcode.register_command('INK_SPI_STOP',self.cmd_INK_SPI_STOP)
        self.gcode.register_command('READ_LAYER_DATA',self.cmd_READ_LAYER_DATA)
        self.gcode.register_command('RST_INKJET',self.cmd_RST_INKJET)
        self.gcode.register_command('SET_FIFO_STATE',self.cmd_SET_FIFO_STATE)
        self.gcode.register_command('TEST_COMMAND',self.cmd_TEST_COMMAND)

        self.fpga_fifo_full=False
        self.ink_spi_enable=False
        self.byte_num=48 #SPI每次发送的byte数
        self.print_file_folder=" "

        self.sample_buffer=np.array([], dtype=np.uint8)
        self.np_data=np.array([], dtype=np.uint8)
        self.data_shape = [] 
        self.height=0
        self.width=0
        self.channels=0

        self.dir_forward=True
        self.y_num_per_frame=90
        self.print_x=1-self.channels
        self.print_y=0
        self.nozzle_num=90

        self._tail=self._get_tail()
        
    #定时执行句柄函数
    def _handle_spi(self,eventtime): 
        
        if(self.ink_spi_enable and self.print_y<self.data_shape[0]):
            #self.gcode.respond_info("_handle_spi")
            # if(self.fpga_fifo_full):
            #     next_time=eventtime+0.1  
            #     self.reactor.register_callback(self._handle_spi, next_time)
            #     return

            #循环发送缓存区数据
            #while(self.ink_spi_enable and not self.fpga_fifo_full and self.sample_buffer.size>0):   
            while(self.ink_spi_enable and len(self.sample_buffer)>=self.byte_num):            
                extracted_data=self.sample_buffer[:self.byte_num]# 取出数据
                self.spi.spi_send(extracted_data.tostring())
                self.sample_buffer=self.sample_buffer[self.byte_num:]# 移除数据

            #设定下一次函数调用时间
            next_time=self.reactor.monotonic()+0.001
            self.reactor.register_callback(self._handle_spi, next_time)
    def _get_tail(self):
        tail = '10000001001101010001001100010000'  # 十六进制数 15D4
        add_tail_arr = np.zeros((len(tail), 8), dtype=np.uint8)
        for i, bit in enumerate(tail):
            if bit == '1':
                add_tail_arr[i] = np.ones((8,), dtype=np.uint8)
        return add_tail_arr
        # 定义替换函数
    def _replace_dot_size(self,value):
        if value == 3:
            return np.array([1, 1])
        elif value == 2:
            return np.array([1, 0])
        elif value == 1:
            return np.array([0, 1])
        elif value == 0:
            return np.array([0, 0])
        else:
            return value        

    def _sample_data(self,eventtime):
        if(self.print_y>=self.data_shape[0]):#如果打印完最后一行，应该是读取下一张图，注意修改
            self.gcode.respond_info("finish read full data")
            return
        if(len(self.sample_buffer)<self.byte_num*100):#buffer大小为10倍于每次发送数据的大小

            sample_array = np.zeros((self.nozzle_num*2, self.channels), dtype=np.uint8)
            for i in range(self.channels):
                column_index = self.print_x + i  # 列索引
                if column_index < 0 or column_index >= self.np_data.shape[1] or self.print_y >= self.np_data.shape[0]:
                    sample_array[:, i] = 0  # 超出范围的位置填充为0
                else:
                    end_row_index = min(self.print_y + self.nozzle_num*2, self.np_data.shape[0]) #防止最后一行采样到空
                    sample_array[:end_row_index-self.print_y, i] = self.np_data[self.print_y:end_row_index, column_index, i]
            #插入0以及尾部信号
            add_zero_arr = np.insert(sample_array, [self.nozzle_num, self.nozzle_num*2], np.zeros(self.channels), axis=0)
            add_tail_arr=np.concatenate((add_zero_arr,self._tail),axis=0)
            packed_arr=np.packbits(add_tail_arr).astype(np.uint8)   #把数据压缩成字节
            self.sample_buffer=np.append(self.sample_buffer, packed_arr)  #写入buffer

            #设置下次打印的位置
            if(self.print_x==self.data_shape[1]-1): #采样到最右边换行
                #self.gcode.respond_info("change line")
                self.print_y=self.print_y+self.y_num_per_frame
                self.print_x=1-self.channels #注意修改
            else:
                self.print_x=self.print_x+1
        #设定下一次函数调用时间
        next_time=self.reactor.monotonic()+0.001
        self.reactor.register_callback(self._sample_data, next_time)





    #初始化喷墨
    def cmd_INIT_INKJET(self,gcmd):
        PATH = gcmd.get('PATH')        
        if PATH.startswith('/'):
            PATH = PATH[1:]       
        self.print_file_folder = os.path.join(self.virtual_sdcard.sdcard_dirname, PATH)
        shape=gcmd.get('SHAPE')
        self.data_shape = list(map(int, shape.split(',')))
        self.height, self.width, self.channels = self.data_shape
        self.gcode.respond_info("np data info: %s %s %s"% (self.height,self.width,self.channels))
        self.gcode.respond_info("Inkjet task init: %s"% (self.print_file_folder))
        

    #读取层图像
    def cmd_READ_LAYER_DATA(self,gcmd):
        file_name = gcmd.get('FILE')
        file_path=os.path.join(self.print_file_folder, file_name)
        self.gcode.respond_info("file path: %s"% (file_path))
        try:
                  
            self.np_data=np.load(file_path).reshape(tuple(self.data_shape))
            #self.np_data=np.load(file_path)
        except:
            logging.exception("virtual_sdcard np data file open")
            raise gcmd.error("%s Unable to open file"%(file_name))
        self.reactor.register_callback(self._sample_data)
        

    #开始数据传输
    def cmd_INK_SPI_START(self,gcmd):
        self.ink_spi_enable=True
        self.print_x=1-self.channels #重置后归零了，所以重新设置一下
        
        self.reactor.register_callback(self._handle_spi)     
        self.gcode.respond_info("Inkjet SPI enable")
    #停止数据传输
    def cmd_INK_SPI_STOP(self,gcmd):
        self.ink_spi_enable=False
        self.gcode.respond_info("Inkjet SPI disable")
    #设置fifo状态
    def cmd_SET_FIFO_STATE(self,gcmd):
        self.fpga_fifo_full=gcmd.get('FIFO_FULL')
        self.gcode.respond_info("Fpga full:%s"%(self.fpga_fifo_full))

    #重置喷墨
    def _rst_inkjet(self):
        self.ink_spi_enable=False
        self.np_data=np.array([])
        #self.sample_buffer=np.array([])
        self.height=0
        self.width=0
        self.channels=0

        self.x_num_per_frame=2
        self.y_num_per_frame=2
        self.print_x=0
        self.print_y=0
    #重置喷墨
    def cmd_RST_INKJET(self,gcmd):
        self._rst_inkjet()
        self.print_file_folder=" "
        self.gcode.respond_info("Inkjet module reset.")

    def cmd_TEST_COMMAND(self,gcmd):
        #data= gcmd.get('DATA')

        # data = bytearray([0b10101010])
        # data[0]|= (1 << 0)      
        # self.spi.spi_send(data)

        padded_arr=np.array([0, 1,0, 1,0, 1,0, 1])
        packed_arr=np.packbits(padded_arr)
        byte_array = bytearray(packed_arr.tobytes())

        self.spi.spi_send(byte_array)
        self.gcode.respond_info("send spi %s"%(byte_array))







def load_config(config):
    return Inkjet(config)