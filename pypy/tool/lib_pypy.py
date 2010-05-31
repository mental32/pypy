import py
import pypy
from pypy.module.sys.version import PYPY_VERSION

def get_lib_pypy_dir():
    prefix = py.path.local(pypy.__path__[0]).dirpath()
    pypy_ver = 'pypy%d.%d' % PYPY_VERSION[:2]
    return prefix.join('lib', pypy_ver, 'lib_pypy')

def import_from_lib_pypy(modname):
    dirname = get_lib_pypy_dir()
    modname = dirname.join(modname+'.py')
    return modname.pyimport()
