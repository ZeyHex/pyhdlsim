"""HDL simulation utilities.
All simulator executables must be visible in PATH.
"""
import subprocess
import argparse
from pathlib import Path

def file_ext(filepath):
    """Get file extension from filepath"""
    return Path(filepath).suffix


def parent_dir(filepath):
    """Get parent directory path from filepath"""
    return Path(filepath).resolve().parent


def make_dir(name):
    """Make directory with specified name"""
    return Path(name).mkdir()


def path_join(*other):
    """Add each of other argumetns to path in turn"""
    return Path().joinpath(*other)


def remove_tree(dirpath):
    """Remove an entire directory tree if it exists"""
    p = Path(dirpath)
    if p.exists() and p.is_dir():
        for child in p.glob('*'):
            if child.is_file():
                child.unlink()
            else:
                remove_tree(child)
        p.rmdir()


def get_define(name, defines):
    """Return define value from defines list"""
    try:
        return next(d for d in defines if name in d).split('=')[-1]
    except StopIteration:
        return None

def get_param(name, params):
    """Return define value from defines list"""
    try:
        return next(d for d in params if name in d).split('=')[-1]
    except StopIteration:
        return None

def write_memfile(path, data):
    """Write data to memory file (can be loaded with $readmemh)"""
    with Path(path).open(mode='w', encoding="utf-8") as memfile:
        memfile.writelines(['%x\n' % d for d in data])

