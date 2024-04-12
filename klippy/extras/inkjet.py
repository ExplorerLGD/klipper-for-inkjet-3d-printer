import logging,os
import sys,optparse, time
import can


#tail -f ~/printer_data/logs/klippy.log
#cat /sys/class/thermal/thermal_zone0/temp
#~/klippy-env/bin/pip install -v bitarray

class Inkjet:
    def __init__(self,config):
        self.printer=config.get_printer()       
        self.reactor=self.printer.get_reactor()
        self.gcode=self.printer.lookup_object('gcode')
        #--can bus-----
        self.tp_state=False
        self.INK_TP_ID = 0x44C
        self.ink_tp_bus=None
        self.ink_tp_recv_bus=None
        #self.ink_pressure_bus=None
        #----tp setting-------
        self.ink_temperature=0
        self.ink_pressure=0
        self.ink_temperature_set=0
        self.ink_pressure_set=0
        #----------
        self.gcode.register_command('CANTEST',self.cmd_cantest)
        self.gcode.register_command('TP_ON',self.cmd_TP_ON)
        self.gcode.register_command('TP_OFF',self.cmd_TP_OFF)
        self.gcode.register_command('SET_INK_TEMP',self.cmd_SET_INK_TEMP)
        self.gcode.register_command('SET_INK_PRESS',self.cmd_SET_INK_PRESS)
        self._InitCAN()

        
    def _InitCAN(self):
        ink_tp_filters = [{"can_id": self.INK_TP_ID, "can_mask": 0x7ff,"extended": False}]
        self.ink_tp_bus = can.interface.Bus(channel="can0",bitrate=500000, can_filters=ink_tp_filters,bustype='socketcan')
        ink_tp_recv_filters = [{"can_id": self.INK_TP_ID+1, "can_mask": 0x7ff,"extended": False}]
        self.ink_tp_recv_bus = can.interface.Bus(channel="can0",bitrate=500000, can_filters=ink_tp_recv_filters,bustype='socketcan')


    def _tp_callback(self,eventtime):
        data=self.ink_tp_recv_bus.recv(0.3)
        if data is not None:
            self.gcode.respond_info("TP data:%s"%(data))
        if(self.tp_state):
            next_time=self.reactor.monotonic()+1
            self.reactor.register_callback(self._tp_callback, next_time)

    def cmd_TP_ON(self,gcmd):
        string="TP ON   "
        bytes_data = string.encode()
        byte_array = bytearray(bytes_data)
        msg = can.Message(arbitration_id=self.INK_TP_ID,data=byte_array, is_extended_id=False)
        self.ink_tp_bus.send(msg)
        self.tp_state=True
        self.reactor.register_callback(self._tp_callback)

    def cmd_TP_OFF(self,gcmd):
        string="TP OFF  "
        bytes_data = string.encode()
        byte_array = bytearray(bytes_data)
        msg = can.Message(arbitration_id=self.INK_TP_ID,data=byte_array, is_extended_id=False)
        self.ink_tp_bus.send(msg)
        self.tp_state=False

    def cmd_SET_INK_TEMP(self,gcmd):
        value = gcmd.get('VALUE')
        self.ink_temperature_set=value
        self._send_tp_setting()
    
    def cmd_SET_INK_PRESS(self,gcmd):
        value = gcmd.get('VALUE')
        self.ink_pressure_set=value
        self._send_tp_setting()

    def _send_tp_setting(self):
        self.gcode.respond_info("temp:%s pressure:%s"%(self.ink_temperature_set,self.ink_pressure_set))
        string='{:0>4}{:0>4}'.format(self.ink_temperature_set, self.ink_pressure_set)
        #string=str(self.ink_temperature)+str(self.ink_pressure)
        bytes_data = string.encode()
        byte_array = bytearray(bytes_data)
        # for i in byte_array:
        #     self.gcode.respond_info("can send msg:%s"%(i))
        msg = can.Message(arbitration_id=self.INK_TP_ID,data=byte_array, is_extended_id=False)
        self.ink_tp_bus.send(msg)

    def cmd_cantest(self,gcmd):
        self.cmd_InitCAN(gcmd)
        string = "ISEN    "
        bytes_data = string.encode()
        byte_array = bytearray(bytes_data)
        msg = can.Message(arbitration_id=self.INK_TP_ID,data=byte_array, is_extended_id=False)
        self.ink_tp_bus.send(msg)
        # self.gcode.respond_info("can send msg")
        # msg=bus.recv(1)
        # if msg is not None:
        #     self.gcode.respond_info("can recv msg:%s"%(msg.data))
        # else:
        #     self.gcode.respond_info("can recv None")










def load_config(config):
    return Inkjet(config)