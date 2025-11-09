#gpiod 需要创建用户组，创建规则文件及命令，并将当前用户添加
#FPGA USB也需要添加用户组sudo usermod -aG dialout $USER

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
from pynq.lib.video import *
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
        #self.ol.download("/home/xilinx/pl.dtbo")
        self.ch1 = self.ol.axi_dma_1
        self.ch1_buff=allocate(shape=(10*1024*1024,), dtype=np.uint8)#预分配10M缓冲区
        self.channels = [self.ch1]
        self.head_en = GPIO(GPIO.get_gpio_pin(0), 'out')
        self.head_dir = GPIO(GPIO.get_gpio_pin(1), 'out')
        self.head_jet = GPIO(GPIO.get_gpio_pin(2), 'out')
        self.jet_delay_time = MMIO(0x40000000, 0x1000) #Delay模块基址为0x40000000，大小为4K字节
        self.active_channels = 0
        #---------gcode------------------- 
        self.gcode.register_command('PRINT_INIT',self.cmd_PRINT_INIT)
        self.gcode.register_command('SET_JET_DELAY',self.cmd_SET_JET_DELAY)
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

    def _extract_compressed_file(self, file_path):
        zip_path = "/content/print.zip"

        with zipfile.ZipFile(zip_path, "r") as zf:
            with zf.open("print/CH1/1.txt") as f:   # 注意前面的 print/
                content = f.read().decode("utf-8")  # 如果有乱码换成 gbk
                return content

    def cmd_PRINT_INIT(self,gcmd):
        # 获取参数，如果没有提供，则使用默认值1
        self.active_channels = gcmd.get_int('CHANNEL_NUM', 1)
        self.ch1.sendchannel.start()
        self.ch1.recvchannel.start()
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
    def cmd_LOAD_CONFIG(self,gcmd):
        # file_name = gcmd.get('FILE')
        # directory = os.path.dirname(self.virtual_sdcard.current_file.name)
        # config_file_path = os.path.join(directory, file_name)
        with open("/home/xilinx/printer_data/gcodes/Config.txt", "r") as f:
            hex_str_config = f.read()
            config_bytes = [
                (int(hex_str_config[i+1], 16) << 4) | int(hex_str_config[i], 16)
                for i in range(0, len(hex_str_config), 2)
            ]
            config_array = np.array(config_bytes, dtype=np.uint8)
            dma_buffer = allocate(shape=config_array.shape, dtype=np.uint8)
            np.copyto(dma_buffer, config_array)
            for i in range(self.active_channels):
                self.channels[i].sendchannel.transfer(dma_buffer)
                self.channels[i].sendchannel.wait()
            del dma_buffer
        #self.gcode.respond_info("Loading config:%s" % (file_name)) 
        self.gcode.respond_info("Config finish.")

    def cmd_LOAD_PRINT_DATA(self,gcmd):
        if(self.ch1.sendchannel.idle):
            with open("/home/xilinx/printer_data/gcodes/1.txt", "r") as f:
                hex_str_config = f.read()
                data_bytes = [
                    (int(hex_str_config[i+1], 16) << 4) | int(hex_str_config[i], 16)
                    for i in range(0, len(hex_str_config), 2)
                ]
                data_array = np.array(data_bytes, dtype=np.uint8)
                np.copyto(self.ch1_buff[:len(data_array)], data_array)
                self.ch1.sendchannel.transfer(self.ch1_buff, nbytes=len(data_array))
            self.gcode.respond_info("Load print data finish.")
        else:
            self.gcode.respond_info("DMA channel busy,load print data fail.")

    def cmd_JET_ENABLE(self,gcmd):
        self.head_jet.write(1)
        self.gcode.respond_info("Jet enable.")

    def cmd_JET_DISABLE(self,gcmd):
        self.head_jet.write(0)
        self.ch1.sendchannel.stop()
        self.ch1.recvchannel.stop()
        self.gcode.respond_info("Jet disable.")

    def cmd_HEAD_DISABLE(self,gcmd):
        self.head_en.write(0)
        self.head_jet.write(0)
        self.active_channels=0
        self.gcode.respond_info("Head disable.")

    def cmd_WAIT(self,gcmd):
        time = gcmd.get_float('TIME')
        self.reactor.pause(self.reactor.monotonic()+time)

    def cmd_TEST1(self,gcmd):
        try:
            video = self.ol.video
        except Exception as e:
            self.gcode.respond_info(f"No self.ol.video: {e}")
            return

        try:
            ips = sorted(self.ol.ip_dict.keys())
            self.gcode.respond_info("Overlay IPs: " + (", ".join(ips) if ips else "<none>"))

            # video object overview
            video_attrs = [a for a in dir(video) if not a.startswith("_")]
            self.gcode.respond_info("ol.video attrs: " + (", ".join(video_attrs)))

            # check ol.video.axi_vdma
            has_axi_vdma = hasattr(video, "axi_vdma")
            axi_vdma = getattr(video, "axi_vdma", None)
            self.gcode.respond_info(f"ol.video.axi_vdma present: {has_axi_vdma}, value: {repr(axi_vdma)}")
            if axi_vdma is not None:
                self.gcode.respond_info("axi_vdma attrs: " + ", ".join([a for a in dir(axi_vdma) if not a.startswith("_")]))
            # inspect hdmi_out and its internal _vdma
            hdmi_out = getattr(video, "hdmi_out", None)
            self.gcode.respond_info(f"hdmi_out: {repr(hdmi_out)}")
            hdmi_vdma = getattr(hdmi_out, "_vdma", None) if hdmi_out is not None else None
            self.gcode.respond_info(f"hdmi_out._vdma: {repr(hdmi_vdma)}")
            if hdmi_vdma is not None:
                self.gcode.respond_info("hdmi_out._vdma attrs: " + ", ".join([a for a in dir(hdmi_vdma) if not a.startswith("_")]))

            # final helpful context
            self.gcode.respond_info(f"Overlay repr: {repr(self.ol)}")

        except Exception as ex:
            self.gcode.respond_info(f"Error during TEST1 diagnostics: {ex}")

    def cmd_TEST2(self,gcmd):
        hdmi_out = self.ol.video.hdmi_out
        Mode=VideoMode(1280, 720, 24)
        hdmi_out.configure(Mode,PIXEL_BGR)
        hdmi_out.start()
        numframes = 600
        for _ in range(numframes):
            outframe = hdmi_out.newframe()
            outframe.fill(1)
            hdmi_out.writeframe(outframe)
        hdmi_out.stop()
        hdmi_out.close()
        self.gcode.respond_info("TEST2 VDMA write complete ")




    def cmd_TEST3(self,gcmd):
        
        
        self.gcode.respond_info("TEST3 ")
        ol = Overlay("/home/xilinx/zynq.bit")
        ch1 = ol.axi_dma_1
        head_en = GPIO(GPIO.get_gpio_pin(0), 'out')
        head_dir = GPIO(GPIO.get_gpio_pin(1), 'out')
        head_jet = GPIO(GPIO.get_gpio_pin(2), 'out')
        mmio = MMIO(0x40000000, 0x1000)  # 0x1000为4K字节，和Vivado中显示的Range一致
        mmio.write(0x0, 20000000) #20MHz，延迟1S
        
