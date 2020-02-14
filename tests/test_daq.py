from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from builtins import str
from builtins import range
import logging
import os.path
import random
import time

import test_functions as tf


# Import DAQ and Access Layer libraries
from builtins import hex

import pydaq.daq_receiver as daq
from pyaavs.tile import Tile

# Import required persisters
from pydaq.persisters import *

temp_dir = "./temp_daq_test"
data_received = False
beam_int_data_received = False
channel_int_data_received = False
test_pattern = list(range(1024))
raw_test_adders = list(range(32))
channel_test_adders = list(range(32))
beamf_test_adders = list(range(32))
channel_integration_length = 0
channel_accumulator_width = 0
channel_round_bits = 0
raw_data_synchronised = 0
dropped_integrated_beam_sample = 0


def s_round(data, bits, max_width=32):
    if bits == 0:
        return data
    elif data == -2 ** (max_width - 1):
        return data
    else:
        c_half = 2 ** (bits - 1)
        if data >= 0:
            data = (data + c_half + 0) >> bits
        else:
            data = (data + c_half - 1) >> bits
        return data


def integrated_sample_calc(data_re, data_im, integration_length, round_bits, max_width):
    power = data_re ** 2 + data_im ** 2
    accumulator = power * integration_length
    round = s_round(accumulator, round_bits, max_width)
    return round


def channelize_pattern(pattern):
    """ Change the frequency channel order to match che channelizer output
        :param pattern: pattern buffer, frequency channel in increasing order
        """
    tmp = [0] * len(pattern)
    half = old_div(len(pattern), 2)
    for n in range(old_div(half, 2)):
        tmp[4 * n] = pattern[2 * n]
        tmp[4 * n + 1] = pattern[2 * n + 1]
        tmp[4 * n + 2] = pattern[-(1 + 2 * n + 1)]
        tmp[4 * n + 3] = pattern[-(1 + 2 * n)]
    return tmp


def set_pattern(tile, stage, pattern, adders, start):
    print("Setting " + stage + " data pattern")
    signal_adder = []
    for n in range(32):
        signal_adder += [adders[n]] * 4

    for i in range(2):
        tile.tpm.tpm_pattern_generator[i].set_pattern(pattern, stage)
        tile.tpm.tpm_pattern_generator[i].set_signal_adder(signal_adder[64 * i:64 * (i + 1)], stage)
        tile['fpga1.pattern_gen.beamf_left_shift'] = 4
        tile['fpga2.pattern_gen.beamf_left_shift'] = 4
        tile['fpga1.pattern_gen.channel_left_shift'] = 0
        tile['fpga2.pattern_gen.channel_left_shift'] = 0
        if start:
            tile.tpm.tpm_pattern_generator[i].start_pattern(stage)


def check_raw(pattern, adders, data):
    global raw_data_synchronised

    ant, pol, sam = data.shape
    if raw_data_synchronised == 1:
        sam = int(sam / 8)
    for a in range(ant):
        for p in range(pol):
            for i in range(sam):
                if i % 864 == 0:
                    sample_idx = 0
                signal_idx = (a * 2 + p)
                exp = pattern[sample_idx] + adders[signal_idx]
                if tf.signed(exp) != data[a, p, i]:
                    print("Data Error!")
                    print("Antenna: " + str(a))
                    print("Polarization: " + str(p))
                    print("Sample index: " + str(i))
                    print("Expected data: " + str(tf.signed(exp)))
                    print("Received data: " + str(data[a, p, i]))
                    exit(-1)
                else:
                    sample_idx += 1
    print("Raw data are correct")


def check_channel(pattern, adders, data):
    ch, ant, pol, sam = data.shape
    for c in range(ch):
        for a in range(ant):
            for p in range(pol):
                sample_idx = 2 * c
                signal_idx = (a * 2 + p)
                exp_re = pattern[sample_idx] + adders[signal_idx]
                exp_im = pattern[sample_idx + 1] + adders[signal_idx]
                exp = (tf.signed(exp_re), tf.signed(exp_im))
                for i in range(16):
                    if exp[0] != data[c, a, p, i][0] or exp[1] != data[c, a, p, i][1]:
                        print("Data Error!")
                        print("Frequency Channel: " + str(c))
                        print("Antenna: " + str(a))
                        print("Polarization: " + str(p))
                        print("Sample index: " + str(i))
                        print("Expected data: " + str(exp))
                        print("Received data: " + str(data[c, a, p, i]))
                        exit(-1)
    print("Channel data are correct")


