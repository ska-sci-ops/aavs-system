from setuptools import setup

setup(
    name='aavs-system',
    version='1.0',
    packages=['pydaq', 'pydaq.persisters', 'pydaq.plotters', 'pyaavs', 'aavs_calibration'],
    url='https://bitbucket.org/aavslmc/aavs-system',
    license='',
    author='Alessio Magro',
    author_email='alessio.magro@um.edu.mt',
    description='AAVS Software',
    install_requires=['h5py', 'pyyaml', 'lockfile', 'scapy', 'numpy==1.16.6', 'gitpython',
                      'future', 'astropy==2.0.16', 'matplotlib==2.2.5', 'scipy==1.2.3',
                      'mongoengine', 'pytz', 'pymongo']
)
