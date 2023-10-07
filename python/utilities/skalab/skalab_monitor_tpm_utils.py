import gc
import logging
import socket
import numpy as np
import copy
from pyaavs import station
from pyaavs.station import configuration
from skalab_base import SkalabBase
from skalab_utils import editClone
from PyQt5 import QtWidgets, QtCore, QtGui
from time import sleep
from pyfabil import TPMGeneric
from future.utils import iteritems
from pyfabil.base.definitions import LibraryError, BoardError

tpm_tables_address = [
    {'temperature': '["temperatures"]'},\
    {'voltage': '["voltages"]'},\
    {'current': '["currents"]'},\
    {'alarm': '["alarms"]'},\
    {'adcpll': '["adcs"]["pll_status"]'}, {'adcsysref': '["adcs"]["sysref_timing_requirements"]'}, {'adccounter': '["adcs"]["sysref_counter"]'},\
    {'clock_fpga0': ['["timing"]["clocks"]["FPGA0"]', '["timing"]["clock_managers"]["FPGA0"]']}, {'clock_fpga1': ['["timing"]["clocks"]["FPGA1"]',\
    '["timing"]["clock_managers"]["FPGA1"]']}, {'pps': '["timing"]["pps"]'}, {'pll': '["timing"]["pll"]'},\
    {'jesd': ['["io"]["jesd_interface"]["link_status"]', '["io"]["jesd_interface"]["lane_status"]']}, {'jesdlane_fpga0_core0': '["io"]["jesd_interface"]["lane_error_count"]["FPGA0"]["Core0"]'},\
    {'jesdlane_fpga0_core1': '["io"]["jesd_interface"]["lane_error_count"]["FPGA0"]["Core1"]'}, {'jesdlane_fpga1_core0': '["io"]["jesd_interface"]["lane_error_count"]["FPGA1"]["Core0"]'},\
    {'jesdlane_fpga1_core1': '["io"]["jesd_interface"]["lane_error_count"]["FPGA1"]["Core1"]'}, {'jesdfpga0': '["io"]["jesd_interface"]["resync_count"]'}, {'jesdfpga1': '["io"]["jesd_interface"]["qpll_status"]'},\
    {'ddr': '["io"]["ddr_interface"]["initialisation"]'}, {'ddr1_reset': '["io"]["ddr_interface"]["reset_counter"]'}, {'f2f': '["io"]["f2f_interface"]'}, {'udp': ['["io"]["udp_interface"]["arp"]', '["io"]["udp_interface"]["status"]']},\
    {'crcerrorcount': '["io"]["udp_interface"]["crc_error_count"]'}, {'linkuplosscount': '["io"]["udp_interface"]["linkup_loss_count"]'}, {'biperrorcount_fpga0': '["io"]["udp_interface"]["bip_error_count"]["FPGA0"]'},\
    {'biperrorcount_fpga1': '["io"]["udp_interface"]["bip_error_count"]["FPGA1"]'}, {'decodeerrorcount_fpga0': '["io"]["udp_interface"]["bip_error_count"]["FPGA0"]'}, {'decodeerrorcount_fpga1': '["io"]["udp_interface"]["bip_error_count"]["FPGA1"]'},\
    {'dsp': '["dsp"]["tile_beamf"]'}, {'dsp_station': '["dsp"]["station_beamf"]["status"]'}, {'ddr_parity': '["dsp"]["station_beamf"]["ddr_parity_error_count"]'}]