def check_beam(pattern, adders, data):
    pol, ch, sam, x = data.shape
    x = 0
    for c in range(ch):
        for p in range(pol):
            for s in range(sam):
                sample_idx = (old_div(c, 2)) * 4 + 2 * p
                signal_idx = 16 * (c % 2)
                exp_re = (pattern[sample_idx] + adders[signal_idx]) * 16
                exp_im = (pattern[sample_idx + 1] + adders[signal_idx]) * 16
                exp = (tf.signed(exp_re, 12, 16), tf.signed(exp_im, 12, 16))
                for i in range(16):  # range(sam):
                    if exp[0] != data[p, c, s, x][0] or exp[1] != data[p, c, s, x][1]:
                        print("Data Error!")
                        print("Frequency Channel: " + str(c))
                        print("Polarization: " + str(p))
                        print("Sample index: " + str(i))
                        print("Expected data: " + str(exp))
                        print("Received data: " + str(data[p, c, s, x]))
                        exit(-1)
    print("Beam data are correct")


def check_integrated_channel(pattern, adders, data):
    ch, ant, pol, sam = data.shape
    for c in range(ch):
        for a in range(ant):
            for p in range(pol):
                sample_idx = 2 * c
                signal_idx = (a * 2 + p)
                exp_re = pattern[sample_idx] + adders[signal_idx]
                exp_im = pattern[sample_idx + 1] + adders[signal_idx]
                exp = integrated_sample_calc(tf.signed(exp_re), tf.signed(exp_im), channel_integration_length,
                                             channel_round_bits, channel_accumulator_width)
                for i in range(1):  # range(sam):
                    if exp != data[c, a, p, i]:
                        print("Data Error!")
                        print("Frequency Channel: " + str(c))
                        print("Antenna: " + str(a))
                        print("Polarization: " + str(p))
                        print("Sample index: " + str(i))
                        print("Expected data: " + str(exp))
                        print("Expected data re: " + str(tf.signed(exp_re)))
                        print("Received data im: " + str(tf.signed(exp_im)))
                        print("Received data: " + str(data[c, a, p, i]))
                        exit(-1)
    print("Integrated Channel data are correct")


def check_integrated_beam(pattern, adders, data):
    pol, ch, ant, sam = data.shape
    for c in range(ch):
        for a in range(ant):
            for p in range(pol):
                sample_idx = (old_div(c, 2)) * 4 + 2 * p
                signal_idx = 16 * (c % 2)
                exp_re = (pattern[sample_idx] + adders[signal_idx]) * 16
                exp_im = (pattern[sample_idx + 1] + adders[signal_idx]) * 16
                exp_re_sign = tf.signed(exp_re, 12, 12)
                exp_im_sign = tf.signed(exp_im, 12, 12)
                exp = integrated_sample_calc(exp_re_sign, exp_im_sign, beamf_integration_length, beamf_round_bits,
                                             beamf_accumulator_width)
                for i in range(1):  # range(sam):
                    if exp != data[p, c, a, i]:
                        print("Data Error!")
                        print("Frequency Channel: " + str(c))
                        print("Antenna: " + str(a))
                        print("Polarization: " + str(p))
                        print("Sample index: " + str(i))
                        print("Expected data: " + str(exp))
                        print("Expected data re: " + str(exp_re) + " " + hex(exp_re))
                        print("Received data im: " + str(exp_im) + " " + hex(exp_im))
                        print("Received data: " + str(data[p, c, a, i]))
                        exit(-1)
    print("Integrated Beam data are correct")


