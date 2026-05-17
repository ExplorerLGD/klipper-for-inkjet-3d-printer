

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
        self.ol = Overlay("/home/xilinx/zynq.bit", download=False)
        self.ch1 = self.ol.channel1.axi_dma_0
        self.ch2 = self.ol.channel2.axi_dma_0
        self.ch3 = self.ol.channel3.axi_dma_0
        self.ch4 = self.ol.channel4.axi_dma_0
        self.ch5 = self.ol.channel5.axi_dma_0
        self.ch6 = self.ol.channel6.axi_dma_0
        self.ch7 = self.ol.channel7.axi_dma_0
        self.buff_size = 5*1024*1024
        self.ch1_buff=allocate(shape=(self.buff_size,), dtype=np.uint8)
        self.ch2_buff=allocate(shape=(self.buff_size,), dtype=np.uint8)
        self.ch3_buff=allocate(shape=(self.buff_size,), dtype=np.uint8)
        self.ch4_buff=allocate(shape=(self.buff_size,), dtype=np.uint8)
        self.ch5_buff=allocate(shape=(self.buff_size,), dtype=np.uint8)
        self.ch6_buff=allocate(shape=(self.buff_size,), dtype=np.uint8)
        self.ch7_buff=allocate(shape=(self.buff_size,), dtype=np.uint8)
        self.channels = [self.ch1, self.ch2, self.ch3, self.ch4, self.ch5, self.ch6, self.ch7]
        self.ch_buffs = [self.ch1_buff, self.ch2_buff, self.ch3_buff, self.ch4_buff, self.ch5_buff, self.ch6_buff, self.ch7_buff]
        self.print_layer_indices = [1] * len(self.channels)
        self.print_zip_file = None
        self.print_zip_names = None
        for ch in self.channels:
            ch.sendchannel.stop()
            time.sleep(0.1)
            ch.register_map.MM2S_DMACR.Reset = 1
        self.head_en = GPIO(GPIO.get_gpio_pin(2), 'out')
        self.head_dir = GPIO(GPIO.get_gpio_pin(1), 'out')
        self.head_jet = GPIO(GPIO.get_gpio_pin(0), 'out')
        self.jet_delay_time = MMIO(0x40000000, 0x1000) #Delay模块基址�?x40000000，大小为4K字节
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

    def cmd_PRINT_INIT(self,gcmd):
        self.print_layer_indices = [1] * len(self.channels)
        self.print_zip_file = None
        self.print_zip_names = None
        for ch in self.channels:
            ch.register_map.MM2S_DMACR.Reset = 1
        time.sleep(0.5)        
        self.head_jet.write(0)
        for ch in self.channels:
            ch.sendchannel.start()
        self.head_en.write(1)
        time.sleep(0.5)
        self.head_en.write(0)
        time.sleep(0.5)
        self.head_en.write(1)
        self.gcode.respond_info("Init finish.")
    def cmd_SET_JET_DELAY(self,gcmd):
        delay_seconds = gcmd.get_float('TIME', 1.0) 
        clock_freq = 100000000  # 100MHz
        delay_value = int(delay_seconds * clock_freq)
        self.jet_delay_time.write(0x0, delay_value)
        self.gcode.respond_info(f"Set jet delay time:{delay_seconds}.")
    def _wait_ch_idle(self, gcmd, ch_idx, timeout=10.0, poll=0.01):
        sendchannel = self.channels[ch_idx].sendchannel
        deadline = self.reactor.monotonic() + timeout
        while True:
            if sendchannel.error:
                raise gcmd.error(f"DMA channel {ch_idx + 1} error.")
            if sendchannel.idle:
                return
            now = self.reactor.monotonic()
            if now >= deadline:
                self.gcode.respond_info(f"DMA channel {ch_idx + 1} timeout.")
                return
                #raise gcmd.error(f"Timeout waiting DMA channel {ch_idx + 1} idle.")
            self.reactor.pause(now + poll) 
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
        self.gcode.respond_info("Load config channel %d finish." % (channel_index)) 

    def cmd_LOAD_SINGLE_PRINT_DATA(self,gcmd):
        file_name = gcmd.get('FILE')
        channel_index = gcmd.get_int('CHANNEL',1)
        directory = os.path.dirname(self.virtual_sdcard.current_file.name)
        data_file_path = os.path.join(directory, file_name)
        self._wait_ch_idle(gcmd, channel_index-1)
        if(self.channels[channel_index-1].sendchannel.idle):
            with open(data_file_path, "rb") as f:
                data = f.read()
                printdata_array = np.fromiter(data, dtype=np.uint8, count=len(data))
                dma_buffer = allocate(shape=printdata_array.shape, dtype=np.uint8)
                np.copyto(dma_buffer, printdata_array)
                self.channels[channel_index-1].sendchannel.transfer(dma_buffer)
            self.gcode.respond_info("Load print data finish.")
        else:
            self.gcode.respond_info("DMA channel busy,load print data fail.")

    def cmd_LOAD_ZIP_CONFIG(self,gcmd):
        # 获取参数，如果没有提供，则使用默认�?
        ch_index = gcmd.get_int('CHANNEL',1)
        zf = self.virtual_sdcard.current_zip_file
        if(zf is None):
            self.gcode.respond_info("No zip file loaded.")
            return
        self.gcode.respond_info(f"zf:{zf}")
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
        channel_index = gcmd.get_int('CHANNEL',1)
        ch_idx = channel_index - 1
        if ch_idx < 0 or ch_idx >= len(self.channels):
            raise gcmd.error(f"Invalid channel index: {channel_index}.")
        if self.channels[ch_idx].sendchannel.error:
            raise gcmd.error(f"DMA channel {channel_index} error.")

        if not self.channels[ch_idx].sendchannel.idle:
            self.gcode.respond_info(f"Channel {channel_index} DMA busy, load print data pending.")
            return
        zf = self.virtual_sdcard.current_zip_file
        if zf is None:
            self.gcode.respond_info("No zip file loaded.")
            return
        
        if self.print_zip_file is not zf:
            self.print_zip_file = zf
            self.print_zip_names = set(zf.namelist())
            self.print_layer_indices = [1] * len(self.channels)

        layer_index = self.print_layer_indices[ch_idx]
        file_path = f'CH{channel_index}/{layer_index}.bin'
        if file_path not in self.print_zip_names:
            self.gcode.respond_info(f"Channel {channel_index} end at chunk {layer_index - 1}.")
            return
        with zf.open(file_path) as f:
            data = f.read()
            printdata_array = np.fromiter(data, dtype=np.uint8, count=len(data))
            data_len = len(printdata_array)
            if data_len > self.buff_size:
                raise gcmd.error(f"Print data too large: {data_len} bytes.")
            np.copyto(self.ch_buffs[ch_idx][:data_len], printdata_array)
            self.channels[ch_idx].sendchannel.transfer(self.ch_buffs[ch_idx], nbytes=data_len)

        self.print_layer_indices[ch_idx] += 1
        self.gcode.respond_info(f"Channel {channel_index} layer {layer_index} load finish. bytes={data_len}.")

    def cmd_JET_ENABLE(self,gcmd):
        self.head_jet.write(1)
        self.gcode.respond_info("Jet Enable.")

    def cmd_JET_DISABLE(self,gcmd):
        self.head_jet.write(0)
        self.gcode.respond_info("Jet Disable.")

    def cmd_HEAD_DISABLE(self,gcmd):
        time.sleep(0.1)
        self.head_en.write(0)
        self.head_jet.write(0)
        self.gcode.respond_info("Head disable.")

    def cmd_TEST1(self,gcmd):
        from pynq import Clocks
        self.gcode.respond_info(f"clock {Clocks.fclk0_mhz}MHz")
        Clocks.fclk0_mhz = 100.0
        self.gcode.respond_info(f"clock {Clocks.fclk0_mhz}MHz")

    def cmd_TEST2(self,gcmd):
        self.channels[0].sendchannel.stop()
        self.channels[0].sendchannel.start()
        self.gcode.respond_info("channel 1 restart.")

    def cmd_TEST3(self,gcmd):
        if(self.channels[0].sendchannel.idle):
            self.gcode.respond_info("Channel 1 is idle.")
        if(self.channels[0].sendchannel.running):
            self.gcode.respond_info("Channel 1 is running.")
        if(self.channels[0].sendchannel.error):
            self.gcode.respond_info("Channel 1 is in error state.")
        self.gcode.respond_info("----------------------")
        # config_bytes = [i for i in range(256)] 
        # config_array = np.array(config_bytes, dtype=np.uint8)
        # dma_buffer = allocate(shape=config_array.shape, dtype=np.uint8)
        # np.copyto(dma_buffer, config_array)
        # self.channels[0].sendchannel.transfer(dma_buffer)
        # if(self.channels[0].sendchannel.idle):
        #     self.gcode.respond_info("Channel 1 is idle.")
        # if(self.channels[0].sendchannel.running):
        #     self.gcode.respond_info("Channel 1 is running.")
        # if(self.channels[0].sendchannel.error):
        #     self.gcode.respond_info("Channel 1 is in error state.")
        # self.gcode.respond_info("----------------------")
        # self.channels[0].sendchannel.wait()
        # del dma_buffer
        # if(self.channels[0].sendchannel.idle):
        #     self.gcode.respond_info("Channel 1 is idle.")
        # if(self.channels[0].sendchannel.running):
        #     self.gcode.respond_info("Channel 1 is running.")
        # if(self.channels[0].sendchannel.error):
        #     self.gcode.respond_info("Channel 1 is in error state.")

        
        self.gcode.respond_info("TEST3 complete ")

def load_config(config):
        return Xaar1003(config)
