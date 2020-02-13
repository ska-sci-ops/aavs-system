from __future__ import print_function
from __future__ import absolute_import
from __future__ import division
# Import DAQ and Access Layer libraries
from builtins import str
from builtins import range
from past.utils import old_div
import pydaq.daq_receiver as daq
from pyaavs.tile import Tile

from . import test_functions as tf
from sys import stdout
import numpy as np
import os.path
import logging


from .spead_csp import *

temp_dir = "./temp_daq_test"
data_received = False
test_pattern = list(range(1024))
test_adders = list(range(32))
channel_integration_length = 0
channel_accumulator_width = 0
channel_round_bits = 0
raw_data_synchronised = 0

#station = ["10.0.10.3", "10.0.10.4"]#, "10.0.10.6", "10.0.10.2"]

station = [
#"tpm-1",
"tpm-1", "tpm-2", "tpm-3", "tpm-4",
"tpm-5", "tpm-6", "tpm-7", "tpm-8",
"tpm-9", "tpm-10", "tpm-11", "tpm-12",
"tpm-13", "tpm-14",
"tpm-15", "tpm-16",
]

first_channel = 200


def set_pattern(tiles, stage, pattern, adders, frame_adder, nof_tpms, start):
    print("Setting " + stage + " data pattern")
    for tile in tiles:
        tile['fpga1.pattern_gen.beamf_left_shift'] = 0
        tile['fpga2.pattern_gen.beamf_left_shift'] = 0
        for i in range(2):
            print()
            tile.tpm.tpm_pattern_generator[i].set_pattern(pattern, stage)
            tile.tpm.tpm_pattern_generator[i].set_signal_adder(adders[i*64:(i+1)*64], stage)
            if start:
                tile.tpm.tpm_pattern_generator[i].start_pattern(stage)
    print("Waiting PPS event to set frame_adder register")
    tiles[0].wait_pps_event()
    for tile in tiles:
        tile['fpga1.pattern_gen.beamf_ctrl.frame_offset_clear'] = 1
        tile['fpga2.pattern_gen.beamf_ctrl.frame_offset_clear'] = 1
        if frame_adder > 0:
            tile['fpga1.pattern_gen.beamf_ctrl.frame_offset_enable'] = 1
            tile['fpga2.pattern_gen.beamf_ctrl.frame_offset_enable'] = 1
            tile['fpga1.pattern_gen.beamf_ctrl.frame_offset_adder'] = frame_adder
            tile['fpga2.pattern_gen.beamf_ctrl.frame_offset_adder'] = frame_adder

            tile['fpga1.pattern_gen.beamf_ctrl.frame_offset_lo'] = 0
            tile['fpga2.pattern_gen.beamf_ctrl.frame_offset_lo'] = 0

            tile['fpga1.pattern_gen.beamf_ctrl.frame_offset_hi'] = int(old_div(127, nof_tpms))
            tile['fpga2.pattern_gen.beamf_ctrl.frame_offset_hi'] = int(old_div(127, nof_tpms))
    tiles[0].wait_pps_event()
    for tile in tiles:
        tile['fpga1.pattern_gen.beamf_ctrl.frame_offset_clear'] = 0
        tile['fpga2.pattern_gen.beamf_ctrl.frame_offset_clear'] = 0
    print("Beamformer Pattern Set!")

def remove_files():
    # create temp directory
    if not os.path.exists(temp_dir):
        print("Creating temp folder: " + temp_dir)
        os.system("mkdir " + temp_dir)
    os.system("rm " + temp_dir + "/*.hdf5")

if __name__ == "__main__":

    # Set logging
    log = logging.getLogger('')
    log.setLevel(logging.INFO)
    str_format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    ch = logging.StreamHandler(stdout)
    ch.setFormatter(str_format)
    log.addHandler(ch)
    remove_files()



    tiles = []
    for n in range(len(station)):
        tiles.append(Tile(ip=station[n], port=10000))
        tiles[n].connect()

    iter = 0
    pattern = [0]*1024
    adders = [0]*64 + [0]*64
    frame_adder = 1

    for tile in tiles:
        tile['fpga1.beamf_ring.csp_scaling'] = 0
        tile['fpga2.beamf_ring.csp_scaling'] = 0

    while True:

        # Starting pattern generator
        random.seed(iter)
        for n in range(1024):
            if frame_adder > 0:
                pattern[n] = 0
            elif iter % 2 == 0:
                pattern[n] = n
            else:
                pattern[n] = random.randrange(0, 255, 1)

        print("Setting pattern:")
        print(pattern[0:15])
        print("Setting frame adder: " + str(frame_adder))

        set_pattern(tiles, "beamf", pattern, adders, frame_adder, len(station), True)

        time.sleep(1)

        spead_rx_inst = spead_rx(4660)
        spead_rx_inst.run_test(len(station), pattern, adders, frame_adder, first_channel, 1000000000000)
        spead_rx_inst.close_socket()
        del spead_rx_inst

        iter += 1

        print("Iteration " + str(iter) + " with no errors!")