def data_callback(mode, filepath, _):
    # Note that this will be called asynchronosuly from the C code when a new file is generated
    # If you want to control the flow of the main program as data comes in, then you need to synchronise
    # with a global variable. In this example, there will be an infinite loop between sending data and receiving data
    global data_received

    # If you want to perform some checks in the data here, you will need to use the persisters scrips to read the
    # data. Note that the persister will read the latest file if no specific timestamp is provided
    # filename will contain the full path

    if mode == "burst_raw":
        raw_file = RawFormatFileManager(root_path=os.path.dirname(filepath))
        data, timestamps = raw_file.read_data(antennas=list(range(16)),
                                              # List of channels to read (not used in raw case)
                                              polarizations=[0, 1],
                                              n_samples=32 * 1024)
        print("Raw data: {}".format(data.shape))
        check_raw(test_pattern, raw_test_adders, data)

    if mode == "burst_channel":
        channel_file = ChannelFormatFileManager(root_path=os.path.dirname(filepath))
        data, timestamps = channel_file.read_data(channels=list(range(512)),
                                                  # List of channels to read (not used in raw case)
                                                  antennas=list(range(16)),
                                                  polarizations=[0, 1],
                                                  n_samples=128)
        print("Channel data: {}".format(data.shape))
        check_channel(test_pattern, channel_test_adders, data)

    if mode == "burst_beam":
        beam_file = BeamFormatFileManager(root_path=os.path.dirname(filepath))
        data, timestamps = beam_file.read_data(channels=list(range(384)),
                                               # List of channels to read (not used in raw case)
                                               polarizations=[0, 1],
                                               n_samples=32)
        print("Beam data: {}".format(data.shape))
        check_beam(test_pattern, beamf_test_adders, data)

    data_received = True


