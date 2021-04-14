#!/usr/bin/env python2
import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt

from pydaq import daq_receiver as receiver
from datetime import datetime, timedelta
from pydaq.persisters import *
from pyaavs import station
from config_manager import ConfigManager
from numpy import random
from spead_beam_power_realtime import SpeadRxBeamPowerRealtime
from spead_beam_power_offline import SpeadRxBeamPowerOffline
import test_functions as tf
import numpy as np
import tempfile
import logging
import shutil
import time
import os

# Number of samples to process
nof_samples = 256*1024
# Global variables to track callback
tiles_processed = None
buffers_processed = 0
data_ready = False


def channel_callback(data_type, filename, tile):
    """ Data callback to process data
    :param data_type: Type of data that was generated
    :param filename: Filename of data file where data was saved """

    global tiles_processed
    global data_ready

    nof_buffers = 2
    
    if data_ready:
        return

    tiles_processed[tile] += 1
    if np.all(tiles_processed >= nof_buffers):
        data_ready = True
        
        
def station_callback(data_type, filename, samples):
    """ Data callback to process data
    :param data_type: Type of data that was generated
    :param filename: Filename of data file where data was saved """

    global buffers_processed
    global data_ready
    global nof_samples
    
    if data_ready:
        return

    buffers_processed += 1
    if nof_samples == samples:
        data_ready = True
       

def delete_files(directory):
    """ Delete all files in directory """
    for f in os.listdir(directory):
        os.remove(os.path.join(directory, f))


def offline_beamformer(data):
    global nof_samples
    x = np.sum(np.power(np.abs(np.sum(data[:, 0, :], axis=0)), 2))
    y = np.sum(np.power(np.abs(np.sum(data[:, 1, :], axis=0)), 2))

    return x / nof_samples, y / nof_samples


def initialise_daq(daq_config):
    logging.info("Starting DAQ")
    receiver.populate_configuration(daq_config)
    receiver.initialise_daq()
    receiver.start_continuous_channel_data_consumer(channel_callback)
    # Wait for DAQ to initialise
    tf.accurate_sleep(4)
    logging.info("DAQ initialised")


def stop_daq():
    # Stop DAQ
    try:
        receiver.stop_daq()
    except Exception as e:
        logging.error("Failed to stop DAQ cleanly: {}".format(e))


def get_offline_beam(daq_config, test_station, channel, antennas_per_tile=16):
    """ Grab channel data """
    global buffers_processed
    global data_ready
    global tiles_processed

    # Reset number of processed tiles
    tiles_processed = np.zeros(daq_config['nof_tiles'], dtype=np.int)

    # Stop any data transmission
    test_station.stop_data_transmission()
    tf.accurate_sleep(1)

    # # Start DAQ
    # logging.info("Starting DAQ")
    # receiver.populate_configuration(daq_config)
    # receiver.initialise_daq()
    # receiver.start_continuous_channel_data_consumer(channel_callback)
    #
    # # Wait for DAQ to initialise
    # tf.accurate_sleep(2)

    # Start sending data
    test_station.send_channelised_data_continuous(channel, daq_config['nof_channel_samples'])
    logging.info("Acquisition started")

    # Wait for observation to finish
    while not data_ready:
        tf.accurate_sleep(0.1)
    data_ready = False

    # All done, instruct receiver to stop writing to disk
    receiver.WRITE_TO_DISK = False
    logging.info("Channelised Data acquired")

    # # Stop DAQ
    # try:
    #     receiver.stop_daq()
    # except Exception as e:
    #     logging.error("Failed to stop DAQ cleanly: {}".format(e))

    # Stop data transmission and reset
    test_station.stop_data_transmission()
    tiles_processed = np.zeros(daq_config['nof_tiles'], dtype=np.int)
    buffers_processed = 0
    receiver.WRITE_TO_DISK = True
    data_ready = False

    # Create channel manager
    channel_file_mgr = ChannelFormatFileManager(root_path=daq_config['directory'],
                                                daq_mode=FileDAQModes.Continuous)

    # Read in generate data file, combinig data from multiple tiles
    data = np.zeros((1, daq_config['nof_tiles'] * antennas_per_tile, 2, daq_config['nof_channel_samples']),
                     dtype=np.complex64)

    for tile in range(daq_config['nof_tiles']):
        read_data, _ = channel_file_mgr.read_data(timestamp=None,
                                                  tile_id=tile,
                                                  n_samples=daq_config['nof_channel_samples'])

        read_data = (read_data['real'] + 1j * read_data['imag']).astype(np.complex64)
        data[:, tile * antennas_per_tile: (tile + 1) * antennas_per_tile, :, :] = read_data

    # antenna, pol, samples order
    data = data[0, :, :, :]
    logging.info("Beamforming data offline")
    x, y = offline_beamformer(data)

    return 10 * np.log10([x, y])

        
