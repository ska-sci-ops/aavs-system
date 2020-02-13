from __future__ import print_function
from __future__ import division
# Import DAQ and Access Layer libraries
from builtins import str
from builtins import range
from past.utils import old_div
import pydaq.daq_receiver as daq
from pyaavs.tile import Tile


from datetime import datetime
from sys import stdout
import numpy as np
import os.path
import logging
import random
import math
import time



def s_round(data, bits, max_width=32):
    if bits == 0:
        return data
    elif data == -2**(max_width-1):
        return data
    else:
        c_half = 2**(bits-1)
        if data >= 0:
            data = (data + c_half + 0) >> bits
        else:
            data = (data + c_half - 1) >> bits
        return data


def integrated_sample_calc(data_re, data_im, integration_length, round_bits, max_width):
    power = data_re**2 + data_im**2
    accumulator = power * integration_length
    round = s_round(accumulator, round_bits, max_width)
    return round


# Custom function to compute the absoule of the custom data type
#def complex_f(value):
#    return math.sqrt((value[0] ** 2) + (value[1] ** 2))


def signed(data, bits=8, ext_bits=8):
    data = data % 2**bits
    if data >= 2**(bits-1):
        data -= 2**bits
    if ext_bits > bits:
        if data == -2**(bits-1):
            data = -2**(ext_bits-1)
    return data


def channelize_pattern(pattern):
    """ Change the frequency channel order to match che channelizer output
    :param pattern: pattern buffer, frequency channel in increasing order
    """
    tmp = [0]*len(pattern)
    half = old_div(len(pattern), 2)
    for n in range(old_div(half, 2)):
        tmp[4*n] = pattern[2*n]
        tmp[4*n+1] = pattern[2*n+1]
        tmp[4*n+2] = pattern[-(1+2*n+1)]
        tmp[4*n+3] = pattern[-(1+2*n)]
    return tmp


def set_pattern(tile, stage, pattern, adders, start, shift=0):
    print("Setting " + stage + " data pattern")
    if stage == "channel":
        pattern_tmp = channelize_pattern(pattern)
    else:
        pattern_tmp = pattern

    signal_adder = []
    for n in range(32):
        signal_adder += [adders[n]]*4

    for i in range(2):
        tile.tpm.tpm_pattern_generator[i].set_pattern(pattern_tmp, stage)
        tile.tpm.tpm_pattern_generator[i].set_signal_adder(signal_adder[64*i:64*(i+1)], stage)
        tile['fpga1.pattern_gen.%s_left_shift' % stage] = shift
        tile['fpga2.pattern_gen.%s_left_shift' % stage] = shift
        tile['fpga1.pattern_gen.beamf_left_shift'] = 4
        tile['fpga2.pattern_gen.beamf_left_shift'] = 4
        if start:
            tile.tpm.tpm_pattern_generator[i].start_pattern(stage)


def stop_pattern(tile, stage):
    print("Stopping " + stage + " data pattern")
    if stage == "all":
        stages = ["jesd", "channel", "beamf"]
    else:
        stages = [stage]
    for s in stages:
        for i in range(2):
            tile.tpm.tpm_pattern_generator[i].stop_pattern(s)


def set_chennelizer_walking_pattern(tile):
    set_pattern(tile, "channel", list(range(1024)), [0]*32, True, 0)
    tile['fpga1.pattern_gen.%s_ctrl.frame_offset_enable' % "channel"] = 1
    tile['fpga2.pattern_gen.%s_ctrl.frame_offset_enable' % "channel"] = 1
    tile['fpga1.pattern_gen.%s_ctrl.frame_offset_adder' % "channel"] = 1
    tile['fpga2.pattern_gen.%s_ctrl.frame_offset_adder' % "channel"] = 1
    tile['fpga1.pattern_gen.%s_ctrl.frame_offset_lo' % "channel"] = 0
    tile['fpga2.pattern_gen.%s_ctrl.frame_offset_lo' % "channel"] = 0
    tile['fpga1.pattern_gen.%s_ctrl.frame_offset_hi' % "channel"] = 255
    tile['fpga2.pattern_gen.%s_ctrl.frame_offset_hi' % "channel"] = 255
    tile['fpga1.pattern_gen.%s_frame_offset_change' % "channel"] = 0
    tile['fpga2.pattern_gen.%s_frame_offset_change' % "channel"] = 0

    tile['fpga1.pattern_gen.%s_ctrl.frame_offset_clear' % "channel"] = 1
    tile['fpga2.pattern_gen.%s_ctrl.frame_offset_clear' % "channel"] = 1
    tile.wait_pps_event()
    tile['fpga1.pattern_gen.%s_ctrl.frame_offset_clear' % "channel"] = 0
    tile['fpga2.pattern_gen.%s_ctrl.frame_offset_clear' % "channel"] = 0

