#!/usr/bin/env python
import sys
from collections import OrderedDict, defaultdict
import yaml
import math

from verilogwriter import Signal, Wire, Instance, ModulePort, VerilogWriter, LocalParam, Assign

AHB3_MASTER_PORTS = [
  Signal('HSEL'),
  Signal('HADDR', 32),
  Signal('HWDATA', 32),
  Signal('HWRITE'),
  Signal('HSIZE', 3),
  Signal('HBURST', 3),
  Signal('HPROT', 4),
  Signal('HTRANS', 2),
  Signal('HMASTLOCK'),
  Signal('HREADY'),
]

AHB3_SLAVE_PORTS  = [
  Signal('HRDATA', 32),
  Signal('HRESP'),
  Signal('HREADYOUT'),
]

AHB3_DATA_WIDTH = defaultdict(float, { 'dat': 1.0 })

class Error(Exception):
  """Base error for ahb3_intercon_gen"""

class UnknownPropertyError(Error):
  """An unknown property was encounterned while parsing the config file."""

def parse_number(s):
    if type(s) == int:
        return s
    if s.startswith('0x'):
        return int(s, 16)
    else:
        return int(s)

class Master:
    def __init__(self, name, index, d=None):
        self.name = name
        self.index = index
        self.datawidth = 32
        self.slaves = []
        self.priority = 0
        if d:
            self.load_dict(d)

    def load_dict(self, d):
      for key, value in d.items():
        if key == 'priority':
          self.priority = int (value)
        elif key == 'slaves':
          self.slaves = value
        else:
          raise UnknownPropertyError(
            "Unknown property '%s' in master section '%s'" % (
              key, self.name))

class Slave:
    def __init__(self, name, index, d=None):
        self.name = name
        self.index = index
        self.masters = []
        self.datawidth = 32
        self.offset = 0
        self.size = 0
        self.mask = 0
        if d:
            self.load_dict(d)

    def load_dict(self, d):
        for key, value in d.items():
            if key == 'datawidth':
                self.datawidth = parse_number(value)
            elif key == 'offset':
                self.offset = parse_number(value)
            elif key == 'size':
                self.size = parse_number(value)
                self.mask = ~(self.size-1) & 0xffffffff
            else:
                raise UnknownPropertyError(
                    "Unknown property '%s' in slave section '%s'" % (
                    key, self.name))

class Parameter:
    def __init__(self, name, value):
        self.name  = name
        self.value = value

class Port:
    def __init__(self, name, value):
        self.name = name
        self.value = value