# def get_realtime_beam(daq_config, channel):
#     """ Grab channel data """
#     global buffers_processed
#     global data_ready
#
#     # Start DAQ
#     logging.debug("Starting DAQ")
#     receiver.populate_configuration(daq_config)
#     receiver.initialise_daq()
#     receiver.start_station_beam_data_consumer(station_callback)
#
#     # Wait for observation to finish
#     while not data_ready:
#         tf.accurate_sleep(0.1)
#
#     # All done, instruct receiver to stop writing to disk
#     logging.info("Station beam acquired")
#
#     # Stop DAQ
#     try:
#         receiver.stop_daq()
#     except Exception as e:
#         logging.error("Failed to stop DAQ cleanly: {}".format(e))
#
#     # Stop data transmission and reset
#     data_ready = False
#
#     # Read integrated station beam and return computed power
#     station_file_mgr = StationBeamFormatFileManager(root_path=daq_config['directory'], daq_mode=FileDAQModes.Integrated)
#
#     # Data is in pol/sample/channel order.
#     data, _, _ = station_file_mgr.read_data(timestamp=None, n_samples=buffers_processed)
#     beam_power = 10 * np.log10(data[:, -1, channel])
#
#     # Reset number of buffers processed
#     buffers_processed = 0
#
#     return beam_power


