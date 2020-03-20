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
import math
import time

channel_bandwidth = 400e6 / 512.0
beam_start_frequency = 156.25e6
beam_start_channel = int(beam_start_frequency / channel_bandwidth)
beam_bandwidth = 6.25e6
nof_channels = int(beam_bandwidth / channel_bandwidth)
nof_samples = 524288


temp_dir = "./temp_daq_test"
data = []
data_received = False
tile_id = 0

def data_callback(mode, filepath, tile):
    # Note that this will be called asynchronosuly from the C code when a new file is generated
    # If you want to control the flow of the main program as data comes in, then you need to synchronise
    # with a global variable. In this example, there will be an infinite loop between sending data and receiving data
    global data_received
    global data

    # If you want to perform some checks in the data here, you will need to use the persisters scrips to read the
    # data. Note that the persister will read the latest file if no specific timestamp is provided
    # filename will contain the full path

    if mode == "burst_beam":
        beam_file = BeamFormatFileManager(root_path=os.path.dirname(filepath))
        data, timestamps = beam_file.read_data(channels=range(nof_channels),  # List of channels to read (not use in raw case)
                                               polarizations=[0, 1],
                                               n_samples=32,
                                               tile_id=tile_id)
        print("Beam data: {}".format(data.shape))

    data_received = True



def remove_files():
    # create temp directory
    if not os.path.exists(temp_dir):
        print("Creating temp folder: " + temp_dir)
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
    parser.add_option("-f", "--first", action="store", dest="first_channel",
                      default="64", help="First frequency channel [default: 64]")
    parser.add_option("-l", "--last", action="store", dest="last_channel",
                      default="383", help="Last frequency channel [default: 383]")
    parser.add_option("-i", "--receiver_interface", action="store", dest="receiver_interface",
                      default="eth0", help="Receiver interface [default: eth0]")
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

    tile_id = tile['fpga1.dsp_regfile.config_id.tpm_id']

    # Initialise DAQ. For now, this needs a configuration file with ALL the below configured
    # I'll change this to make it nicer
    daq_config = {
                  'receiver_interface': conf.receiver_interface,  # CHANGE THIS if required
                  'directory': temp_dir,  # CHANGE THIS if required
             #     'nof_beam_channels': nof_channels,
             #     'nof_beam_samples': 64,
             #     'receiver_frame_size': 9000
                  }

    print(daq_config)

    # Configure the DAQ receiver and start receiving data
    daq.populate_configuration(daq_config)
    daq.initialise_daq()

    # Start whichever consumer is required and provide callback
    #daq.start_raw_data_consumer(callback=data_callback)  # Change start_xxxx_data_consumer with data mode required
    #daq.start_channel_data_consumer(callback=data_callback)  # Change start_xxxx_data_consumer with data mode required
    daq.start_beam_data_consumer(callback=data_callback)  # Change start_xxxx_data_consumer with data mode required
    #
    # beam data
    #
    tf.stop_pattern(tile, "all")
    tile['fpga1.jesd204_if.regfile_channel_disable'] = 0xFFFF
    tile['fpga2.jesd204_if.regfile_channel_disable'] = 0xFFFF
    tile.test_generator_disable_tone(0)
    tile.test_generator_disable_tone(1)
    tile.test_generator_set_noise(0.0)
    tile.test_generator_input_select(0xFFFFFFFF)

    tile.set_channeliser_truncation(5)

    remove_files()

    channels = range(int(conf.first_channel), int(conf.last_channel) + 1)
    single_input_data = np.zeros((2, 16), dtype='complex')
    coeff = np.zeros((2, 16), dtype='complex')
    tf.stop_pattern(tile, "all")

    for c in channels:
        frequency = c * 400e6 / 512.0
        tile.test_generator_set_tone(0, frequency, 1.0)
        tf.set_delay(tile, [random.randrange(0, 32, 1) for x in range(32)])
        ref_antenna = random.randrange(0, 16, 1)
        ref_pol = random.randrange(0, 2, 1)
        tf.reset_beamf_coeff(tile, gain=1.0)
        time.sleep(0.1)

        inputs = 0x3
        for i in range(16):

            tile.test_generator_input_select(inputs)

            # Set data received to False
            data_received = False
            # Send data from tile

            tile.send_beam_data()

            # Wait for data to be received
            while not data_received:
                time.sleep(0.1)

            # print data[0, :, 0, 0]

            single_input_data[0][i] = tf.get_beam_value(data, 0, c-beam_start_channel)
            single_input_data[1][i] = tf.get_beam_value(data, 1, c-beam_start_channel)

            inputs = (inputs << 2)
            print(single_input_data)

        ref_value = single_input_data[ref_pol][ref_antenna]

        for p in range(2):
            for n in range(16):
                coeff[p][n] = ref_value / single_input_data[p][n]

        print(coeff)

        tf.set_beamf_coeff(tile, coeff, c)

        inputs = 0x3
        for i in range(16):

            tile.test_generator_input_select(inputs)

            # Set data received to False
            data_received = False
            # Send data from tile
            tile.send_beam_data()

            # Wait for data to be received
            while not data_received:
                time.sleep(0.1)

            single_input_data[0][i] = tf.get_beam_value(data, 0, c-beam_start_channel)
            single_input_data[1][i] = tf.get_beam_value(data, 1, c-beam_start_channel)

            inputs = (inputs << 2)

        for p in range(2):
            for a in range(16):
                exp_val = ref_value
                rcv_val = single_input_data[p][a]
                if abs(exp_val.real-rcv_val.real) > 1 or abs(exp_val.imag-rcv_val.imag) > 1:
                    print("Error:")
                    print(single_input_data)
                    print(ref_value)
                    _ = input("Press Enter")

        inputs = 0xFFFFFFFF
        tile.test_generator_input_select(inputs)
        # Set data received to False
        data_received = False
        # Send data from tile
        tile.send_beam_data()

        # Wait for data to be received
        while not data_received:
            time.sleep(0.1)

        for p in range(2):
            beam_val = tf.get_beam_value(data, p, c-beam_start_channel)
            single_val = ref_value

            if abs(beam_val.real/16-single_val.real) > 1 or abs(beam_val.imag/16-single_val.imag) > 1:
                print("Beam sum error:")
                print(single_input_data)
                print(tf.get_beam_value(data, p, c-beam_start_channel))
                print(ref_value)
                _ = input("Press Enter")

        print("CHANNEL " + str(c) + " OK!")

    daq.stop_daq()