# TODO USE this 2 methods when subrack attributes are defined
""" def getThreshold(wg,tlm,top_attr,warning_factor):
    default = wg.qline_subrack_threshold.text()
    if default != 'API_alarm.txt':
        try:
            with open(default, 'r') as file:
                a_lines = []
                for line in file:
                    line = line.strip()
                    line = eval(line)
                    a_lines.append(line)
            alarm = a_lines
            warning = copy.deepcopy(alarm)
            for i in range(len(top_attr)):
                keys = list(alarm[i][top_attr[i]].keys())
                for j in range(len(keys)):
                    alarm_values = list(alarm[i][top_attr[i]][keys[j]])
                    if alarm_values != [None,None]:
                        factor = (alarm_values[1]-alarm_values[0]) * (warning_factor)
                        warning_values = [round(alarm_values[0] + factor,2), round(alarm_values[1] - factor,2)]
                    else:
                        warning_values = [None,None]
                    warning[i][top_attr[i]][keys[j]] =  warning_values
        except:
            #log error
            [alarm,warning] = getDefaultThreshold(tlm,top_attr,warning_factor)
    else: 
        [alarm,warning] = getDefaultThreshold(tlm,top_attr,warning_factor)

    writeThresholds(wg.ala_text,wg.war_text, alarm, warning)
    return alarm, warning 

def getDefaultThreshold(tlm,top_attr,warning_factor):
    #log load default api values
    alarm = copy.deepcopy(tlm)
    warning = copy.deepcopy(tlm)
    alarm_values = {}
    warning_values = {}
    for i in range(len(top_attr)):
        keys = list(tlm[i][top_attr[i]].keys())
        for j in range(len(keys)):
            alarm_values = list(tlm[i][top_attr[i]][keys[j]]['exp_value'].values())
            alarm[i][top_attr[i]][keys[j]] =  alarm_values
            if alarm_values != [None,None]:
                factor = (alarm_values[1]-alarm_values[0]) * (warning_factor)
                warning_values = [round(alarm_values[0] + factor,2), round(alarm_values[1] - factor,2)]
            else:
                warning_values = [None,None]
            warning[i][top_attr[i]][keys[j]] =  warning_values
    file = open('API_alarm.txt','w+')
    for item in alarm:
        file.write(str(item) + "\n")
    file.close()
    return alarm, warning """

# TODO this methods are temnporaney
def getThreshold(wg,tlm,top_attr):
    default = wg.qline_subrack_threshold.text()
    if default != 'default_subrack_alarm.txt':
        try:
            with open(default, 'r') as file:
                a_lines = []
                for line in file:
                    line = line.strip()
                    line = eval(line)
                    a_lines.append(line)
            alarm = a_lines
        except:
            #log error
            alarm = getDefaultThreshold(tlm,top_attr)
    else: 
        alarm = getDefaultThreshold(tlm,top_attr)

    writeThresholds(wg.ala_text,wg.war_text, alarm)
    return alarm
    
def getDefaultThreshold(tlm,top_attr):
    #log load default api values
    alarm = copy.deepcopy(tlm)
    alarm_values = {}
    for i in range(len(top_attr)):
        keys = list(tlm[i][top_attr[i]].keys())
        for j in range(len(keys)):
            alarm_values = list(tlm[i][top_attr[i]][keys[j]]['exp_value'].values())
            alarm[i][top_attr[i]][keys[j]] =  alarm_values
    file = open('default_subrack_alarm.txt','w+')
    for item in alarm:
        file.write(str(item) + "\n")
    file.close()
    return alarm


def writeThresholds(alarm_box, warning_box, alarm, *warning):
    alarm_box.clear()
    warning_box.clear()
    if isinstance(alarm,list):
        for item in alarm:
            alarm_box.appendPlainText(str(item))
        if warning:
            for item in warning:
                warning_box.appendPlainText(str(item))
        else:
            warning_box.appendPlainText("Warning thresholds are not implementd yet.")
    else:
        for key, value in alarm.items():  
            alarm_box.appendPlainText('%s:%s\n' % (key, value))
        if warning:
            for key, value in warning[0].items():  
                warning_box.appendPlainText('%s:%s\n' % (key, value))
    return