def set_delay(tile, delay):
    tile.tpm.test_generator[0].set_delay(delay[0:16])
    tile.tpm.test_generator[1].set_delay(delay[16:32])


def get_beam_value(data, pol, channel):
    sample = 0
    x = 0
    return data[pol, channel, sample, x][0] + data[pol, channel, sample, x][1]*1j


def reset_beamf_coeff(tile,  gain=2.0):
    # print "Reset beamormer coefficients"
    for n in range(16):
        cal_coeff = [[complex(gain), complex(0.0), complex(0.0), complex(gain)]] * 512
        tile.tpm.beamf_fd[old_div(n,8)].load_calibration(n % 8, cal_coeff[64:448])
        # tile.tpm.beamf_fd[n/8].load_cal_curve(n % 8, 0, cal_coeff)
    #tile.tpm.beamf_fd[0].compute_calibration_coefs()
    #tile.tpm.beamf_fd[1].compute_calibration_coefs()
    tile.tpm.beamf_fd[0].switch_calibration_bank(force=True)
    tile.tpm.beamf_fd[1].switch_calibration_bank(force=True)


def set_beamf_coeff(tile, coeff, channel):
    for n in range(16):
        # cal_coeff = [[complex(0.0), complex(0.0), complex(0.0), complex(0.0)]] * 512
        cal_coeff = [np.random.random_sample(4)] * 512
        cal_coeff[channel] = [coeff[0][n], complex(0.0), complex(0.0), coeff[1][n]]
        #tile.tpm.beamf_fd[n/8].load_calibration(n % 8, cal_coeff[64:448])
        tile.tpm.beamf_fd[old_div(n,8)].load_cal_curve(n % 8, 0, cal_coeff[64:448])
    tile.tpm.beamf_fd[0].compute_calibration_coefs()
    tile.tpm.beamf_fd[1].compute_calibration_coefs()
    tile.tpm.beamf_fd[0].switch_calibration_bank()
    tile.tpm.beamf_fd[1].switch_calibration_bank()


def mask_antenna(tile, antenna, gain=1.0):
    for n in range(16):
        if n in antenna:
            cal_coeff = [[complex(0.0), complex(0.0), complex(0.0), complex(0.0)]] * 512
        else:
            cal_coeff = [[complex(gain), complex(0.0), complex(0.0), complex(gain)]] * 512
        tile.tpm.beamf_fd[old_div(n,8)].load_calibration(n % 8, cal_coeff[64:448])
    tile.tpm.beamf_fd[0].switch_calibration_bank()
    tile.tpm.beamf_fd[1].switch_calibration_bank()


def enable_adc_test_pattern(tile, adc, pattern_type, pattern_value=[[15, 67, 252, 128]]*16):
    print("Setting ADC pattern " + pattern_type)
    for adc_id in adc:
        # print "setting ADC pattern " + pattern_type + " on ADC " + str(adc_id)
        tile[("adc" + str(adc_id), 0x552)] = pattern_value[adc_id][0]
        tile[("adc" + str(adc_id), 0x554)] = pattern_value[adc_id][1]
        tile[("adc" + str(adc_id), 0x556)] = pattern_value[adc_id][2]
        tile[("adc" + str(adc_id), 0x558)] = pattern_value[adc_id][3]
        if pattern_type ==  "fixed":
            tile[("adc" + str(adc_id), 0x550)] = 0x8
        elif pattern_type == "ramp":
            tile[("adc" + str(adc_id), 0x550)] = 0xF
        else:
            print("Supported pattern are fixed, ramp")
            exit()


