from builtins import input
from sys import stdout
from tabulate import tabulate
from pyaavs import station
from config_manager import ConfigManager
import test_functions as tf
import pkg_resources
import numpy as np
import os.path
import inspect
import logging
import random
import time
import sys
import os


class TestWrapper():
    def __init__(self, tpm_config, log_file):
        self._tests = {'adc': "Check JESD link setting test patterns in the ADCs and verifying data recevied by FPGAs",
                       'daq': "Check data transfer from FPGAs to LMC using DAQ software. All data format checked: raw, channel, tile beam and integrated data.",
                       'channelizer': "Check channelizer output using the FPGA internal tone generator.",
                       'tile_beamformer': "Check if the beamformer corrects for time domain delays applied to the internally generated tone.",
                       'full_station': "Check operation of networked beamformer comparing offline and realtime beam power.",
                       'ddr': "Check on board DDR using FPGA embedded test.",
                       'f2f': "Check fast data link between FPGAs using FPGA embedded test.",
                       'eth40g': "Check 40G UDP using FPGA embedded test."}

        self.test_todo = []
        self.tpm_config = tpm_config
        self.log_file = log_file

        self.exclude_daq_tests()
        self.available_tests = list(self._tests.keys())

        self.class_dict = {}
        for test in self.available_tests:
            class_ = self.get_class(test)
            argspec = inspect.getfullargspec(class_.execute)
            argspec_args = argspec.args
            argspec_args.remove('self')
            self.class_dict[test] = {'class': class_,
                                      'parameter_names': argspec_args,
                                      'parameter_values': argspec.defaults}

    def exclude_daq_tests(self):
        #installed = {pkg.key for pkg in pkg_resources.working_set}
        try:
            import pydaq
        except:
        #if 'pydaq' not in installed:
            logging.info('pydaq not installed! Removing tests using DAQ!')
            del self._tests['adc']
            del self._tests['daq']
            del self._tests['channelizer']
            del self._tests['tile_beamformer']
            del self._tests['full_station']

    def get_class(self, test_name):
        module_ = __import__("test_" + test_name)
        class_name = [x.capitalize() for x in test_name.split("_")]
        class_name = "Test" + "".join(class_name)
        class_ = getattr(module_, class_name)
        return class_

    def print_available_test(self):
        #for test in self.available_tests:
        #    logger.info(test)
        logging.info("Avalable tests are:")
        print(tabulate(self._tests.items(), tablefmt="plain"))

    def load_tests(self, requested_tests):
        if requested_tests != "all":
            self.test_todo = requested_tests.split(",")
        else:
            self.test_todo = self.available_tests
        for test in self.test_todo:
            if test not in self.available_tests:
                logging.error("Requested test: %s is not available!")
                logging.info("Avalable tests are:")
                self.print_available_test()
                logging.info("Exiting")
                exit
        return self.test_todo

    def set_parameter_value(self, test, param_name, param_value):
        idx = self.class_dict[test]['parameter_names'].index(param_name)
        y = list(self.class_dict[test]['parameter_values'])
        y[idx] = param_value
        self.class_dict[test]['parameter_values'] = tuple(y)

    def get_parameter_value(self, test, param_name):
        idx = self.class_dict[test]['parameter_names'].index(param_name)
        return self.class_dict[test]['parameter_values'][idx]

    def get_parameter_list(self, test):
        return self.class_dict[test]['parameter_names']

    def execute(self):
        test_result = []
        ret = 0
        for test in self.test_todo:
            class_ = self.get_class(test)
            test_logger = logging.getLogger('TEST_' + test.upper())
            test_instance = class_(self.tpm_config, test_logger)
            print()
            print("* Executing %s test with following parameters:" % test.upper())
            for n in list(range(len(self.class_dict[test]['parameter_names']))):
                param_name = self.class_dict[test]['parameter_names'][n]
                param_value = self.class_dict[test]['parameter_values'][n]
                if param_name != "self":
                    print("    + %s = %s" % (param_name, param_value))
            print()
            ret_val = test_instance.execute(*self.class_dict[test]['parameter_values'])
            test_result.append(ret_val)
        for n, ret_val in enumerate(test_result):
            if ret_val == 0:
                logging.info("TEST_" + self.test_todo[n].upper() + " PASSED!")
            else:
                logging.info("TEST_" + self.test_todo[n].upper() + " FAILED!")
                ret = 1
        self.log_filter()
        return ret

    def initialise_station(self, max_power=False, start_beamformer=True):
        station_config = self.tpm_config
        station_config['station']['program'] = True
        station_config['station']['initialise'] = True
        station_config['station']['start_beamformer'] = start_beamformer
        if max_power:
            station_config['observation']['start_frequency_channel'] = 50e6
            station_config['observation']['bandwidth'] = 300e6
        station_inst = station.Station(station_config)
        station_inst.connect()
        if max_power:
            station_inst.test_generator_input_select(0xFFFFFFFF)
            station_inst.test_generator_set_noise(0.95)
        station_config['station']['program'] = False
        station_config['station']['initialise'] = False

    def adc_power_down(self):
        station_config = self.tpm_config
        station_config['station']['program'] = False
        station_config['station']['initialise'] = False
        station_inst = station.Station(station_config)
        station_inst.connect()
        station_inst['board.regfile.ctrl.ad_pdwn'] = 1
        # station_inst['board.regfile.ctrl.ad_pdwn'] = 0

    def log_filter(self, log_file_name=None):
        if log_file_name is None:
            log_file_name = self.log_file
        log_str_filtered = ""
        log_file = open(log_file_name, "r")
        for line in log_file:
            if "TEST_" in line:
                log_str_filtered += line
        log_file_filtered_name = os.path.splitext(log_file_name)[0] + "_filtered" + os.path.splitext(log_file_name)[1]
        log_file_filtered = open(log_file_filtered_name, "w")
        log_file_filtered.write(log_str_filtered)
        log_file_filtered.close()


