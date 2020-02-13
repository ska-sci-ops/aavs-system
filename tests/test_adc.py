# Import DAQ and Access Layer libraries
import pydaq.daq_receiver as daq
from pyaavs.tile import Tile

# Import required persisters
from pydaq.persisters.aavs_file import FileModes
from pydaq.persisters.raw import RawFormatFileManager
from pydaq.persisters.channel import ChannelFormatFileManager
from pydaq.persisters.beam import BeamFormatFileManager
from pydaq.persisters import *

from sys import stdout
import test_functions as tf
import numpy as np
import os.path
import logging
import random
import time

temp_dir = "./temp_daq_test"
data_received = False
data = []
pattern_type = ""
fixed_pattern = [[191, 254, 16, 17]] * 16


def check_adc_pattern(pattern_type, fixed_pattern):

    global data

    print "Checking " + pattern_type + " ADC pattern"
    if pattern_type == "fixed":
        print "Pattern data: "
        for n in range(16):
            print fixed_pattern[n]

    for a in range(16):
        for p in range(2):
            buffer = np.array(data[a, p, 0:32768], dtype='uint8')
            if pattern_type == "ramp":
                seed = buffer[0]
                for n in range(len(buffer)):
                    exp_value = (seed + n) % 256
                    if buffer[n] != exp_value:
                        print "Error detected, ramp pattern"
                        print "Buffer position: " + str(n)
                        print "Expected value: " + str(exp_value)
                        print "Received value: " + str(buffer[n])
                        print buffer[0:128]
                        raw_input()
            if pattern_type == "fixed":
                for n in range(4):
                    seed = n
                    for m in range(4):
                        if buffer[m] != fixed_pattern[a][(m + n) % 4]:
                            seed = -1
                    if seed >= 0:
                        break
                for n in range(0, len(buffer)):
                    exp_value = fixed_pattern[a][(seed + n) % 4]
                    if buffer[n] != exp_value:
                        print "Error detected, fixed pattern"
                        print fixed_pattern[a]
                        print "Buffer position: " + str(n)
                        print "Expected value: " + str(fixed_pattern[a][(n + m) % 4])
                        print "Received value: " + str(buffer[n])
                        print buffer[0:128]
                        raw_input()

    print "Data pattern checked!\n"

def data_callback(mode, filepath, tile):
    # Note that this will be called asynchronosuly from the C code when a new file is generated
    # If you want to control the flow of the main program as data comes in, then you need to synchronise
    # with a global variable. In this example, there will be an infinite loop between sending data and receiving data
    global data_received
    global data

    # If you want to perform some checks in the data here, you will need to use the persisters scrips to read the
    # data. Note that the persister will read the latest file if no specific timestamp is provided
    # filename will contain the full path

    if mode == "burst_raw":
        raw_file = RawFormatFileManager(root_path=os.path.dirname(filepath))
        data, timestamps = raw_file.read_data(antennas=range(16),  # List of channels to read (not use in raw case)
                                           polarizations=[0, 1],
                                           n_samples=32*1024)
        print "Raw data: {}".format(data.shape)

    data_received = True


def remove_files():
    # create temp directory
    if not os.path.exists(temp_dir):
        print "Creating temp folder: " + temp_dir
        os.system("mkdir " + temp_dir)
    os.system("rm " + temp_dir + "/*.hdf5")

if __name__ == "__main__":

    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %station [options]")
    parser.add_option("--port", action="store", dest="port",
                      type="int", default="10000", help="Port [default: 10000]")
    parser.add_option("--tpm_ip", action="store", dest="tpm_ip",
                      default="10.0.10.3", help="IP [default: 10.0.10.3]")
    parser.add_option("-i", "--iteration", action="store", dest="iteration",
                      default="16", help="Number of iterations [default: 16, infinite: -1]")
    (conf, args) = parser.parse_args(argv[1:])

    # Set logging
    log = logging.getLogger('')
    log.setLevel(logging.INFO)
    str_format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    ch = logging.StreamHandler(stdout)
    ch.setFormatter(str_format)
    log.addHandler(ch)
    remove_files()

    # Connect to tile (and do whatever is required)
    tile = Tile(ip=conf.tpm_ip, port=conf.port)
    tile.connect()

    tf.stop_pattern(tile, "all")
    tile['fpga1.jesd204_if.regfile_channel_disable'] = 0x0
    tile['fpga2.jesd204_if.regfile_channel_disable'] = 0x0
    tile.test_generator_disable_tone(0)
    tile.test_generator_disable_tone(1)
    tile.test_generator_set_noise(0.0)
    tile.test_generator_input_select(0x00000000)

    time.sleep(0.2)

    iter = int(conf.iteration)
    if iter == 0:
        exit()

    # Initialise DAQ. For now, this needs a configuration file with ALL the below configured
    # I'll change this to make it nicer
    daq_config = {
                  'receiver_interface': 'eth3',  # CHANGE THIS if required
                  'directory': temp_dir,  # CHANGE THIS if required
                  'nof_beam_channels': 384,
                  'nof_beam_samples': 32,
                  'receiver_frame_size': 9000
                  }

    # Configure the DAQ receiver and start receiving data
    daq.populate_configuration(daq_config)
    daq.initialise_daq()

    # Start whichever consumer is required and provide callback
    daq.start_raw_data_consumer(callback=data_callback)  # Change start_xxxx_data_consumer with data mode required
    #
    # raw data synchronised
    #
    remove_files()

    print "Setting 0 delays..."
    delays = [0] * 32
    tf.set_delay(tile, delays)

    while iter > 0 or iter == -1:
        pattern_type = "ramp"
        tf.enable_adc_test_pattern(tile, range(16), pattern_type)
        time.sleep(0.2)

        data_received = False
        # Send data from tile
        tile.send_raw_data()
        # Wait for data to be received
        while not data_received:
            time.sleep(0.1)

        check_adc_pattern(pattern_type, fixed_pattern)

        for n in range(16):
            fixed_pattern[n] = [random.randrange(0, 255, 1) for x in range(4)]
        pattern_type = "fixed"
        tf.enable_adc_test_pattern(tile, range(16), pattern_type, fixed_pattern)
        time.sleep(0.2)

        data_received = False
        # Send data from tile
        tile.send_raw_data()
        # Wait for data to be received
        while not data_received:
            time.sleep(0.1)

        check_adc_pattern(pattern_type, fixed_pattern)

        iter -= 1

    daq.stop_daq()