class TileInitialization(SkalabBase):

    signal_station_init = QtCore.pyqtSignal()

    def __init__(self, profile, swpath="") -> None:
        super(TileInitialization, self).__init__(App="monitor", Profile=profile, Path=swpath, parent=self.wgProBox)
        self.config_file = self.profile['Init']['station_file']
        self.wg.qline_configfile.setText(self.config_file)
        if 'Extras' in self.profile.keys():
            if 'text_editor' in self.profile['Extras'].keys():
                self.text_editor = self.profile['Extras']['text_editor']
        self.wg.initbar.setStyleSheet("QProgressBar"
                          "{"
                            "background-color : rgba(255, 0, 0, 255);"
                            "border : 1px"
                          "}"
  
                          "QProgressBar::chunk"
                          "{"
                            "background : rgba(0, 255, 0, 255);"
                          "}"
                          )
        self.wg.initbar.hide()

        if self.config_file:  
            station.load_configuration_file(self.config_file)
            self.station_name = station.configuration['station']['name']
            self.nof_tiles = len(station.configuration['tiles'])
            self.nof_antennas = int(station.configuration['station']['number_of_antennas'])
            self.bitfile = station.configuration['station']['bitfile']
            if len(self.bitfile) > 52:
                self.wg.qlabel_bitfile.setText("..." + self.bitfile[-52:])
            else:
                self.wg.qlabel_bitfile.setText(self.bitfile)
            self.truncation = int(station.configuration['station']['channel_truncation'])
            self.populate_table_station()
            self.loadEventStation()
            

    def loadEventStation(self):
        self.wg.qbutton_station_init.clicked.connect(lambda: self.station_init())
        self.wg.qbutton_load_configuration.clicked.connect(lambda: self.setup_config())
        self.wg.qbutton_browse.clicked.connect(lambda: self.browse_config())
        self.wg.qbutton_edit.clicked.connect(lambda: editClone(self.wg.qline_configfile.text(), self.text_editor))

    def browse_config(self):
        fd = QtWidgets.QFileDialog()
        fd.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, True)
        options = fd.options()
        self.config_file = fd.getOpenFileName(self, caption="Select a Station Config File...",
                                              directory="/opt/aavs/config/", options=options)[0]
        self.wg.qline_configfile.setText(self.config_file)

    def setup_config(self):
        if not self.config_file == "":
            # self.wgPlay.config_file = self.config_file
            # self.wgLive.config_file = self.config_file
            station.configuration = configuration.copy()
            station.load_configuration_file(self.config_file)
            self.wg.qline_configfile.setText(self.config_file)
            self.station_name = station.configuration['station']['name']
            self.nof_tiles = len(station.configuration['tiles'])
            self.nof_antennas = int(station.configuration['station']['number_of_antennas'])
            self.bitfile = station.configuration['station']['bitfile']
            self.wg.qlabel_bitfile.setText(self.bitfile)
            self.truncation = int(station.configuration['station']['channel_truncation'])
            self.populate_table_station()
            # if not self.wgPlay == None:
            #     self.wgPlay.wg.qcombo_tpm.clear()
            # if not self.wgLive == None:
            #     self.wgLive.wg.qcombo_tpm.clear()
            self.tiles = []
            for n, i in enumerate(station.configuration['tiles']):
                # if not self.wgPlay == None:
                #     self.wgPlay.wg.qcombo_tpm.addItem("TPM-%02d (%s)" % (n + 1, i))
                # if not self.wgLive == None:
                #     self.wgLive.wg.qcombo_tpm.addItem("TPM-%02d (%s)" % (n + 1, i))
                self.tiles += [i]
            self.populateTileInstance()
        else:
            msgBox = QtWidgets.QMessageBox()
            msgBox.setText("SKALAB: Please SELECT a valid configuration file first...")
            msgBox.setWindowTitle("Error!")
            msgBox.exec_()


    def do_station_init(self):
        self.wg.initbar.setValue(40)
        station.configuration['station']['initialise'] = True
        station.configuration['station']['program'] = True
        try:
            self.tpm_station = station.Station(station.configuration)
            self.wg.qbutton_station_init.setEnabled(False)
            self.wg.initbar.setValue(70)
            self.tpm_station.connect()
            self.wg.initbar.hide()
            station.configuration['station']['initialise'] = False
            station.configuration['station']['program'] = False
            if self.tpm_station.properly_formed_station:
                self.wg.qbutton_station_init.setStyleSheet("background-color: rgb(78, 154, 6);")
                for k in range(len(self.tpm_slot_ip)):
                    if self.tpm_slot_ip[k] in self.tpm_station.configuration['tiles'] and self.tpm_slot_ip[k] != '0' :
                        self.tpm_initialized[k] = True
                        self.tpm_station.configuration['tiles'].index(self.tpm_slot_ip[k])
                        self.tpm_active[k] = self.tpm_station.tiles[self.tpm_station.configuration['tiles'].index(self.tpm_slot_ip[k])]
                self.tpmStatusChanged()
                #self.wait_check_tpm.set()
                # Switch On the PreADUs
                for tile in self.tpm_station.tiles:
                    tile["board.regfile.enable.fe"] = 1
                    sleep(0.1)
                sleep(1)
                self.tpm_station.set_preadu_attenuation(0)
                self.logger.info("TPM PreADUs Powered ON")
            else:
                self.wg.qbutton_station_init.setStyleSheet("background-color: rgb(204, 0, 0);")
            self.wg.qbutton_station_init.setEnabled(True)
            del self.tpm_station
            gc.collect()
        except:
            self.wg.qbutton_station_init.setEnabled(True)
        self.tpm_station = None


    def station_init(self):
        result = QtWidgets.QMessageBox.question(self.wg.monitor_tab, "Confirm Action -IP",
                                            "Are you sure to Program and Init the Station?",
                                            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        if result == QtWidgets.QMessageBox.Yes:
            if self.config_file:
                tpm_ip_from_subrack = []
                self.wg.initbar.show()
                # Create station
                station.load_configuration_file(self.config_file)
                # Check wether the TPM are ON or OFF
                station_on = True
                self.wg.initbar.setValue(10)
                tpm_ip_list = list(station.configuration['tiles'])
                # TODO : self.client.get_attribute('tpm_ips')['value'] sometimes gives None 
                """  with self._subrack_lock:
                    self.tpm_status_info['tpm_ips'] = self.client.get_attribute('tpm_ips')['value'] # update tpm ip
                tpm_ip_from_subrack = self.tpm_status_info['tpm_ips'] """
                
                # workaround
                for i in range(8):
                    if self.tpm_status_info['tpm_on_off'][i]:
                        tpm_ip_from_subrack.append(self.tpm_status_info['assigned_tpm_ip_adds'][i])

                self.wg.initbar.setValue(20)
                if tpm_ip_from_subrack:
                    if not len(tpm_ip_list) == len(tpm_ip_from_subrack):
                        self.wg.initbar.hide()
                        msgBox = QtWidgets.QMessageBox()
                        message = "STATION\nOne or more TPMs forming the station are OFF\nPlease check the power!"
                        msgBox.setText(message)
                        msgBox.setWindowTitle("ERROR: TPM POWERED OFF")
                        msgBox.setIcon(QtWidgets.QMessageBox.Critical)
                        details = "STATION IP LIST FROM CONFIG FILE (%d): " % len(tpm_ip_list)
                        for i in tpm_ip_list:
                            details += "\n%s" % i
                        details += "\n\nSUBRACK IP LIST OF TPM POWERED ON: (%d): " % len(tpm_ip_from_subrack)
                        for i in tpm_ip_from_subrack:
                            details += "\n%s" % i
                        msgBox.setDetailedText(details)
                        msgBox.exec_()
                        #self.logger.info(self.wgSubrack.telemetry)
                        return
                    else:
                        if not np.array_equal(tpm_ip_list, tpm_ip_from_subrack):
                            msgBox = QtWidgets.QMessageBox()
                            message = "STATION\nIPs provided by the Subrack are different from what defined in the " \
                                    "config file.\nINIT will use the new assigned IPs."
                            msgBox.setText(message)
                            msgBox.setWindowTitle("WARNING: IP mismatch")
                            msgBox.setIcon(QtWidgets.QMessageBox.Warning)
                            details = "STATION IP LIST FROM CONFIG FILE (%d): " % len(tpm_ip_list)
                            for i in tpm_ip_list:
                                details += "\n%s" % i
                            details += "\n\nSUBRACK IP LIST OF TPM POWERED ON: (%d): " % len(tpm_ip_from_subrack)
                            for i in tpm_ip_from_subrack:
                                details += "\n%s" % i
                            msgBox.setDetailedText(details)
                            msgBox.exec_()
                            station.configuration['tiles'] = list(tpm_ip_from_subrack)
                            self.wgLive.setupNewTilesIPs(list(tpm_ip_from_subrack))
                for tpm_ip in station.configuration['tiles']:
                    self.wg.initbar.setValue(30)
                    try:
                        tpm = TPMGeneric()
                        tpm_version = tpm.get_tpm_version(socket.gethostbyname(tpm_ip), 10000)
                    except (BoardError, LibraryError):
                        station_on = False
                        break
                if station_on:
                    self.signal_station_init.emit()
                else:
                    msgBox = QtWidgets.QMessageBox()
                    msgBox.setText("STATION\nOne or more TPMs forming the station is unreachable\n"
                                "Please check the power or the connection!")
                    msgBox.setWindowTitle("ERROR: TPM UNREACHABLE")
                    msgBox.setIcon(QtWidgets.QMessageBox.Critical)
                    details = "STATION IP LIST FROM CONFIG FILE (%d): " % len(tpm_ip_list)
                    for i in tpm_ip_list:
                        details += "\n%s" % i
                    details += "\n\nSUBRACK IP LIST OF TPM POWERED ON: (%d): " % len(tpm_ip_from_subrack)
                    for i in tpm_ip_from_subrack:
                        details += "\n%s" % i
                    msgBox.setDetailedText(details)
                    msgBox.exec_()
            else:
                msgBox = QtWidgets.QMessageBox()
                msgBox.setText("SKALAB: Please LOAD a configuration file first...")
                msgBox.setWindowTitle("Error!")
                msgBox.setIcon(QtWidgets.QMessageBox.Critical)
                msgBox.exec_()

    def apply_config_file(self,input_dict, output_dict):
        """ Recursively copy value from input_dict to output_dict"""
        for k, v in iteritems(input_dict):
            if type(v) is dict:
                self.apply_config_file(v, output_dict[k])
            elif k not in list(output_dict.keys()):
                logging.warning("{} not a valid configuration item. Skipping".format(k))
            else:
                output_dict[k] = v

    def populate_table_station(self):
        # TABLE STATION
        self.wg.qtable_station.clearSpans()
        #self.wg.qtable_station.setGeometry(QtCore.QRect(20, 140, 171, 31))
        self.wg.qtable_station.setObjectName("conf_qtable_station")
        self.wg.qtable_station.setColumnCount(1)
        self.wg.qtable_station.setRowCount(len(station.configuration['station'].keys()) - 1)
        n = 0
        for i in station.configuration['station'].keys():
            if not i == "bitfile":
                self.wg.qtable_station.setVerticalHeaderItem(n, QtWidgets.QTableWidgetItem(i.upper()))
                n = n + 1

        item = QtWidgets.QTableWidgetItem()
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        item.setFont(font)
        item.setText("SECTION: STATION")
        self.wg.qtable_station.setHorizontalHeaderItem(0, item)
        __sortingEnabled = self.wg.qtable_station.isSortingEnabled()
        self.wg.qtable_station.setSortingEnabled(False)
        n = 0
        for i in station.configuration['station'].keys():
            if not i == "bitfile":
                item = QtWidgets.QTableWidgetItem(str(station.configuration['station'][i]))
                item.setFlags(QtCore.Qt.ItemIsEnabled)
                self.wg.qtable_station.setItem(n, 0, item)
                n = n + 1
        self.wg.qtable_station.horizontalHeader().setStretchLastSection(True)
        self.wg.qtable_station.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.wg.qtable_station.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.wg.qtable_station.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)

        # TABLE TPM
        self.wg.qtable_tpm.clearSpans()
        #self.wg.qtable_tpm.setGeometry(QtCore.QRect(20, 180, 511, 141))
        self.wg.qtable_tpm.setObjectName("conf_qtable_tpm")
        self.wg.qtable_tpm.setColumnCount(2)
        self.wg.qtable_tpm.setRowCount(len(station.configuration['tiles']))
        for i in range(len(station.configuration['tiles'])):
            self.wg.qtable_tpm.setVerticalHeaderItem(i, QtWidgets.QTableWidgetItem("TPM-%02d" % (i + 1)))
        item = QtWidgets.QTableWidgetItem("IP ADDR")
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        item.setFont(font)
        item.setTextAlignment(QtCore.Qt.AlignCenter)
        self.wg.qtable_tpm.setHorizontalHeaderItem(0, item)
        item = QtWidgets.QTableWidgetItem("DELAYS")
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        item.setFont(font)
        item.setTextAlignment(QtCore.Qt.AlignCenter)
        self.wg.qtable_tpm.setHorizontalHeaderItem(1, item)
        for n, i in enumerate(station.configuration['tiles']):
            item = QtWidgets.QTableWidgetItem(str(i))
            item.setTextAlignment(QtCore.Qt.AlignCenter)
            item.setFlags(QtCore.Qt.ItemIsEnabled)
            self.wg.qtable_tpm.setItem(n, 0, item)
        for n, i in enumerate(station.configuration['time_delays']):
            item = QtWidgets.QTableWidgetItem(str(i))
            item.setTextAlignment(QtCore.Qt.AlignCenter)
            item.setFlags(QtCore.Qt.ItemIsEnabled)
            self.wg.qtable_tpm.setItem(n, 1, item)
        self.wg.qtable_tpm.horizontalHeader().setStretchLastSection(True)
        self.wg.qtable_tpm.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.wg.qtable_tpm.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.wg.qtable_tpm.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)

        # TABLE NETWORK
        self.wg.qtable_network.clearSpans()
        #self.wg.qtable_network.setGeometry(QtCore.QRect(600, 230, 511, 481))
        self.wg.qtable_network.setObjectName("conf_qtable_network")
        self.wg.qtable_network.setColumnCount(1)

        total_rows = len(station.configuration['network'].keys()) * 2 - 1
        for i in station.configuration['network'].keys():
            total_rows += len(station.configuration['network'][i])
        self.wg.qtable_network.setRowCount(total_rows)
        item = QtWidgets.QTableWidgetItem("SECTION: NETWORK")
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        item.setFont(font)
        item.setTextAlignment(QtCore.Qt.AlignCenter)
        item.setFlags(QtCore.Qt.ItemIsEnabled)
        self.wg.qtable_network.setHorizontalHeaderItem(0, item)
        n = 0
        for i in station.configuration['network'].keys():
            if n:
                item = QtWidgets.QTableWidgetItem(" ")
                item.setTextAlignment(QtCore.Qt.AlignCenter)
                item.setFlags(QtCore.Qt.ItemIsEnabled)
                self.wg.qtable_network.setVerticalHeaderItem(n, item)
                item = QtWidgets.QTableWidgetItem(" ")
                item.setTextAlignment(QtCore.Qt.AlignCenter)
                item.setFlags(QtCore.Qt.ItemIsEnabled)
                self.wg.qtable_network.setItem(n, 0, item)
                n = n + 1
            self.wg.qtable_network.setVerticalHeaderItem(n, QtWidgets.QTableWidgetItem(str(i).upper()))
            item = QtWidgets.QTableWidgetItem(" ")
            item.setFlags(QtCore.Qt.ItemIsEnabled)
            self.wg.qtable_network.setItem(n, 0, item)
            n = n + 1
            for k in sorted(station.configuration['network'][i].keys()):
                self.wg.qtable_network.setVerticalHeaderItem(n, QtWidgets.QTableWidgetItem(str(k).upper()))
                if "MAC" in str(k).upper() and not str(station.configuration['network'][i][k]) == "None":
                    item = QtWidgets.QTableWidgetItem(hex(station.configuration['network'][i][k]).upper())
                else:
                    item = QtWidgets.QTableWidgetItem(str(station.configuration['network'][i][k]))
                item.setTextAlignment(QtCore.Qt.AlignLeft)
                item.setFlags(QtCore.Qt.ItemIsEnabled)
                self.wg.qtable_network.setItem(n, 0, item)
                n = n + 1
        self.wg.qtable_network.horizontalHeader().setStretchLastSection(True)
        self.wg.qtable_network.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.wg.qtable_network.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.wg.qtable_network.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)


