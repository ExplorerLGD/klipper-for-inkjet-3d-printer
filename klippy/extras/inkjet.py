import logging,os
import sys,optparse, time
import can
import struct
#cat /sys/class/thermal/thermal_zone0/temp

class Inkjet:
    def __init__(self,config):
        self.printer=config.get_printer()       
        self.reactor=self.printer.get_reactor()
        self.gcode=self.printer.lookup_object('gcode')
        #--can bus-----
        self.INK_SUPPLY_CTL_ID = 0x44C
        self.INK_UV_LIGHT_CTL_ID = 0x44E
        #self.ink_tp_filters = [{"can_id": self.INK_SUPPLY_CTL_ID, "can_mask": 0x7ff,"extended": False}]
        #self.inkjet_bus = can.interface.Bus(channel="can0", bitrate=500000, can_filters=self.ink_tp_filters, bustype='socketcan')
        self.inkjet_bus = can.interface.Bus(channel="can0", bitrate=500000,  bustype='socketcan')
        #-----控制参数-----------
        self.ink_heat_PWM=0
        self.ink_pump_pwm=0
        self.uv_light_en=0
        self.uv_fan_en=0
        #----------
        self.gcode.register_command('CANTEST',self.cmd_cantest)
        self.gcode.register_command('INK_HEAT_PWM',self.cmd_INK_HEAT_PWM)
        self.gcode.register_command('INK_PUMP_PWM',self.cmd_INK_PUMP_PWM)
        self.gcode.register_command('UV_LIGHT_EN',self.cmd_UV_LIGHT_EN)
        self.gcode.register_command('UV_FAN_EN',self.cmd_UV_FAN_EN)
        #self._InitCAN()

    def _send_ink_supply_ctl_data(self):
        byte_array = struct.pack('HH', self.ink_heat_PWM, self.ink_pump_pwm)
        msg = can.Message(arbitration_id=self.INK_SUPPLY_CTL_ID,data=byte_array, is_extended_id=False)
        self.inkjet_bus.send(msg)

    def cmd_INK_HEAT_PWM(self,gcmd):
        pwm = gcmd.get_int('VALUE', 0, minval=0, maxval=255)
        self.ink_heat_PWM=pwm
        self._send_ink_supply_ctl_data()
        self.gcode.respond_info("Ink heat pwm: %s"%(self.ink_heat_PWM))


    def cmd_INK_PUMP_PWM(self,gcmd):
        pwm = gcmd.get_int('VALUE', 0, minval=0, maxval=4096)
        self.ink_pump_pwm=pwm
        self._send_ink_supply_ctl_data()
        self.gcode.respond_info("Ink pump pwm: %s"%(self.ink_pump_pwm))

    def _send_uv_light_ctl_data(self):
        byte_array = struct.pack('HH', self.uv_light_en, self.uv_fan_en)
        msg = can.Message(arbitration_id=self.INK_UV_LIGHT_CTL_ID,data=byte_array, is_extended_id=False)
        self.inkjet_bus.send(msg)

    def cmd_UV_LIGHT_EN(self,gcmd):
        en = gcmd.get_int('VALUE', 0, minval=0, maxval=1)
        self.uv_light_en=en
        self._send_uv_light_ctl_data()
        self.gcode.respond_info("UV light state: %s"%(self.uv_light_en))

    def cmd_UV_FAN_EN(self,gcmd):
        en = gcmd.get_int('VALUE', 0, minval=0, maxval=1)
        self.uv_fan_en=en
        self._send_uv_light_ctl_data()
        self.gcode.respond_info("UV fan state: %s"%(self.uv_fan_en))



    def cmd_cantest(self,gcmd):
        byte_array = struct.pack('BH', self.ink_heat_PWM, self.ink_pump_pwm)
        self.gcode.respond_info("pack data.")
        msg = can.Message(arbitration_id=self.INK_SUPPLY_CTL_ID,data=byte_array, is_extended_id=False)
        self.inkjet_bus.send(msg)
        # self.gcode.respond_info("can send msg")
        # msg=bus.recv(1)
        # if msg is not None:
        #     self.gcode.respond_info("can recv msg:%s"%(msg.data))
        # else:
        #     self.gcode.respond_info("can recv None")


def load_config(config):
    return Inkjet(config)