#        file_name = "config.txt"
#        directory = os.path.dirname(self.virtual_sdcard.sdcard_dirname)
#        file_path = os.path.join(directory,file_name)
#        self.gcode.respond_info("Loading print data:%s"%(file_path)) 
        
        # 读取并解析txt文件
        # 读取并解析Config.txt
        with open("/home/xilinx/printer_data/gcodes/Config.txt", "r") as f:
            hex_str_config = f.read()
        byte_list = [
            (int(hex_str_config[i+1], 16) << 4) | int(hex_str_config[i], 16)
            for i in range(0, len(hex_str_config), 2)
        ]
        # 读取并解析1.txt
        with open("/home/xilinx/printer_data/gcodes/1.txt", "r") as f:
            hex_str_print = f.read()
        self.gcode.respond_info(f'hex_str_print length: {len(hex_str_print)}')
        printData_list = [
            (int(hex_str_print[i+1], 16) << 4) | int(hex_str_print[i], 16)
            for i in range(0, len(hex_str_print), 2)
        ]
        # 合并两个列表
        merged_list = byte_list + printData_list
        data_array = np.array(merged_list, dtype=np.uint8)
        ch1_buffer = allocate(shape=data_array.shape, dtype=np.uint8)
        np.copyto(ch1_buffer, data_array)
        
        head_jet.write(0)
        time.sleep(2)
        head_en.write(1)
        time.sleep(0.5)
        head_en.write(0)
        time.sleep(0.5)
        head_en.write(1)
        
        
        
        # 启动 DMA 传输
        ch1.sendchannel.transfer(ch1_buffer)
        ch1.sendchannel.wait()
    
        
        time.sleep(5)
        head_jet.write(1)
        time.sleep(50)
        head_en.write(0)
        del ch1_buffer
        self.gcode.respond_info("DMA send complete")

def load_config(config):
        return Xaar1003(config)
