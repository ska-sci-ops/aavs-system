from builtins import str
import os
import re
import subprocess
import multiprocessing
from distutils.version import LooseVersion

from setuptools import setup, Extension
from setuptools.command.build_ext import build_ext

# Check if install directory is specified


install_dir = "/usr/local"
source_dir = os.path.join(os.getcwd(), "../src")


class CMakeExtension(Extension):
    def __init__(self, name, sourcedir=''):
        Extension.__init__(self, name, sources=[])
        self.sourcedir = os.path.abspath(sourcedir)


class CMakeBuild(build_ext):
    def run(self):
        try:
            out = subprocess.check_output(['cmake', '--version'])
        except OSError:
            raise RuntimeError("CMake must be installed to build the following extensions: " +
                               ", ".join(e.name for e in self.extensions))

        cmake_version = LooseVersion(re.search(r'version\s*([\d.]+)', out.decode()).group(1))
        if cmake_version < LooseVersion('3.1.0'):
            raise RuntimeError("CMake >= 3.1.0 is required on Windows")

        for ext in self.extensions:
            self.build_extension(ext)

    def build_extension(self, ext):
        cmake_args = ['-DCMAKE_INSTALL_PREFIX={}'.format(install_dir), '-DCMAKE_BUILD_TYPE=Release']
        build_args = ['--', '-j', str(multiprocessing.cpu_count())]

        if not os.path.exists(self.build_temp):
            os.makedirs(self.build_temp)

        subprocess.check_call(['cmake', source_dir] + cmake_args, cwd=self.build_temp, env=os.environ)
        subprocess.check_call(['cmake', '--build', '.', '--target', 'install'] + build_args, cwd=self.build_temp)


setup(
    name='pydaq',
    version='0.5',
    packages=['pydaq', 'pydaq.persisters', 'pydaq.plotters'],
    url='https://bitbucket.org/aavslmc/aavs-daq',
    license='',
    author='Alessio Magro',
    author_email='alessio.magro@um.edu.mt',
    description='DAQ for AAVS',
#    ext_modules=[CMakeExtension(install_dir)],
#    cmdclass=dict(build_ext=CMakeBuild),
    install_requires=['h5py', 'lockfile', 'matplotlib', 'zope.event', 'mongoengine', 'pytz', 'pymongo', 'watchdog']
)