class TestFullStation():
    def __init__(self, station_config, logger):
        self._logger = logger
        self._station_config = station_config
        self._daq_eth_if = station_config['eth_if']
        self._total_bandwidth = station_config['test_config']['total_bandwidth']
        self._antennas_per_tile = station_config['test_config']['antennas_per_tile']
        self._pfb_nof_channels = station_config['test_config']['pfb_nof_channels']

    def prepare_test(self):
        for i, tile in enumerate(self._test_station.tiles):
            tile.set_channeliser_truncation(5)
            tf.disable_test_generator_and_pattern(tile)
            tile['fpga1.jesd204_if.regfile_channel_disable'] = 0xFFFF
            tile['fpga2.jesd204_if.regfile_channel_disable'] = 0xFFFF
            self._test_station.tiles[i].test_generator_input_select(0xFFFFFFFF)
        self._test_station.test_generator_set_tone(0, frequency=100e6, ampl=0.0)
        self._test_station.test_generator_set_tone(1, frequency=100e6, ampl=0.0)
        self._test_station.test_generator_set_noise(ampl=0.35, delay=1024)
        scale = int(np.ceil(np.log2(len(self._test_station.tiles))))
        scale -= 2
        if scale < 0:
            scale = 0
        for tile in self._test_station.tiles:
            tile['fpga1.beamf_ring.csp_scaling'] = scale
            tile['fpga2.beamf_ring.csp_scaling'] = scale
            tile.set_channeliser_truncation(3)

    def set_delay(self, random_delays, max_delay):
        delays = np.array(random_delays * max_delay, dtype=np.int)

        # interleaving same array
        delays_per_antenna = np.empty((delays.size + delays.size,), dtype=delays.dtype)
        delays_per_antenna[0::2] = delays
        delays_per_antenna[1::2] = delays

        # print(delays_per_antenna)
        for i, tile in enumerate(self._test_station.tiles):
            tile_delays = delays_per_antenna[i * self._antennas_per_tile * 2: (i + 1) * self._antennas_per_tile * 2]
            # Set delays
            tile.test_generator[0].set_delay(tile_delays[:self._antennas_per_tile].tolist())
            tile.test_generator[1].set_delay(tile_delays[self._antennas_per_tile:].tolist())

    def check_station(self):
        station_ok = True
        if not self._test_station.properly_formed_station:
            station_ok = False
        else:
            for tile in self._test_station.tiles:
                if not tile.is_programmed():
                    station_ok = False
                if not tile.beamformer_is_running():
                    station_ok = False
        return station_ok

    def execute(self, test_channel=4, max_delay=128):
        global nof_samples

        self._test_station = station.Station(self._station_config)
        self._test_station.connect()
        # reinit_todo = False
        # try:
        #     self._test_station = station.Station(self._station_config)
        #     self._test_station.connect()
        #     if not self.check_station():
        #         reinit_todo = True
        # except:
        #     reinit_todo = True
        #
        # if reinit_todo:
        #     self._logger.info("Station not properly formed, re-initilising station")
        #     self._station_config['station']['program'] = True
        #     self._station_config['station']['initialise'] = True
        #     self._station_config['station']['start_beamformer'] = True
        #     self._test_station = station.Station(self._station_config)
        #     self._test_station.connect()
        #     if not self.check_station():
        #         self._logger.info("Not possible to form station, exiting...TEST FAILED!")
        #         return

        self.prepare_test()

        # Update channel numbers
        channel_bandwidth = float(self._total_bandwidth) / int(self._pfb_nof_channels)
        nof_channels = int(self._station_config['observation']['bandwidth'] / channel_bandwidth)

        if test_channel >= nof_channels:
            self._logger.error("Station beam does not contain selected frequency channel. Exiting...")
            return
        channelised_channel = test_channel + int((self._station_config['observation']['start_frequency_channel']) / channel_bandwidth)
        beamformed_channel = test_channel

        # Generate DAQ configuration
        daq_config = {"nof_channels": 1,
                      "nof_tiles": len(self._test_station.tiles),
                      "nof_channel_samples": nof_samples,
                      "nof_beam_channels": nof_channels,
                      "nof_station_samples": nof_samples,
                      "receiver_interface": self._daq_eth_if,
                      "receiver_frame_size": 9000}

        # Create temporary directory to store DAQ generated files
        data_directory = tempfile.mkdtemp()
        daq_config['directory'] = data_directory
        self._logger.info("Using temporary directory {}".format(data_directory))

        # spead_rx_realtime_inst = spead_rx(4660, self._daq_eth_if)
        # spead_rx_offline_inst = spead_rx_offline(4660, self._daq_eth_if)
        try:

            # initialise_daq(daq_config)

            errors = 0
            # Mask antennas if required
            one_matrix = np.ones((nof_channels, 4), dtype=np.complex64)
            one_matrix[:, 1] = one_matrix[:, 2] = 0

            for i, tile in enumerate(self._test_station.tiles):
                for antenna in range(self._antennas_per_tile):
                    tile.load_calibration_coefficients(antenna, one_matrix.tolist())

            # Done downloading coefficient, switch calibration bank
            self._test_station.switch_calibration_banks(1024)
            self._logger.info("Applied default beamformer coefficients")

            nof_antennas = len(self._station_config['tiles']) * self._antennas_per_tile
            random.seed(0)  # Static seed so that each run generates the same random numbers
            random_delays = (random.random(nof_antennas) - 0.5) * 2.0

            offline_power = []
            realtime_power = []
            scale_power = []
            while max_delay > 0:
                self._logger.info("Setting time domain delays, maximum %d" % max_delay)
                self.set_delay(random_delays, max_delay)
                tf.accurate_sleep(1)

                # for n in range(4):
                #     offline_beam_power = get_offline_beam(daq_config, self._test_station, channelised_channel, self._antennas_per_tile)
                #     self._logger.info("Offline beamformed channel power: {}".format(str(offline_beam_power)))
                #     delete_files(data_directory)

                target_power = 0
                scale = 2
                for tile in self._test_station.tiles:
                    tile.set_channeliser_truncation(scale)
                while target_power < 42 or target_power > 50 and scale >= 0:
                    tf.accurate_sleep(1)
                    spead_rx_offline_inst = SpeadRxBeamPowerOffline(4660, self._daq_eth_if)
                    self._test_station.send_channelised_data_continuous(channelised_channel, daq_config['nof_channel_samples'])
                    offline_beam_power = spead_rx_offline_inst.get_power()
                    self._logger.info("Offline beamformed channel power: {}".format(str(offline_beam_power)))
                    self._test_station.stop_data_transmission()
                    del spead_rx_offline_inst
                    if offline_beam_power[0] > 50:
                        scale_up = int(offline_beam_power[0] - 50) // 6
                        scale += scale_up + 1
                    if offline_beam_power[0] < 42:
                        scale -= 1
                    for tile in self._test_station.tiles:
                        tile.set_channeliser_truncation(abs(scale))
                    target_power = offline_beam_power[0]
                offline_power.append(offline_beam_power)
                scale_power.append(scale)
                tf.accurate_sleep(2)

                spead_rx_realtime_inst = SpeadRxBeamPowerRealtime(4660, self._daq_eth_if)
                realtime_beam_power = np.asarray(spead_rx_realtime_inst.get_power(8 * nof_samples, beamformed_channel))
                self._logger.info("Realtime beamformed channel power: {}".format(str(realtime_beam_power)))
                delete_files(data_directory)
                realtime_power.append(realtime_beam_power)
                del spead_rx_realtime_inst

                max_delay = int(max_delay/2)

            rescale = offline_power[0][0] - realtime_power[0][0]

            self._logger.info("Test result:")
            self._logger.info("Step, Realtime, Offline, Difference [dB]")
            max_diff = 0.0
            for n in range(len(realtime_power)):
                diff = realtime_power[n][0] - offline_power[n][0] + rescale
                self._logger.info("%d %f %f %f" % (n, realtime_power[n][0], offline_power[n][0], diff))
                if abs(diff) > max_diff:
                    max_diff = abs(diff)

            self._logger.info("Maximum difference: %f dB" % max_diff)
            if abs(max_diff) > 0.9:
                self._logger.error("TEST FAILED!")
                errors += 1
            else:
                self._logger.info("TEST PASSED!")

            # plt.plot(np.array(realtime_power)[:, 0])
            # plt.plot(np.array(offline_power)[:, 0] - rescale)
            # plt.show()
            # plt.savefig("test_full_station.png")
            # All done, remove temporary directory
        except Exception as e:
            import traceback
            self._logger.error(traceback.format_exc())

        finally:
            # stop_daq()
            shutil.rmtree(data_directory, ignore_errors=True)
            return errors