class AHB3Intercon:
    def __init__(self, name, config_file):
        self.verilog_writer = VerilogWriter(name)
        self.template_writer = VerilogWriter(name);
        self.name = name
        d = OrderedDict()
        self.slaves = OrderedDict()
        self.masters = OrderedDict()
        import yaml

        def ordered_load(stream, Loader=yaml.Loader, object_pairs_hook=OrderedDict):
            class OrderedLoader(Loader):
                pass
            def construct_mapping(loader, node):
                loader.flatten_mapping(node)
                return object_pairs_hook(loader.construct_pairs(node))
            OrderedLoader.add_constructor(
                yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
                construct_mapping)
            return yaml.load(stream, OrderedLoader)
        data = ordered_load(open(config_file))

        config     = data['parameters']
        files_root = data['files_root']
        self.vlnv       = data['vlnv']

        index = 0
        for k,v in config['masters'].items():
            print("Found master " + k)
            self.masters[k] = Master(k,index,v)
            index = index + 1
        index = 0
        for k,v in config['slaves'].items():
            print("Found slave " + k)
            self.slaves[k] = Slave(k,index,v)
            index = index + 1

        #Create master/slave connections
        for master, slaves in d.items():
            for slave in slaves:
                self.masters[master].slaves += [self.slaves[slave]]
                self.slaves[slave].masters += [self.masters[master]]

        self.output_file = config.get('output_file', 'ahb3lite_intercon.v')

    def _dump(self):
        print("*Masters*")
        for master in self.masters.values():
            print(master.name)
            for slave in master.slaves:
                print(' ' + slave.name)

        print("*Slaves*")
        for slave in self.slaves.values():
            print(slave.name)
            for master in slave.masters:
                print(' ' + master.name)

    def write(self):
        file = self.output_file

        # Template port/parameters
        template_ports = [Port('clk', 'CLK'),
                          Port('reset_n', 'RESET_N')]
        template_parameters = []


        # Gen top level ports
        self.verilog_writer.add(ModulePort('clk', 'input'))
        self.verilog_writer.add(ModulePort('reset_n', 'input'))

        # Declare global wires to pass to instantiation
        self.verilog_writer.add (LocalParam ('localparam MASTERS', len (self.masters)))
        self.verilog_writer.add (LocalParam ('localparam SLAVES', len (self.slaves)))
        self.verilog_writer.add (Wire ('mst_PRIORITY', math.ceil(math.log2(len (self.masters))), append=' [MASTERS]'))
        self.verilog_writer.add (Wire ('slv_ADDR_BASE', 32, append=' [SLAVES]'))
        self.verilog_writer.add (Wire ('slv_ADDR_MASK', 32, append=' [SLAVES]'))
        for p in AHB3_MASTER_PORTS:
          self.verilog_writer.add (Wire ('mst_{0}'.format (p.name), p.width, append=' [MASTERS]'))
          self.verilog_writer.add (Wire ('slv_{0}'.format (p.name), p.width, append=' [SLAVES]'))
        for p in AHB3_SLAVE_PORTS:
          self.verilog_writer.add (Wire ('mst_{0}'.format (p.name), p.width, append=' [MASTERS]'))
          self.verilog_writer.add (Wire ('slv_{0}'.format (p.name), p.width, append=' [SLAVES]'))

        # Generate master wires
        for key, value in self.masters.items():
          for p in AHB3_MASTER_PORTS:
            self.verilog_writer.add (Wire ('{0}_{1}'.format (key, p.name), p.width))
            self.template_writer.add (Wire ('{0}_{1}'.format (key, p.name), p.width))
            self.verilog_writer.add(ModulePort('{0}_{1}'.format (key, p.name), 'input', p.width))
            template_ports += [Port ('{0}_{1}'.format (key, p.name), '{0}_{1}'.format (key, p.name))]
          for p in AHB3_SLAVE_PORTS:
            self.verilog_writer.add (Wire ('{0}_{1}'.format (key, p.name), p.width))
            self.template_writer.add (Wire ('{0}_{1}'.format (key, p.name), p.width))
            self.verilog_writer.add(ModulePort('{0}_{1}'.format (key, p.name), 'output', p.width))
            template_ports += [Port ('{0}_{1}'.format (key, p.name), '{0}_{1}'.format (key, p.name))]

        # Generate slave wires
        for key, value in self.slaves.items():
          for p in AHB3_MASTER_PORTS:
            self.verilog_writer.add (Wire ('{0}_{1}'.format (key, p.name), p.width))
            self.template_writer.add (Wire ('{0}_{1}'.format (key, p.name), p.width))
            self.verilog_writer.add(ModulePort('{0}_{1}'.format (key, p.name), 'output', p.width))
            template_ports += [Port ('{0}_{1}'.format (key, p.name), '{0}_{1}'.format (key, p.name))]
          for p in AHB3_SLAVE_PORTS:
            self.verilog_writer.add (Wire ('{0}_{1}'.format (key, p.name), p.width))
            self.template_writer.add (Wire ('{0}_{1}'.format (key, p.name), p.width))
            self.verilog_writer.add(ModulePort('{0}_{1}'.format (key, p.name), 'input', p.width))
            template_ports += [Port ('{0}_{1}'.format (key, p.name), '{0}_{1}'.format (key, p.name))]

        # Generate master assignments
        for key, val in self.masters.items():
          self.verilog_writer.add (Assign ('mst_{0} [{1}]'.format ('PRIORITY', val.index), val.priority))
          for p in AHB3_MASTER_PORTS:
            if p.name == 'HREADY':
              self.verilog_writer.add (Assign ('mst_{0} [{1}]'.format (p.name, val.index), 'mst_HREADYOUT[{0}]'.format (val.index)))
            else:
              self.verilog_writer.add (Assign ('mst_{0} [{1}]'.format (p.name, val.index), '{0}_{1}'.format (key, p.name)))
          for p in AHB3_SLAVE_PORTS:
            if p.name == 'HREADYOUT':
              self.verilog_writer.add (Assign ('{0}_{1}'.format (key, p.name[:-3]), 'mst_{0} [{1}]'.format (p.name, val.index)))
            else:
              self.verilog_writer.add (Assign ('{0}_{1}'.format (key, p.name), 'mst_{0} [{1}]'.format (p.name, val.index)))

        # Generate slave assignments
        for key, val in self.slaves.items():
          self.verilog_writer.add (Assign ('slv_addr_base [{0}]'.format (val.index), val.offset))
          self.verilog_writer.add (Assign ('slv_addr_mask [{0}]'.format (val.index), ~(val.size - 1)))
          for p in AHB3_MASTER_PORTS:
            if p.name == 'HREADY':
              self.verilog_writer.add (Assign ('{0}_{1}'.format (key, p.name), 'slv_HREADYOUT [{0}]'.format (val.index)))
            else:
              self.verilog_writer.add (Assign ('{0}_{1}'.format (key, p.name), 'slv_{0} [{1}]'.format (p.name, val.index)))
          for p in AHB3_SLAVE_PORTS:
            if p.name == 'HREADYOUT':
              self.verilog_writer.add (Assign ('slv_HREADY [{0}]'.format (val.index), '{0}_{1}'.format (key, p.name)))
            else:              
              self.verilog_writer.add (Assign ('slv_{0} [{1}]'.format (p.name, val.index), '{0}_{1}'.format (key, p.name)))

        # Instantiate interconnect
        inter_param = [Parameter ('MASTERS', len (self.masters)),
                       Parameter ('SLAVES', len (self.slaves)),
                       Parameter ('HADDR_SIZE', 32),
                       Parameter ('HDATA_SIZE', 32)]
        inter_ports = [Port ('HCLK', 'clk'),
                       Port ('HRESETn', 'reset_n'),
                       Port ('mst_priority', 'mst_priority'),
                       Port ('slv_addr_base', 'slv_addr_base'),
                       Port ('slv_addr_mask', 'slv_addr_mask')]
        inter_ports += [Port ('mst_'+p.name, 'mst_'+p.name) for p in AHB3_MASTER_PORTS]
        inter_ports += [Port ('slv_'+p.name, 'slv_'+p.name) for p in AHB3_MASTER_PORTS]
        inter_ports += [Port ('mst_'+p.name, 'mst_'+p.name) for p in AHB3_SLAVE_PORTS]
        inter_ports += [Port ('slv_'+p.name, 'slv_'+p.name) for p in AHB3_SLAVE_PORTS]
        self.verilog_writer.add (Instance ('ahb3lite_interconnect', 'ahb3lite_intercon0', inter_param, inter_ports))

        # Create template
        self.template_writer.add(Instance(self.name, self.name+'0',
                                          template_parameters, template_ports))

        self.verilog_writer.write(file)
        self.template_writer.write(file+'h')

        core_file = self.vlnv.split(':')[2]+'.core'
        vlnv = self.vlnv
        with open(core_file, 'w') as f:
            f.write('CAPI=2:\n')
            files = [{file     : {'file_type' : 'verilogSource'}},
                     {file+'h' : {'is_include_file' : True,
                                  'file_type' : 'verilogSource'}}
            ]
            coredata = {'name' : vlnv,
                        'targets' : {'default' : {}},
            }

            coredata['filesets'] = {'rtl' : {'files' : files}}
            coredata['targets']['default']['filesets'] = ['rtl']

            f.write(yaml.dump(coredata))

if __name__ == "__main__":
    #if len(sys.argv) < 3 or len(sys.argv) > 4:
        #print("ahb3_intercon_gen <config_file> <out_file> [module_name]")
        #exit(0)
    name = "ahb3lite_intercon"
    if len(sys.argv) == 4:
      name = sys.argv[3]
    try:
      g = AHB3Intercon(name, sys.argv[1])
      if len(sys.argv) > 2:
          g.output_file = sys.argv[2]
      print("="*80)
      g.write()
    except Error as e:
      print("Error: %s" % e)
      exit(1)