def integrated_data_callback(mode, filepath, tile):
    global channel_int_data_received
    global beam_int_data_received
    global dropped_integrated_beam_sample

    if mode == "integrated_channel":
        channel_file = ChannelFormatFileManager(root_path=os.path.dirname(filepath), daq_mode=FileDAQModes.Integrated)
        data, timestamps = channel_file.read_data(antennas=list(range(16)),
                                                  polarizations=[0, 1],
                                                  n_samples=1)
        print("Integrated channel data: {}".format(data.shape))
        check_integrated_channel(test_pattern, channel_test_adders, data)
        channel_int_data_received = True

    if mode == "integrated_beam":
        beam_file = BeamFormatFileManager(root_path=os.path.dirname(filepath), daq_mode=FileDAQModes.Integrated)
        data, timestamps = beam_file.read_data(channels=list(range(384)),
                                               polarizations=[0, 1],
                                               n_samples=1)
        print("Integrated beam data: {}".format(data.shape))
        if dropped_integrated_beam_sample == 0:
            check_integrated_beam(test_pattern, beamf_test_adders, data)
            beam_int_data_received = True
        else:
            print("Drop integrated beam sample")
            dropped_integrated_beam_sample -= 1


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
    parser.add_option("--interface", action="store", dest="interface",
                      default="eth3", help="Network interface [default: eth3]")
    parser.add_option("--test", action="store", dest="test_type",
                      default="all", help="Test stage [raw, channel, beam, integrated, non-integrated. default: all]")
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
        'receiver_interface': conf.interface,
        'directory': temp_dir,
        'nof_beam_channels': 384,
        'nof_beam_samples': 32,
        'receiver_frame_size': 9000,
        'nof_channel_samples': 256
    }

    # Configure the DAQ receiver and start receiving data
    daq.populate_configuration(daq_config)
    daq.initialise_daq()

    # Start whichever consumer is required and provide callback
    daq.start_raw_data_consumer(callback=data_callback)  # Change start_xxxx_data_consumer with data mode required
    daq.start_channel_data_consumer(callback=data_callback)  # Change start_xxxx_data_consumer with data mode required
    daq.start_beam_data_consumer(callback=data_callback)  # Change start_xxxx_data_consumer with data mode required
    #
    # raw data
    #
    if conf.test_type in ["all", "raw", "non-integrated"]:
        remove_files()
        for i in range(4):
            # Set data received to False
            data_received = False

            # Start pattern generator
            for n in range(1024):
                if i % 2 == 0:
                    test_pattern[n] = n
                else:
                    test_pattern[n] = random.randrange(0, 255, 1)

            raw_test_adders = list(range(32))
            set_pattern(tile, "jesd", test_pattern, raw_test_adders, start=True)
            # Send data from tile
            tile.send_raw_data()

            # Wait for data to be received
            while not data_received:
                time.sleep(0.1)
        #
        # raw data synchronised
        #
        remove_files()
        raw_data_synchronised = 1
        for i in range(4):
            # Set data received to False
            data_received = False

            # Start pattern generator
            for n in range(1024):
                if i % 2 == 0:
                    test_pattern[n] = n
                else:
                    test_pattern[n] = random.randrange(0, 255, 1)

            raw_test_adders = list(range(32))
            set_pattern(tile, "jesd", test_pattern, raw_test_adders, start=True)
            # Send data from tile
            tile.send_raw_data_synchronised()

            # Wait for data to be received
            while not data_received:
                time.sleep(0.1)
    #
    # channel data
    #
    if conf.test_type in ["all", "channel", "non-integrated"]:
        remove_files()
        for i in range(4):
            # Set data received to False
            data_received = False

            # Start pattern generator
            for n in range(1024):
                if i % 2 == 0:
                    test_pattern[n] = n
                else:
                    test_pattern[n] = random.randrange(0, 255, 1)

            channel_test_adders = list(range(32))
            set_pattern(tile, "channel", channelize_pattern(test_pattern), channel_test_adders, start=True)
            # Send data from tile
            tile.send_channelised_data(256)

            # Wait for data to be received
            while not data_received:
                time.sleep(0.1)
    #
    # beam data
    #
    if conf.test_type in ["all", "beam", "non-integrated"]:
        remove_files()
        for i in range(4):
            # Set data received to False
            data_received = False

            # Start pattern generator
            for n in range(1024):
                if i % 2 == 0:
                    test_pattern[n] = n
                else:
                    test_pattern[n] = random.randrange(0, 255, 1)

            beamf_test_adders = list(range(16)) + list(range(2, 16 + 2))
            set_pattern(tile, "beamf", test_pattern, beamf_test_adders, start=True)
            # Send data from tile
            tile.send_beam_data()

            # Wait for data to be received
            while not data_received:
                time.sleep(0.1)

    if conf.test_type in ["all", "raw", "channel", "beam", "non-integrated"]:
        daq.stop_daq()

    if conf.test_type in ["all", "integrated"]:
        print("Checking integrated data format now...")

        daq_config = {
            'receiver_interface': conf.interface,  # CHANGE THIS if required
            'directory': temp_dir,  # CHANGE THIS if required
            'nof_beam_channels': 384,
            'nof_beam_samples': 1
        }

        channel_integration_length = tile['fpga1.lmc_integrated_gen.channel_integration_length']
        channel_accumulator_width = tile['fpga1.lmc_integrated_gen.channel_accumulator_width']
        channel_round_bits = tile['fpga1.lmc_integrated_gen.channel_scaling_factor']

        beamf_integration_length = tile['fpga1.lmc_integrated_gen.beamf_integration_length']
        beamf_accumulator_width = tile['fpga1.lmc_integrated_gen.beamf_accumulator_width']
        beamf_round_bits = tile['fpga1.lmc_integrated_gen.beamf_scaling_factor']

        daq.populate_configuration(daq_config)
        daq.initialise_daq()

        for i in range(2):
            # Start pattern generator
            for n in range(1024):
                if i % 2 == 0:
                    test_pattern[n] = n
                else:
                    test_pattern[n] = random.randrange(0, 255, 1)

            channel_test_adders = list(range(32))
            set_pattern(tile, "channel", channelize_pattern(test_pattern), channel_test_adders, start=True)
            beamf_test_adders = list(range(16)) + list(range(2, 16 + 2))
            set_pattern(tile, "beamf", test_pattern, beamf_test_adders, start=True)

            print("Sleeping for " + str(channel_integration_length * 1.08e-6 + 0.5) + " seconds...")
            time.sleep(channel_integration_length * 1.08e-6 + 0.5)

            # Set data received to False
            remove_files()
            channel_int_data_received = False
            beam_int_data_received = False

            daq.start_integrated_channel_data_consumer(callback=integrated_data_callback)
            daq.start_integrated_beam_data_consumer(callback=integrated_data_callback)

            # Wait for data to be received
            while (not channel_int_data_received) or (not beam_int_data_received):
                time.sleep(0.1)

            daq.stop_integrated_channel_data_consumer()
            daq.stop_integrated_beam_data_consumer()
