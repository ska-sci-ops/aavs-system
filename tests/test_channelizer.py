from __future__ import print_function
from __future__ import absolute_import
from __future__ import division

# Import DAQ and Access Layer libraries
from builtins import input
from builtins import str
from builtins import range
from past.utils import old_div
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

temp_dir = "./temp_daq_test"
data = []
data_received = False


def data_callback(mode, filepath, tile):
    # Note that this will be called asynchronosuly from the C code when a new file is generated
    # If you want to control the flow of the main program as data comes in, then you need to synchronise
    # with a global variable. In this example, there will be an infinite loop between sending data and receiving data
    global data_received
    global data

    # If you want to perform some checks in the data here, you will need to use the persisters scrips to read the
    # data. Note that the persister will read the latest file if no specific timestamp is provided
    # filename will contain the full path

    if mode == "burst_channel":
        channel_file = ChannelFormatFileManager(root_path=os.path.dirname(filepath))
        data, timestamps = channel_file.read_data(channels=list(range(512)),  # List of channels to read (not use in raw case)
                                               antennas=list(range(16)),
                                               polarizations=[0, 1],
                                               n_samples=128)
        print("Channel data: {}".format(data.shape))

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
    parser.add_option("-p", "--points", action="store", dest="points",
                      default="1", help="Frequency points per channel [default: 1]")
    parser.add_option("-f", "--first", action="store", dest="first_channel",
                      default="64", help="First frequency channel [default: 64]")
    parser.add_option("-l", "--last", action="store", dest="last_channel",
                      default="447", help="Last frequency channel [default: 383]")
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
    # daq.start_raw_data_consumer(callback=data_callback)  # Change start_xxxx_data_consumer with data mode required
    daq.start_channel_data_consumer(callback=data_callback)  # Change start_xxxx_data_consumer with data mode required
    # daq.start_beam_data_consumer(callback=data_callback)  # Change start_xxxx_data_consumer with data mode required
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

    tile.set_channeliser_truncation(4)

    points_per_channel = int(conf.points)
    channels = list(range(int(conf.first_channel), int(conf.last_channel) + 1))
    channel_width = 400e6 / 512.0

    for channel in channels:
        for point in range(points_per_channel):
            frequency = channel * channel_width - old_div(channel_width, 2) + old_div(channel_width, (points_per_channel + 1)) * (point + 1)
            tile.test_generator_set_tone(0, frequency, 1.0)
            delays = [0] + [random.randrange(0, 4, 1) for x in range(31)]
            tf.set_delay(tile, delays)
            print("setting frequency: " + str(frequency) + " Hz, point " + str(point))
            time.sleep(1)

            remove_files()
            data_received = False
            tile.send_channelised_data(256)

            while not data_received:
                time.sleep(0.1)

            ch, ant, pol, sam = data.shape
            for i in range(16):  # range(sam):
                ref_channel_value = data[channel, 0, 0, i][0] + data[channel, 0, 0, i][1]*1j
                if abs(ref_channel_value) > 0:
                    ref_power_value = 20*np.log10(abs(ref_channel_value))
                else:
                    ref_power_value = 0
                ref_phase_value = np.angle(ref_channel_value, deg=True)
                for a in range(ant):
                    for c in range(2, ch):
                        for p in range(pol):
                            channel_value = data[c, a, p, i][0] + data[c, a, p, i][1]*1j
                            if abs(channel_value):
                                power_value = 20*np.log10(abs(channel_value))
                            else:
                                power_value = 0
                            phase_value = np.angle(channel_value, deg=True)
                            if c != channel:
                                if ref_power_value - power_value < 30 and power_value > 0:
                                    print(data[:, a, p, i])
                                    print("Test channel " + str(channel))
                                    print("Excessive power in channel " + str(c))
                                    print("Frequency: " + str(frequency))
                                    print("Antenna: " + str(a))
                                    print("Polarization: " + str(p))
                                    print("Sample index: " + str(i))
                                    print("Reference value: " + str(ref_channel_value))
                                    print("Reference power " + str(ref_power_value))
                                    print("Channel value " + str(channel_value))
                                    print("Channel power " + str(power_value))
                                    input("Press a key")
                            else:
                                if ref_power_value - power_value > 1 or ref_power_value < 35:
                                    print(data[:, a, p, i])
                                    print("Test channel " + str(channel))
                                    print("Low power in channel " + str(c))
                                    print("Frequency: " + str(frequency))
                                    print("Antenna: " + str(a))
                                    print("Polarization: " + str(p))
                                    print("Sample index: " + str(i))
                                    print("Reference value: " + str(ref_channel_value))
                                    print("Reference power " + str(ref_power_value))
                                    print("Channel value " + str(channel_value))
                                    print("Channel power " + str(power_value))
                                    input("Press a key")

                            if c == channel:
                                #if phase_value < 0:
                                ref_phase_value_360 = ref_phase_value % 360
                                phase_value_360 = phase_value % 360
                                applied_delay = delays[2*a+p] * 1.25e-9
                                phase_delay = np.modf(old_div(applied_delay, (1.0 / frequency)))[0]
                                expected_phase_delay = phase_delay*360
                                expected_phase = (ref_phase_value_360 + expected_phase_delay) % 360
                                diff = abs(expected_phase - phase_value_360) % 360
                                if diff > 3 and 360-diff > 3:
                                    print(data[:, a, p, i])
                                    print(diff)
                                    print("Test channel " + str(channel))
                                    print("Excessive phase shift in channel " + str(c))
                                    print("Frequency: " + str(frequency))
                                    print("Antenna: " + str(a))
                                    print("Polarization: " + str(p))
                                    print("Sample index: " + str(i))
                                    print("Reference value: " + str(ref_channel_value))
                                    print("Reference phase " + str(ref_phase_value_360))
                                    print("Channel value " + str(channel_value))
                                    print("Channel phase " + str(phase_value_360))
                                    print("Expected phase: " + str(expected_phase))
                                    print("Applied delay: " + str(applied_delay))
                                    print("Applied delay steps: " + str(delays[2*a+p]))
                                    print("Expected phase delay: " + str(expected_phase_delay))
                                    print("Periods delay: " + str(np.modf(old_div(applied_delay, (1.0 / frequency)))[1]))
                                    input("Press a key")

        print("CHANNEL " + str(channel) + " OK!")

    daq.stop_daq()
