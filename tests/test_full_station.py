#!/usr/bin/env python2
import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt

from pydaq import daq_receiver as receiver
from datetime import datetime, timedelta
from pydaq.persisters import *
from pyaavs import station
from numpy import random
import numpy as np
import tempfile
import logging
import shutil
import time

# Script parameters
station_config_file = None
receiver_interface = None
initialise_tile = None
program_tile = None

# Test generator and beam parameters
beam_start_frequency = 156.25e6
beam_bandwidth = 6.25e6
nof_samples = 256*1024
test_channel = 204

# Antenna delay parameters
antennas_per_tile = 16

# Global variables populated by main
channelised_channel = None
beamformed_channel = None
nof_antennas = None
nof_channels = None

# Global variables to track callback
tiles_processed = None
buffers_processed = 0
data_ready = False
nof_buffers = 2


def channel_callback(data_type, filename, tile):
    """ Data callback to process data
    :param data_type: Type of data that was generated
    :param filename: Filename of data file where data was saved """

    global tiles_processed
    global data_ready
    
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
    
    if data_ready:
        return

    buffers_processed += 1
    if nof_samples == samples:
        data_ready = True
       
       
def accurate_sleep(seconds):
    now = datetime.datetime.now()
    end = now + timedelta(seconds=seconds)
    while now < end:
        now = datetime.datetime.now()
        time.sleep(0.1)


def delete_files(directory):
    """ Delete all files in directory """
    for f in os.listdir(directory):
        os.remove(os.path.join(directory, f))


def offline_beamformer(data):
    x = np.sum(np.power(np.abs(np.sum(data[:, 0, :], axis=0)), 2))
    y = np.sum(np.power(np.abs(np.sum(data[:, 1, :], axis=0)), 2))

    return x / daq_config['nof_channel_samples'], y / daq_config['nof_channel_samples']


def get_offline_beam(daq_config, test_station):
    """ Grab channel data """
    global buffers_processed
    global data_ready
    global tiles_processed

    # Reset number of processed tiles
    tiles_processed = np.zeros(daq_config['nof_tiles'], dtype=np.int)

    # Stop any data transmission
    test_station.stop_data_transmission()
    accurate_sleep(1)

    # Start DAQ
    logging.info("Starting DAQ")
    receiver.populate_configuration(daq_config)
    receiver.initialise_daq()
    receiver.start_continuous_channel_data_consumer(channel_callback)

    # Wait for DAQ to initialise
    accurate_sleep(2)

    # Start sending data
    test_station.send_channelised_data_continuous(channelised_channel, daq_config['nof_channel_samples'])
    logging.info("Acquisition started")

    # Wait for observation to finish
    while not data_ready:
        accurate_sleep(0.1)

    # All done, instruct receiver to stop writing to disk
    receiver.WRITE_TO_DISK = False
    logging.info("Data acquired")

    # Stop DAQ
    try:
        receiver.stop_daq()
    except Exception as e:
        logging.error("Failed to stop DAQ cleanly: {}".format(e))

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
    logging.info("Beamforming data")
    x, y = offline_beamformer(data)

    return 10 * np.log10([x, y])

        
def get_realtime_beam(daq_config):
    """ Grab channel data """
    global buffers_processed
    global data_ready
    
    # Start DAQ
    logging.info("Starting DAQ")
    receiver.populate_configuration(daq_config)
    receiver.initialise_daq()
    receiver.start_station_beam_data_consumer(station_callback)
        
    # Wait for observation to finish
    while not data_ready:
        accurate_sleep(0.1)
        
    # All done, instruct receiver to stop writing to disk
    logging.info("Station beam acquired")
        
    # Stop DAQ
    try:
        receiver.stop_daq()
    except Exception as e:
        logging.error("Failed to stop DAQ cleanly: {}".format(e))
    
    # Stop data transmission and reset
    data_ready = False
    
    # Read integrated station beam and return computed power
    station_file_mgr = StationBeamFormatFileManager(root_path=daq_config['directory'], daq_mode=FileDAQModes.Integrated)
    
    # Data is in pol/sample/channel order.
    data, _, _ = station_file_mgr.read_data(timestamp=None, n_samples=buffers_processed)
    beam_power = 10 * np.log10(data[:, -1, beamformed_channel])
    
    # Reset number of buffers processed
    buffers_processed = 0
    
    return beam_power


def prepare_test(test_station):
    test_station.test_generator_input_select(0xFFFFFFFF)
    test_station.test_generator_set_tone(0, frequency=100e6, ampl=0.0)
    test_station.test_generator_set_tone(1, frequency=100e6, ampl=0.0)
    test_station.test_generator_set_noise(ampl=0.35, delay=1024)
    scale = int(np.ceil(np.log2(len(test_station.tiles))))
    for tile in test_station.tiles:
        tile['fpga1.beamf_ring.csp_scaling'] = scale + 2
        tile['fpga2.beamf_ring.csp_scaling'] = scale + 2
        tile.set_channeliser_truncation(2)

def set_delay(test_station, random_delays, max_delay):
    delays = np.array(random_delays * max_delay, dtype=np.int)

    # interleaving same array
    delays_per_antenna = np.empty((delays.size + delays.size,), dtype=delays.dtype)
    delays_per_antenna[0::2] = delays
    delays_per_antenna[1::2] = delays

    print(delays_per_antenna)
    for i, tile in enumerate(test_station.tiles):
        tile_delays = delays_per_antenna[i*antennas_per_tile*2: (i+1)*antennas_per_tile*2]
        # Set delays
        tile.test_generator[0].set_delay(tile_delays[:antennas_per_tile].tolist())
        tile.test_generator[1].set_delay(tile_delays[antennas_per_tile:].tolist())


