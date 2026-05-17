# Support for the PCA9685 16-channel PWM driver ic
from . import bus, mcp4018

BACKGROUND_PRIORITY_CLOCK = 0x7fffffff00000000

# Register addresses
PCA9685_MODE1 = 0x00
PCA9685_MODE2 = 0x01
PCA9685_LED0_ON_L = 0x06
PCA9685_LED0_ON_H = 0x07
PCA9685_LED0_OFF_L = 0x08
PCA9685_LED0_OFF_H = 0x09
PCA9685_PRESCALE = 0xFE

# MODE1 bits
PCA9685_RESTART = 0x80
PCA9685_SLEEP = 0x10
PCA9685_ALLCALL = 0x01
PCA9685_AI = 0x20  # Auto-increment

# MODE2 bits
PCA9685_OUTDRV = 0x04  # Totem pole output

# PWM resolution
PCA9685_PWM_MAX = 4095

class PCA9685:
    def __init__(self, config):
        self.printer = printer = config.get_printer()
        if config.get("scl_pin", None) is not None:
            self.i2c = mcp4018.SoftwareI2C(config, 0x40)
        else:
            self.i2c = bus.MCU_I2C_from_config(config, default_addr=0x40)
        
        # Get channel count (1-16 channels supported)
        self.channel_count = config.getint("channel_count", 8, minval=1, maxval=16)
        
        # Initialize channel values
        self.channel_values = [0.0] * self.channel_count
        self.prev_regs = {}
        
        # PWM frequency (default 1000 Hz)
        self.pwm_frequency = config.getfloat("frequency", 1500.0, 
                                              minval=24.0, maxval=1526.0)
        
        # Setup LED helper for color control (channels 1-7 map to RGBWYYY or similar)
        pled = printer.load_object(config, "led")
        # Use channel_count for LED chain length (each channel = 1 LED with single color)
        self.led_helper = pled.setup_helper(config, self.update_leds, 
                                            self.channel_count)
        
        printer.register_event_handler("klippy:connect", self.handle_connect)
        
        # Register GCode commands for individual channel control
        gcode = printer.lookup_object('gcode')
        # self.name not needed for non-mux command
        self.name = config.get_name().split()[-1]
        gcode.register_command("SET_PCA9685",
                               self.cmd_SET_PCA9685_CHANNEL,
                               desc=self.cmd_SET_PCA9685_CHANNEL_help)
    
    cmd_SET_PCA9685_CHANNEL_help = "Set a PCA9685 channel PWM value"
    
    def cmd_SET_PCA9685_CHANNEL(self, gcmd):
        channel = gcmd.get_int("CHANNEL", minval=1, maxval=self.channel_count)
        value = gcmd.get_float("VALUE", minval=0.0, maxval=1.0)
        self.set_channel(channel, value)
    
    def reg_write(self, reg, val, minclock=0):
        if self.prev_regs.get(reg) == val:
            return
        self.prev_regs[reg] = val
        self.i2c.i2c_write([reg, val], minclock=minclock,
                           reqclock=BACKGROUND_PRIORITY_CLOCK)
    
    def reg_write_multi(self, reg, vals, minclock=0):
        key = (reg, tuple(vals))
        if self.prev_regs.get(reg) == key:
            return
        self.prev_regs[reg] = key
        self.i2c.i2c_write([reg] + list(vals), minclock=minclock,
                           reqclock=BACKGROUND_PRIORITY_CLOCK)
    
    def handle_connect(self):
        # Calculate prescale value for desired frequency
        # prescale = round(25MHz / (4096 * frequency)) - 1
        prescale = int(round(25000000.0 / (4096.0 * self.pwm_frequency)) - 1)
        prescale = max(3, min(255, prescale))
        
        # Configure MODE1 - put to sleep before setting prescale
        self.reg_write(PCA9685_MODE1, PCA9685_SLEEP)
        
        # Set prescale (can only be set when in sleep mode)
        self.reg_write(PCA9685_PRESCALE, prescale)
        
        # Configure MODE1 - wake up with auto-increment enabled
        self.reg_write(PCA9685_MODE1, PCA9685_AI | PCA9685_ALLCALL)
        
        # Configure MODE2 - totem pole output
        self.reg_write(PCA9685_MODE2, PCA9685_OUTDRV)
        
        # Small delay for oscillator to stabilize, then restart
        self.reg_write(PCA9685_MODE1, PCA9685_AI | PCA9685_ALLCALL | PCA9685_RESTART)
        
        # Initialize all channels to current state
        self.update_leds(self.led_helper.get_status()['color_data'], None)
    
    def set_channel_pwm(self, channel, value, minclock=0):
        """Set PWM value for a specific channel (0-indexed internally)"""
        # Calculate ON and OFF times
        # We use ON=0 and OFF=value for simplicity
        if value <= 0:
            on_time = 0
            off_time = 0
        elif value >= 1.0:
            on_time = 4096  # Full on (special case)
            off_time = 0
        else:
            on_time = 0
            off_time = int(value * PCA9685_PWM_MAX + 0.5)
        
        # Calculate register address for this channel
        reg_base = PCA9685_LED0_ON_L + (channel * 4)
        
        # Write all 4 bytes for this channel
        if value >= 1.0:
            # Full ON - set bit 4 of ON_H
            self.reg_write_multi(reg_base, [0, 0x10, 0, 0], minclock=minclock)
        elif value <= 0:
            # Full OFF - set bit 4 of OFF_H
            self.reg_write_multi(reg_base, [0, 0, 0, 0x10], minclock=minclock)
        else:
            # Normal PWM
            self.reg_write_multi(reg_base, [
                on_time & 0xFF,
                (on_time >> 8) & 0x0F,
                off_time & 0xFF,
                (off_time >> 8) & 0x0F
            ], minclock=minclock)
    
    def set_channel(self, channel, value, print_time=None):
        """Set a channel value (1-indexed for user interface)"""
        if channel < 1 or channel > self.channel_count:
            raise self.printer.command_error(
                "Channel must be between 1 and %d" % self.channel_count)
        
        minclock = 0
        if print_time is not None:
            minclock = self.i2c.get_mcu().print_time_to_clock(print_time)
        
        self.channel_values[channel - 1] = value
        self.set_channel_pwm(channel - 1, value, minclock=minclock)
    
    def update_leds(self, led_state, print_time):
        """Update channels based on LED color data"""
        minclock = 0
        if print_time is not None:
            minclock = self.i2c.get_mcu().print_time_to_clock(print_time)
        
        # Each LED in the chain controls one channel
        # led_state is a list of (red, green, blue, white) tuples
        for i, state in enumerate(led_state):
            if i >= self.channel_count:
                break
            # Use the first color component (red) as the channel value
            # Or use white if available, otherwise average
            if len(state) >= 4:
                value = state[3]  # Use white channel
            else:
                value = state[0]  # Use red channel
            
            self.channel_values[i] = value
            self.set_channel_pwm(i, value, minclock=minclock)
    
    def get_status(self, eventtime):
        return self.led_helper.get_status(eventtime)

def load_config_prefix(config):
    return PCA9685(config)