import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt

from datetime import datetime, timedelta, timezone
from config_manager import ConfigManager
from pyaavs import station
from multiprocessing import Process
from spead_beam_power_realtime import SpeadRxBeamPowerRealtime
from spead_beam_power_offline import SpeadRxBeamPowerOffline
import spead_beam_power_realtime
import spead_beam_power_offline
import test_functions as tf
import numpy as np
import datetime
import logging
import shutil
import h5py
import time
import os

def set_data_request(station, channel_id, number_of_samples):
    for tile in station.tiles:
        for fpga in ["fpga1", "fpga2"]:
            tile["%s.lmc_gen.channelized_single_channel_mode" % fpga] = (channel_id & 0x1FF) | 0x80000000
            tile["%s.lmc_gen.channelized_pkt_length" % fpga] = number_of_samples - 1
        
def send_channelised_data_continuous(station, channel_id, number_of_samples=65536, seconds=0.5):
    """ Send continuous channelised data from all Tiles """
    station.stop_data_transmission()
    station._wait_available()
    for tile in station.tiles:
        for i in range(len(tile.tpm.tpm_test_firmware)):
            tile.tpm.tpm_test_firmware[i].send_channelised_data_continuous(channel_id, number_of_samples=128)
            
    delay = seconds * (1 / (1080 * 1e-9) / 256)
    t0 = station.tiles[0].get_fpga_timestamp()
    t1 = t0 + int(delay)
    
    for tile in station.tiles:
        tile["fpga1.pps_manager.timestamp_req_val"] = t1
        tile["fpga2.pps_manager.timestamp_req_val"] = t1
      
    #for tile in station.tiles:  
    #    tile["fpga1.lmc_gen.request"] = 0x2
    #    tile["fpga2.lmc_gen.request"] = 0x2
     
    t2 = station.tiles[0].get_fpga_timestamp()
    print(t0, t1, t2)
    if t2 >= t1:
        print("Synchronised operation failed!")
        return -1
    else:
        return 0


class BeamComparisonObservation():
    def __init__(self, station_config, logger):
        self._logger = logger
        self._station_config = station_config
        self._daq_eth_if = station_config['eth_if']
        self._total_bandwidth = station_config['test_config']['total_bandwidth']
        self._antennas_per_tile = station_config['test_config']['antennas_per_tile']
        self._pfb_nof_channels = station_config['test_config']['pfb_nof_channels']

        if not os.path.exists('beam_comparison_data'):
            os.makedirs('beam_comparison_data')
        _time = time.strftime("%Y%m%d_%H%M%S")
        self.hdf5_realtime_file_name = 'beam_comparison_data/beam_realtime_data_' + _time + '.h5'
        self.hdf5_offline_file_name = 'beam_comparison_data/beam_offline_data_' + _time + '.h5'


    def prepare_test(self):
        return

    def execute(self, test_channel=4):

        self._test_station = station.Station(self._station_config)
        self._test_station.connect()

        self.prepare_test()

        channel_bandwidth = float(self._total_bandwidth) / int(self._pfb_nof_channels)
        nof_channels = int(self._station_config['observation']['bandwidth'] / channel_bandwidth)

        if test_channel >= nof_channels:
            self._logger.error("Station beam does not contain selected frequency channel. Exiting...")
            return
        channelised_channel = test_channel + int((self._station_config['observation']['start_frequency_channel']) / channel_bandwidth)
        beamformed_channel = test_channel

        # set_data_request(self._test_station, channelised_channel, 1024)
        
        #self._test_station.send_channelised_data_continuous(channelised_channel, 1024)
        #print("Sending some data")
        #time.sleep(2)
        #input()
        #self._test_station.stop_data_transmission()
        

        try:
            iter = 0
            while True:
                iter += 1
                self._logger.info("Starting iteration %d" % iter)

                noise = divmod(iter * 0.02, 1.0)[1]
                self._test_station.test_generator_set_noise(noise)
                self._logger.info("Set noise generator amplitude %f" % noise)
                time.sleep(1)

                self._logger.info("Acquiring channelised data, channel %d" % channelised_channel)
                while True:
                    sync_good = self._test_station.send_channelised_data_continuous(channelised_channel, 1024)
                    if sync_good:
                        break
                # while send_channelised_data_continuous(self._test_station, channelised_channel, 1024, 0.5) != 0:
                # send_channelised_data_continuous(self._test_station, channelised_channel, 1024, 0.5)
                # print("Data Request retry!")
                print("Waiting for channelised data...")
                time.sleep(2)
                spead_rx_offline_inst = SpeadRxBeamPowerOffline(4660, len(self._test_station.tiles), self._daq_eth_if)
                offline_beam_power = np.asarray(spead_rx_offline_inst.get_power())
                self._logger.info("Offline beamformed channel power: %f %f %d %d %d %d" % (offline_beam_power[0], offline_beam_power[1], offline_beam_power[2], offline_beam_power[3], offline_beam_power[4], offline_beam_power[5]))
                self._test_station.stop_data_transmission()
                offline_power = offline_beam_power
                dt = datetime.datetime.now(timezone.utc)
                utc_time = dt.replace(tzinfo=timezone.utc)
                offline_utc_timestamp = utc_time.timestamp()
                del spead_rx_offline_inst

                self._logger.info("Acquiring realtime beamformed data")
                spead_rx_realtime_inst = SpeadRxBeamPowerRealtime(4660, self._daq_eth_if)
                realtime_beam_power = np.asarray(spead_rx_realtime_inst.get_power(beamformed_channel))
                self._logger.info("Realtime beamformed channel power: %f %f %d %d %d %d" % (realtime_beam_power[0], realtime_beam_power[1], realtime_beam_power[2], realtime_beam_power[3], realtime_beam_power[4], realtime_beam_power[5]))
                realtime_power = realtime_beam_power
                dt = datetime.datetime.now(timezone.utc)
                utc_time = dt.replace(tzinfo=timezone.utc)
                realtime_utc_timestamp = utc_time.timestamp()
                del spead_rx_realtime_inst

                self.hdf5_offline_data = h5py.File(self.hdf5_offline_file_name, 'a')
                self.hdf5_offline_data.create_dataset(str(offline_utc_timestamp), data=offline_power)
                self.hdf5_offline_data.close()

                self.hdf5_realtime_data = h5py.File(self.hdf5_realtime_file_name, 'a')
                self.hdf5_realtime_data.create_dataset(str(realtime_utc_timestamp), data=realtime_power)
                self.hdf5_realtime_data.close()
        except KeyboardInterrupt:
            self._logger.info("Observation terminated by user")
            self.hdf5_offline_data.close()
            self.hdf5_realtime_data.close()
            return 0

if __name__ == "__main__":

    from optparse import OptionParser
    from sys import argv, stdout
    
    parser = OptionParser(usage="usage: %test_full_station [options]")
    parser = tf.add_default_parser_options(parser)
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

    test_inst = BeamComparisonObservation(station_config, test_logger)
    test_inst.execute(int(opts.test_channel))