if __name__ == "__main__":

    from optparse import OptionParser
    from sys import argv, stdout
    
    parser = OptionParser(usage="usage: %test_full_station [options]")
    parser.add_option("--config", action="store", dest="config",
                      type="str", default=None, help="Configuration file [default: None]")
    parser.add_option("-P", "--program", action="store_true", dest="program",
                      default=False, help="Program FPGAs [default: False]")
    parser.add_option("-I", "--initialise", action="store_true", dest="initialise",
                      default=False, help="Initialise TPM [default: False]")
    parser.add_option("-i", "--receiver_interface", action="store", dest="receiver_interface",
                      default="eth0", help="Receiver interface [default: eth0]")
    (opts, args) = parser.parse_args(argv[1:])
    
    # Set logging
    log = logging.getLogger('')
    log.setLevel(logging.INFO)
    line_format = logging.Formatter("%(asctime)s - %(levelname)s - %(threadName)s - %(message)s")
    ch = logging.StreamHandler(stdout)
    ch.setFormatter(line_format)
    log.addHandler(ch)
    
    # Check if a config file is specified
    if opts.config is None:
        logging.error("No station configuration file was defined. Exiting")
        exit()
    elif not os.path.exists(opts.config) or not os.path.isfile(opts.config):
        logging.error("Specified config file does not exist or is not a file. Exiting")
        exit()
        
    # Update global config
    station_config_file = opts.config
    receiver_interface = opts.receiver_interface
    initialise_tile = opts.initialise
    program_tile = opts.program
    
    # Load station configuration file
    station.load_configuration_file(station_config_file)
    
    # Override parameters
    station_config = station.configuration
    station_config['station']['program'] = program_tile
    station_config['station']['initialise'] = initialise_tile
    station_config['station']['channel_truncation'] = 5  # Increase channel truncation factor
    station_config['station']['start_beamformer'] = True
    
    # Define station beam parameters (using configuration for test pattern generator)
    station_config['observation']['start_frequency_channel'] = beam_start_frequency
    station_config['observation']['bandwidth'] = beam_bandwidth
    
    # Check number of antennas to delay
    nof_antennas = len(station_config['tiles']) * antennas_per_tile
    
    # Create station
    test_station = station.Station(station_config)
    
    # Initialise station
    test_station.connect()
    
    if not test_station.properly_formed_station:
        logging.error("Station not properly formed, exiting")
        exit()

    prepare_test(test_station)

    # Update channel numbers for script
    channel_bandwidth = 400e6 / 512.0
    nof_channels = int(station_config['observation']['bandwidth'] / channel_bandwidth)
    channelised_channel = int(test_channel)
    beamformed_channel = channelised_channel - int((station_config['observation']['start_frequency_channel']) / channel_bandwidth)
    if beamformed_channel > nof_channels - 1:
        logging.error("Station beam does not contain selected frequency channel, exiting")
    
    # Generate DAQ configuration
    daq_config = {"nof_channels": 1,
                  "nof_tiles": len(test_station.tiles),
                  "nof_channel_samples": nof_samples,
                  "nof_beam_channels": nof_channels,
                  "nof_station_samples": nof_samples,
                  "receiver_interface": receiver_interface,
                  "receiver_frame_size": 9000}
     
    # Create temporary directory to store DAQ generated files
    data_directory = tempfile.mkdtemp()
    daq_config['directory'] = data_directory
    logging.info("Using temporary directory {}".format(data_directory))
    
    try:
        
        # Mask antennas if required
        one_matrix = np.ones((nof_channels, 4), dtype=np.complex64)
        one_matrix[:, 1] = one_matrix[:, 2] = 0

        for i, tile in enumerate(test_station.tiles):
            for antenna in range(antennas_per_tile):
                tile.load_calibration_coefficients(antenna, one_matrix.tolist())

        # Done downloading coefficient, switch calibration bank 
        test_station.switch_calibration_banks(1024)
        logging.info("Applied default coefficients")

        max_delay = 128
        random.seed(0)  # Static seed so that each run generates the same random numbers
        random_delays = (random.random(nof_antennas) - 0.5) * 2.0
        #random_delays = np.array(range(nof_antennas), dtype=np.float) / float(nof_antennas)

        offline_power = []
        realtime_power = []
        while max_delay >= 0:
            logging.info("Setting delays, maximum %d" % max_delay)
            set_delay(test_station, random_delays, max_delay)
            accurate_sleep(1)

            offline_beam_power = get_offline_beam(daq_config, test_station)
            logging.info("Offline beamformed channel power: {}".format(str(offline_beam_power)))
            delete_files(data_directory)
            offline_power.append(offline_beam_power)

            realtime_beam_power = get_realtime_beam(daq_config)
            logging.info("Realtime beamformed channel power: {}".format(str(realtime_beam_power)))
            delete_files(data_directory)
            realtime_power.append(realtime_beam_power)

            if int(max_delay) == 0:
                max_delay = -1
            else:
                max_delay = max_delay // 2

        rescale = offline_power[0][0] - realtime_power[0][0]
        plt.plot(np.array(realtime_power)[:, 0])
        plt.plot(np.array(offline_power)[:, 0] - rescale)

        #plt.show()
        plt.savefig("test_full_station.png")
        # All done, remove temporary directory
    except Exception as e:
        import traceback
        logging.error(traceback.format_exc())

    finally:
        shutil.rmtree(data_directory, ignore_errors=True)       