if __name__ == "__main__":

    from optparse import OptionParser
    from sys import argv, stdout
    
    parser = OptionParser(usage="usage: %test_full_station [options]")
    parser = tf.add_default_parser_options(parser)
    parser.add_option("--max_delay", action="store", dest="max_delay",
                      type="str", default="128", help="Maximum antenna delay [default: 128]")
    parser.add_option("--test_channel", action="store", dest="test_channel",
                      type="str", default="4", help="Beam test channel ID [default: 4]")

    (opts, args) = parser.parse_args(argv[1:])

    # set up logging to file - see previous section for more details
    logging_format = "%(name)-12s - %(asctime)s - %(levelname)s - %(message)s"
    logging.basicConfig(level=logging.DEBUG,
                        format=logging_format,
                        filename='test_log/test_full_station.log',
                        filemode='w')
    # define a Handler which writes INFO messages or higher to the sys.stderr
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    # set a format which is simpler for console use
    formatter = logging.Formatter(logging_format)
    # tell the handler to use this format
    console.setFormatter(formatter)
    # add the handler to the root logger
    logging.getLogger('').addHandler(console)

    test_logger = logging.getLogger('TEST_FULL_STATION')

    # Check if a config file is specified
    if opts.config is None:
        test_logger.error("No station configuration file was defined. Exiting")
        exit()
    elif not os.path.exists(opts.config) or not os.path.isfile(opts.config):
        test_logger.error("Specified config file does not exist or is not a file. Exiting")
        exit()

    config_manager = ConfigManager(opts.test_config)
    station_config = config_manager.apply_test_configuration(opts)

    test_inst = TestFullStation(station_config, test_logger)
    test_inst.execute(int(opts.test_channel),
                      int(opts.max_delay))