import klippy

class Inkjet:
    def __init__(self,config):
        self.printer=config.get_printer()
        self.gcode=self.printer.lookup_object('gcode')
        self.gcode.register_command('INKJET_COMMAND',self.cmd_INKJET_COMMAND,desc=self.cmd_INKJET_COMMAND_help)
    
    
    
    
    cmd_INKJET_COMMAND_help="ink jet!"

    def cmd_INKJET_COMMAND(self,params):
        self.gcode.respond_info("Hello from MyPlugin!")

def load_config(config):
    return Inkjet(config)