class UI:
    def __init__(self, test_wrapper):
        self._test_wrapper = test_wrapper
        pass

    def get_parameter_value(self):
        user_input = input("Enter parameter value:")
        return user_input

    def test_configuration(self, test):
        test_wrapper = self._test_wrapper
        while True:
            user_input = None
            print()
            print("Select parameter to configure:")
            table = []
            param_list = test_wrapper.get_parameter_list(test)
            for n, param in enumerate(param_list):
                table.append(["%d)" % (n + 1), param, test_wrapper.get_parameter_value(test, param)])
            table.append(["Q)", "Exit"])
            print(tabulate(table, tablefmt="plain"))
            try:
                user_input = input()
                param_id = int(user_input)
                selected_param = param_list[param_id - 1]
                current_value = test_wrapper.get_parameter_value(test, selected_param)
                parameter_type = type(current_value)
                new_value = parameter_type(self.get_parameter_value())
                test_wrapper.set_parameter_value(test, selected_param, new_value)
            except:
                if user_input.upper() == "Q":
                    return
                else:
                    print()
                    print("Input not valid.")

    def configuration_menu(self):
        test_wrapper = self._test_wrapper
        while True:
            user_input = None
            print()
            print("Select test to configure:")
            table = []
            for n, test in enumerate(test_wrapper.available_tests):
                table.append(["%d)" % (n + 1), test.upper()])
            table.append(["Q)", "Exit"])
            print(tabulate(table, tablefmt="plain"))
            try:
                user_input = input()
                test_id = int(user_input)
                selected_test = test_wrapper.available_tests[test_id - 1]
                self.test_configuration(selected_test)
            except:
                if user_input.upper() == "Q":
                    return
                else:
                    print()
                    print("Input not valid.")

    def main_manu(self):
        test_wrapper = self._test_wrapper
        selected_test = ""
        user_input = None
        print("Available tests:")
        table = []
        for n, test in enumerate(test_wrapper.available_tests):
            table.append(["%d)" % (n + 1), test.upper(), test_wrapper._tests[test]])
        table.append(["A)", "Execute all tests"])
        table.append(["C)", "Configure test parameters"])
        table.append(["I)", "Initialise station"])
        table.append(["L)", "Initialise station without starting beamformer"])
        table.append(["P)", "Maximum power"])
        table.append(["D)", "ADCs power down"])
        table.append(["Q)", "Quit"])
        print(tabulate(table, tablefmt="plain"))
        try:
            user_input = input()
            test_id = int(user_input)
            selected_test = test_wrapper.available_tests[test_id - 1]
        except:
            if user_input.upper() == "Q":
                sys.exit()
            elif user_input.upper() == "C":
                self.configuration_menu()
            elif user_input.upper() == "I":
                test_wrapper.initialise_station(max_power=False, start_beamformer=True)
            elif user_input.upper() == "L":
                test_wrapper.initialise_station(max_power=False, start_beamformer=False)
            elif user_input.upper() == "P":
                test_wrapper.initialise_station(max_power=True, start_beamformer=True)
            elif user_input.upper() == "D":
                test_wrapper.adc_power_down()
            elif user_input.upper() == "A":
                selected_test = "all"
            else:
                print()
                print("Input not valid.")
        if selected_test != "":
            test_wrapper.load_tests(selected_test)
            test_wrapper.execute()
        print()


if __name__ == "__main__":

    from optparse import OptionParser
    from sys import argv, stdout

    parser = OptionParser(usage="usage: %station [options]")
    parser = tf.add_default_parser_options(parser)
    parser.add_option("-t", "--test", action="store", dest="test_todo",
                      default="all", help="Test to be executed [default: All]")
    parser.add_option("-p", action="store_true", dest="print_tests",
                      default=False, help="Print available tests and exit [default: False]")
    parser.add_option("-i", "--interactive", action="store_true", dest="interactive_mode",
                      default=False, help="Interactive execution mode [default: False]")
    parser.add_option("--init", action="store_true", dest="init",
                      default=False, help="Initialise station before performing tests, ignored in interactive mode [default: False]")

    (conf, args) = parser.parse_args(argv[1:])

    # set up logging to file - see previous section for more details

    test_log_file = 'test_log/test_wrapper.log'
    if not os.path.exists('test_log'):
        os.makedirs('test_log')
    logging_format = "%(name)-12s - %(asctime)s - %(levelname)s - %(message)s"
    logging.basicConfig(level=logging.DEBUG,
                        format=logging_format,
                        filename=test_log_file,
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

    config_manager = ConfigManager(conf.test_config)
    tpm_config = config_manager.apply_test_configuration(conf)

    test_wrapper = TestWrapper(tpm_config, test_log_file)

    if conf.print_tests:
        test_wrapper.print_available_test()
        sys.exit()

    if conf.interactive_mode:
        ui_inst = UI(test_wrapper)
        while True:
            ui_inst.main_manu()
    else:
        if conf.init:
            test_wrapper.initialise_station()
        test_wrapper.load_tests(conf.test_todo)
        ret = test_wrapper.execute()
        sys.exit(ret)