class Simulator:
    """Simulator wrapper"""
    def __init__(self, name='icarus', gui=False, cwd='work'):
        self.gui = gui

        self.cwd = Path(cwd).resolve()
        if parent_dir(__file__) == self.cwd:
            raise ValueError("Wrong working directory '%s'" % self.cwd)

        self.name = name
        self._runners = {'icarus': self._run_icarus,
                         'modelsim': self._run_modelsim,
                         'vivado': self._run_vivado}
        if self.name not in self._runners.keys():
            raise ValueError("Unknown simulator tool '%s'" % self.name)

        self.worklib = 'worklib'
        self.top = 'top'
        self.sources = []
        self.defines = []
        self.params  = []
        self.incdirs = []

        self.stdout = ''
        self.retcode = 0

        self.sim_errors = ['$error : ', 'Error: ', 'ERROR: ', 'Assertion error']

        """Prepare working directory"""
        remove_tree(self.cwd)
        make_dir(self.cwd)

    #def setup(self):
    #    """Prepare working directory"""
    #    remove_tree(self.cwd)
    #    make_dir(self.cwd)

    def run(self):
        """Run selected simulator"""
        # some preprocessing
        self.sources = [str(Path(filepath).resolve()).replace('\\','/') for filepath in self.sources]
        self.incdirs = [str(Path(dirpath).resolve()).replace('\\','/') for dirpath in self.incdirs]
        self.defines += ['TOP_NAME=%s' % self.top, 'SIM']
        self.params += []
        # run simulation
        self._runners[self.name]()

    def get_define(self, name):
        """Return define value from defines list"""
        return get_define(name, self.defines)
    
    def get_param(self, name):
        return get_param(name, self.params)

    def _exec(self, prog, args):
        """Execute external program.
        Args:
            prog : string with program name
            args : string with program arguments
        """
        exec_str = prog + " " + args
        print(exec_str)
        if self.name == 'vivado':
            exec_str = exec_str
        else:
            exec_str = exec_str.split()
        child = subprocess.Popen(exec_str, cwd=self.cwd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        """Reading shell output """
        while True:
            output = child.stdout.readline().decode('utf-8').strip()

            if output == '' and child.poll() is not None:
                break
            
            """Check shell output for errors """
            for err in self.sim_errors:
                if err in output:
                    child.kill()
                    output = output.replace(err,'')
                    raise AssertionError(output, self.defines)
            
            if output:
                print(output)
        
        """Check return code"""
        self.retcode = child.returncode
        if self.retcode:
            raise RuntimeError("Execution failed at '%s' with return code %d!" % (exec_str, self.retcode))

    def _run_icarus(self):
        """Run Icarus + GTKWave"""
        print('Run Icarus (cwd=%s)' % self.cwd)
        print(' '.join([d for d in self.defines]))
        # elaborate
        elab_args = ''
        elab_args += ' '.join(['-I %s' % incdir for incdir in self.incdirs]) + ' '
        elab_args += ' '.join(['-D %s' % define for define in self.defines]) + ' '
        elab_args += '-g2005-sv -s %s -o %s.vvp' % (self.top, self.worklib) + ' '
        elab_args += ' '.join(self.sources)
        self._exec('iverilog', elab_args)
        # simulate
        self._exec('vvp', '%s.vvp -lxt2' % self.worklib)
        # show waveforms
        if self.gui:
            self._exec('gtkwave', 'dump.vcd')

    def _run_modelsim(self):
        """Run Modelsim"""
        print('Run Modelsim (cwd=%s)' % self.cwd)
        print(' '.join([d for d in self.defines]))
        # prepare compile script
        defines = ' '.join(['+define+' + define for define in self.defines])
        incdirs = ' '.join(['+incdir+' + incdir for incdir in self.incdirs])
        params  = ''.join(['-G ' + param + ' ' for param in self.params])
        sources = ''
        for src in self.sources:
            ext = file_ext(src)
            if ext in ['.v', '.sv']:
                sources += 'vlog -nologo -suppress 2902 %s %s -sv -timescale \"1 ns / 1 ps\" %s\n' % (defines, incdirs, src)
            elif ext == 'vhd':
                sources += 'vcom -93 %s\n' % src
        if not self.gui:
            run = 'run -all'
        else:
            run = ''
        compile_tcl = """
            proc rr  {{}} {{
              write format wave -window .main_pane.wave.interior.cs.body.pw.wf wave.do
              uplevel #0 source compile.tcl
            }}
            proc q  {{}} {{quit -force}}
            vlib {worklib}
            vmap work {worklib}
            {sources}
            eval vsim {worklib}.{top} {params}
            if [file exist wave.do] {{
              source wave.do
            }}
            {run}
            """
    
        with path_join(self.cwd, 'compile.tcl').open(mode='w', encoding="utf-8") as f:
            f.write(compile_tcl.format(worklib=self.worklib,
                                       top=self.top,
                                       incdirs=incdirs,
                                       sources=sources,
                                       defines=defines,
                                       params=params,
                                       run=run))
        vsim_args = '-do compile.tcl'
        if not self.gui:
            vsim_args += ' -c -64 '
            vsim_args += ' -onfinish exit'
        else:
            vsim_args += ' -onfinish stop'
        self._exec('vsim', vsim_args)


    def _run_vivado(self):
        """Run Vivado simulator"""
        print('Run Vivado (cwd=%s)' % self.cwd)
        print(' '.join([d for d in self.defines]))
        print(' '.join([d for d in self.params]))
        # prepare and run elaboration
        elab_args = "-a --prj files.prj %s -R -nolog -timescale \"1 ns / 1 ps\" " % self.top
        elab_args += ' '.join(['-d ' + '"' + define + '"' for define in self.defines]) + ' '
        elab_args += ' '.join(['--generic_top ' + '"' + param + '"' for param in self.params]) + ' '
        elab_args += ' '.join(['-i ' + incdir for incdir in self.incdirs])+ ' '
        sources = ''
        for src in self.sources:
            ext = file_ext(src)
            if ext == '.sv':
                sources += 'sv work %s\n' % src
            elif ext == '.v':
                sources += 'verilog work %s\n' % src
            elif ext == 'vhd':
                sources += 'vhdl work %s\n' % src
        with path_join(self.cwd, 'files.prj').open(mode='w', encoding="utf-8") as f:
            f.write(sources)

        self._exec('xelab', elab_args)
        


class CliArgs:
    """Parse command line parameters for simulation"""
    def __init__(self, default_test='test', default_simtool='vivado', default_gui=False, default_defines=[], default_params=[]):
        self._args_parser = argparse.ArgumentParser()
        self._args_parser.add_argument('-t',
                                       default=default_test,
                                       metavar='<name>',
                                       dest='test',
                                       help="test <name>; default is '%s'" % default_test)
        self._args_parser.add_argument('-s',
                                       default=default_simtool,
                                       metavar='<name>',
                                       dest='simtool',
                                       help="simulation tool <name>; default is '%s'" % default_simtool)
        self._args_parser.add_argument('-b',
                                       default=default_gui,
                                       dest='gui',
                                       action='store_false',
                                       help='enable batch mode (no GUI)')
        self._args_parser.add_argument('-d',
                                       default=default_defines,
                                       metavar='<def>',
                                       dest='defines',
                                       nargs='+',
                                       help="define <name>; option can be used multiple times")
        self._args_parser.add_argument('-g',
                                       default=default_params,
                                       metavar='<par>',
                                       dest='params',
                                       nargs='+',
                                       help="parameter <name>; option can be used multiple times")
        
    def parse(self):
        return self._args_parser.parse_args()