def disable_adc_test_pattern(tile, adc):
    for adc_id in adc:
        tile[("adc" + str(adc_id), 0x550)] = 0x0


def get_beamf_pattern_data(channel, pattern, adder, shift):
    index = 4 * (old_div(channel, 2))
    ret = []
    for n in range(4):
        adder_idx = 64 * (channel % 2) + n
        data = pattern[index+n]
        data += adder[adder_idx]
        data &= 0xFF
        data = data << shift
        data = signed(data, 12, 12)
        ret.append(data)
    return ret


def rms_station_log(station, sampling_period=1.0):
    file_names = []
    time_now = str((datetime.utcnow() - datetime(1970, 1, 1)).total_seconds())
    time_now = time_now.replace(".", "_")
    for tile in station.tiles:
        file_name = "rms_log_" + str(tile._ip) + "_" + time_now + ".log"
        f = open(file_name, "w")
        f.write("")
        f.close()
        file_names.append(file_name)
    time_prev = datetime.now()
    try:
        while True:
            time_this = datetime.now()
            time_diff = time_this - time_prev
            time_sec = time_diff.total_seconds()
            time_prev = time_this
            for i, tile in enumerate(station.tiles):
                rms = tile.get_adc_rms()
                f = open(file_names[i], "a")
                txt = str(time_sec)
                for r in range(len(rms)):
                    txt += " " + str(rms[r])
                txt += "\n"
                f.write(txt)
                f.close()
            time.sleep(sampling_period)
    except KeyboardInterrupt:
        print('interrupted!')


def ddr3_test(station, duration):
    station['fpga1.ddr3_simple_test.start'] = 0
    station['fpga2.ddr3_simple_test.start'] = 0

    time.sleep(0.1)

    station['fpga1.ddr3_simple_test.start'] = 1
    station['fpga2.ddr3_simple_test.start'] = 1

    fpga1_pass = station['fpga1.ddr3_simple_test.pass']
    fpga2_pass = station['fpga2.ddr3_simple_test.pass']
    fpga1_status = station['fpga1.ddr3_if.status']
    fpga2_status = station['fpga2.ddr3_if.status']

    for n in range(duration):
        time.sleep(1)
        for n in range(len(station.tiles)):
            if fpga1_pass[n] == station['fpga1.ddr3_simple_test.pass'][n]:
                print("Tile %d FPGA1 error. Pass does not increment." % n)
                return
            if fpga2_pass[n] == station['fpga2.ddr3_simple_test.pass'][n]:
                print("Tile %d FPGA2 error. Pass does not increment." % n)
                return
            if station['fpga1.ddr3_simple_test.error'][n] == 1:
                print("Tile %d FPGA1 error. Test error." % n)
                return
            if station['fpga2.ddr3_simple_test.error'][n] == 1:
                print("Tile %d FPGA2 error. Test error." % n)
                return
            if (station['fpga1.ddr3_if.status'][n] & 0xF00) != (fpga1_status[n] & 0xF00):
                print("Tile %d FPGA1 error. Reset error." % n)
                return
            if (station['fpga2.ddr3_if.status'][n] & 0xF00) != (fpga2_status[n] & 0xF00):
                print("Tile %d FPGA2 error. Reset error." % n)
                return
            print("Test running ...")

    station['fpga1.ddr3_simple_test.start'] = 0
    station['fpga2.ddr3_simple_test.start'] = 0
    print("Test passed!")


def network_test(station, duration):
    station.mii_test(0xFFFFFFFF, show_result=False)
    for n in range(duration):
        time.sleep(1)
        for i, tile in enumerate(station.tiles):
            print("Tile " + str(i) + " MII test result:")
            tile.mii_show_result()
        print()
        print()
    station['fpga1.regfile.eth10g_ctrl'] = 0
    station['fpga2.regfile.eth10g_ctrl'] = 0
    print("Test ended!")

