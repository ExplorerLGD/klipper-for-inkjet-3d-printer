

import logging,os
import time
import queue
import multiprocessing
import zipfile
import tempfile
import shutil


from pynq import Overlay
from pynq import GPIO
import pynq.lib.dma
from pynq import allocate
from pynq import MMIO
from pynq import PL
from pynq import DefaultHierarchy
import numpy as np

class Xaar1003:
    def __init__(self,config):
        
        self.printer=config.get_printer()        
        self.reactor=self.printer.get_reactor()
        self.gcode=self.printer.lookup_object('gcode')
        self.virtual_sdcard=self.printer.lookup_object("virtual_sdcard")
        #----------overlay--------------------
        PL.reset()
        self.ol = Overlay("/home/xilinx/zynq.bit")
        self.ch1 = self.ol.channel1.axi_dma_0
        self.ch2 = self.ol.channel2.axi_dma_0
        self.ch3 = self.ol.channel3.axi_dma_0
        self.ch4 = self.ol.channel4.axi_dma_0
        self.ch5 = self.ol.channel5.axi_dma_0
        self.ch6 = self.ol.channel6.axi_dma_0
        self.ch7 = self.ol.channel7.axi_dma_0
        self.ch1_buff=allocate(shape=(5*1024*1024,), dtype=np.uint8)#预分配5M缓冲区
        self.ch2_buff=allocate(shape=(5*1024*1024,), dtype=np.uint8)
        self.ch3_buff=allocate(shape=(5*1024*1024,), dtype=np.uint8)
        self.ch4_buff=allocate(shape=(5*1024*1024,), dtype=np.uint8)
        self.ch5_buff=allocate(shape=(5*1024*1024,), dtype=np.uint8)
        self.ch6_buff=allocate(shape=(5*1024*1024,), dtype=np.uint8)
        self.ch7_buff=allocate(shape=(5*1024*1024,), dtype=np.uint8)
        self.channels = [self.ch1, self.ch2, self.ch3, self.ch4, self.ch5, self.ch6, self.ch7]
        self.ch_buffs = [self.ch1_buff, self.ch2_buff, self.ch3_buff, self.ch4_buff, self.ch5_buff, self.ch6_buff, self.ch7_buff]
        self.head_en = GPIO(GPIO.get_gpio_pin(0), 'out')
        self.head_dir = GPIO(GPIO.get_gpio_pin(1), 'out')
        self.head_jet = GPIO(GPIO.get_gpio_pin(2), 'out')
        self.jet_delay_time = MMIO(0x40000000, 0x1000) #Delay模块基址为0x40000000，大小为4K字节
        #---------gcode------------------- 
        self.gcode.register_command('PRINT_INIT',self.cmd_PRINT_INIT)
        self.gcode.register_command('SET_JET_DELAY',self.cmd_SET_JET_DELAY)
        self.gcode.register_command('LOAD_SINGLE_CONFIG',self.cmd_LOAD_SINGLE_CONFIG)
        self.gcode.register_command('LOAD_SINGLE_PRINT_DATA',self.cmd_LOAD_SINGLE_PRINT_DATA)
        self.gcode.register_command('LOAD_ZIP_CONFIG',self.cmd_LOAD_ZIP_CONFIG)
        self.gcode.register_command('LOAD_ZIP_PRINT_DATA',self.cmd_LOAD_ZIP_PRINT_DATA)

        self.gcode.register_command('JET_ENABLE',self.cmd_JET_ENABLE)
        self.gcode.register_command('JET_DISABLE',self.cmd_JET_DISABLE)
        self.gcode.register_command('HEAD_DISABLE',self.cmd_HEAD_DISABLE)

        self.gcode.register_command('TEST1',self.cmd_TEST1)
        self.gcode.register_command('TEST2',self.cmd_TEST2)
        self.gcode.register_command('TEST3',self.cmd_TEST3)

    def _extract_compressed_file(self, file_path):
        zip_path = "/content/print.zip"

        with zipfile.ZipFile(zip_path, "r") as zf:
            with zf.open("print/CH1/1.txt") as f:   # 注意前面的 print/
                content = f.read().decode("utf-8")  # 如果有乱码换成 gbk
                return content

    def cmd_PRINT_INIT(self,gcmd):
        self.ch1.sendchannel.start()
        self.head_en.write(1)
        time.sleep(0.5)
        self.head_en.write(0)
        time.sleep(0.5)
        self.head_en.write(1)
        self.gcode.respond_info("Init finish.")
    def cmd_SET_JET_DELAY(self,gcmd):
        delay_seconds = gcmd.get_float('TIME', 1.0)  # 默认1秒
        clock_freq = 20000000  # 20MHz
        delay_value = int(delay_seconds * clock_freq)
        self.jet_delay_time.write(0x0, delay_value)
        self.gcode.respond_info(f"Set jet delay time:{delay_seconds}.")
    def cmd_LOAD_SINGLE_CONFIG(self,gcmd):
        file_name = gcmd.get('FILE')
        channel_index = gcmd.get_int('CHANNEL',1)
        directory = os.path.dirname(self.virtual_sdcard.current_file.name)
        config_file_path = os.path.join(directory, file_name)
        with open(config_file_path, "r") as f:
            hex_str_config = f.read()
            config_bytes = [
                (int(hex_str_config[i+1], 16) << 4) | int(hex_str_config[i], 16)
                for i in range(0, len(hex_str_config), 2)
            ]
            config_array = np.array(config_bytes, dtype=np.uint8)
            dma_buffer = allocate(shape=config_array.shape, dtype=np.uint8)
            np.copyto(dma_buffer, config_array)
            self.channels[channel_index-1].sendchannel.transfer(dma_buffer)
            self.channels[channel_index-1].sendchannel.wait()
            del dma_buffer
        self.gcode.respond_info("Loading config:%s" % (file_name)) 

    def cmd_LOAD_SINGLE_PRINT_DATA(self,gcmd):
        file_name = gcmd.get('FILE')
        channel_index = gcmd.get_int('CHANNEL',1)
        directory = os.path.dirname(self.virtual_sdcard.current_file.name)
        data_file_path = os.path.join(directory, file_name)
        if(self.channels[channel_index-1].sendchannel.idle):
            with open(data_file_path, "r") as f:
                hex_str_config = f.read()
                data_bytes = [
                    (int(hex_str_config[i+1], 16) << 4) | int(hex_str_config[i], 16)
                    for i in range(0, len(hex_str_config), 2)
                ]
                data_array = np.array(data_bytes, dtype=np.uint8)
                np.copyto(self.ch_buffs[channel_index-1][:len(data_array)], data_array)
                self.channels[channel_index-1].sendchannel.transfer(self.ch_buffs[channel_index-1], nbytes=len(data_array))
            self.gcode.respond_info("Load print data finish.")
        else:
            self.gcode.respond_info("DMA channel busy,load print data fail.")

    def cmd_LOAD_ZIP_CONFIG(self,gcmd):
        # 获取参数，如果没有提供，则使用默认值1
        ch_index = gcmd.get_int('CHANNEL',1)
        zip_path = self.virtual_sdcard.current_zip_file
        with zipfile.ZipFile(zip_path, 'r') as zf:
            file_path = f'CH{ch_index}/Config.txt'
            with zf.open(file_path) as f:
                hex_str_config = f.read().decode('utf-8')
                config_bytes = [
                    (int(hex_str_config[j+1], 16) << 4) | int(hex_str_config[j], 16)
                    for j in range(0, len(hex_str_config), 2)
                ]
                config_array = np.array(config_bytes, dtype=np.uint8)
                dma_buffer = allocate(shape=config_array.shape, dtype=np.uint8)
                np.copyto(dma_buffer, config_array)
                self.channels[ch_index-1].sendchannel.transfer(dma_buffer)
                self.channels[ch_index-1].sendchannel.wait()
                del dma_buffer
        self.gcode.respond_info(f"Channel {ch_index} config finish.")

    def cmd_LOAD_ZIP_PRINT_DATA(self,gcmd):
        # 获取参数，如果没有提供，则使用默认值1
        ch_index = gcmd.get_int('CHANNEL',1)
        layer_index = gcmd.get_int('LAYER',1)
        zip_path = self.virtual_sdcard.current_zip_file
        with zipfile.ZipFile(zip_path, 'r') as zf:
            file_path = f'CH{ch_index}/{layer_index}.txt'
            with zf.open(file_path) as f:
                hex_str_config = f.read().decode('utf-8')
                data_bytes = [
                    (int(hex_str_config[j+1], 16) << 4) | int(hex_str_config[j], 16)
                    for j in range(0, len(hex_str_config), 2)
                ]
                data_array = np.array(data_bytes, dtype=np.uint8)
                np.copyto(self.ch1_buff[:len(data_array)], data_array)
                self.channels[ch_index-1].sendchannel.transfer(self.ch1_buff, nbytes=len(data_array))
                self.channels[ch_index-1].sendchannel.wait()
        self.gcode.respond_info(f"Channel {ch_index} layer {layer_index} load finish.")

    def cmd_JET_ENABLE(self,gcmd):
        self.head_jet.write(1)
        self.gcode.respond_info("Jet enable.")

    def cmd_JET_DISABLE(self,gcmd):
        self.head_jet.write(0)
        # self.ch1.sendchannel.stop()
        # self.ch1.recvchannel.stop()
        self.gcode.respond_info("Jet disable.")

    def cmd_HEAD_DISABLE(self,gcmd):
        self.head_en.write(0)
        self.head_jet.write(0)
        self.gcode.respond_info("Head disable.")

    def cmd_TEST1(self,gcmd):
        # file_name = gcmd.get('FILE')
        zip_path = self.virtual_sdcard.current_zip_file
        self.gcode.respond_info(zip_path)
        #config_file_path = os.path.join(zip_path, "CH1/Config.txt")
        with zipfile.ZipFile(zip_path, 'r') as zf:
            # 收集顶层目录名（只取第一个 path component）
            folders = set()
            for name in zf.namelist():
                if not name:
                    continue
                first = name.rstrip('/').split('/', 1)[0]
                if first:
                    folders.add(first)

            if not folders:
                self.gcode.respond_info("No CH directories found in zip")
            else:
                for d in folders:
                    self.gcode.respond_info(d)
            target = None
            for name in zf.namelist():
                if name.lower().endswith('ch1/config.txt'):
                    target = name
                    break
            if target is not None:
                with zf.open(target) as f:
                    content = f.read().decode('utf-8')
                    self.gcode.respond_info(content)
            else:
                self.gcode.respond_info("Config.txt not found in CH1 folder.")
        self.gcode.respond_info("TEST1 complete ")

    def cmd_TEST2(self,gcmd):
        self.gcode.respond_info("TEST2 complete ")

    def cmd_TEST3(self,gcmd):
        self.gcode.respond_info("TEST3 complete ")

def load_config(config):
        return Xaar1003(config)
