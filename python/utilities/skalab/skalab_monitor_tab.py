import gc
import logging
import socket
import numpy as np

from pyaavs import station
from skalab_base import SkalabBase
from PyQt5 import QtWidgets, uic, QtCore, QtGui
from time import sleep
from pyfabil import TPMGeneric
from future.utils import iteritems
from pyfabil.base.definitions import LibraryError, BoardError, PluginError, InstrumentError
#from skalab_monitor import MonitorSubrack


def populateWarningAlarmTable(true_table, warning, alarm):
        true_table.setEditTriggers(QtWidgets.QTableWidget.AllEditTriggers)
        row = len(alarm.keys())
        item = QtWidgets.QTableWidgetItem()
        item.setFlags(item.flags() ^ QtCore.Qt.ItemIsEditable)
        for i in range(row):
            attr = list(alarm)[i]
            true_table.setRowCount(row)
            row_name = QtWidgets.QTableWidgetItem(list(warning.keys())[i])
            true_table.setVerticalHeaderItem(i, row_name)
            true_table.setItem(i , 0, QtWidgets.QTableWidgetItem(str(warning[attr][0])))
            true_table.setItem(i , 1, QtWidgets.QTableWidgetItem(str(warning[attr][1])))
            true_table.setItem(i , 2, QtWidgets.QTableWidgetItem(str(alarm[attr][0]))  )
            true_table.setItem(i , 3, QtWidgets.QTableWidgetItem(str(alarm[attr][1])) )
        true_table.setEditTriggers(QtWidgets.QTableWidget.NoEditTriggers)

class TileInitialization(SkalabBase):

    signal_station_init = QtCore.pyqtSignal()

    def __init__(self, profile, swpath="") -> None:
        super(TileInitialization, self).__init__(App="monitor", Profile=profile, Path=swpath, parent=self.wgProBox)
        self.config_file = self.profile['Init']['station_file']
        self.wg.qline_configfile.setText(self.config_file)
        if 'Extras' in self.profile.keys():
            if 'text_editor' in self.profile['Extras'].keys():
                self.text_editor = self.profile['Extras']['text_editor']
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

    def do_station_init(self):
        station.configuration['station']['initialise'] = True
        station.configuration['station']['program'] = True
        try:
            self.tpm_station = station.Station(station.configuration)
            self.wg.qbutton_station_init.setEnabled(False)
            self.tpm_station.connect()
            station.configuration['station']['initialise'] = False
            station.configuration['station']['program'] = False
            if self.tpm_station.properly_formed_station:
                self.wg.qbutton_station_init.setStyleSheet("background-color: rgb(78, 154, 6);")
                for k in self.tpm_slot_ip.keys():
                    self.tpm_initialized[k-1] = True
                self.wait_check_tpm.set()
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
                # Create station
                station.load_configuration_file(self.config_file)
                # Check wether the TPM are ON or OFF
                station_on = True
                tpm_ip_list = list(station.configuration['tiles'])
                tpm_ip_from_subrack = MonitorSubrack.getTiles(self)
                if tpm_ip_from_subrack:
                    tpm_ip_from_subrack_short = [x for x in tpm_ip_from_subrack if not x == '0']
                    if not len(tpm_ip_list) == len(tpm_ip_from_subrack_short):
                        msgBox = QtWidgets.QMessageBox()
                        message = "STATION\nOne or more TPMs forming the station are OFF\nPlease check the power!"
                        msgBox.setText(message)
                        msgBox.setWindowTitle("ERROR: TPM POWERED OFF")
                        msgBox.setIcon(QtWidgets.QMessageBox.Critical)
                        details = "STATION IP LIST FROM CONFIG FILE (%d): " % len(tpm_ip_list)
                        for i in tpm_ip_list:
                            details += "\n%s" % i
                        details += "\n\nSUBRACK IP LIST OF TPM POWERED ON: (%d): " % len(tpm_ip_from_subrack_short)
                        for i in tpm_ip_from_subrack_short:
                            details += "\n%s" % i
                        msgBox.setDetailedText(details)
                        msgBox.exec_()
                        self.logger.info(self.wgSubrack.telemetry)
                        return
                    else:
                        if not np.array_equal(tpm_ip_list, tpm_ip_from_subrack_short):
                            msgBox = QtWidgets.QMessageBox()
                            message = "STATION\nIPs provided by the Subrack are different from what defined in the " \
                                    "config file.\nINIT will use the new assigned IPs."
                            msgBox.setText(message)
                            msgBox.setWindowTitle("WARNING: IP mismatch")
                            msgBox.setIcon(QtWidgets.QMessageBox.Warning)
                            details = "STATION IP LIST FROM CONFIG FILE (%d): " % len(tpm_ip_list)
                            for i in tpm_ip_list:
                                details += "\n%s" % i
                            details += "\n\nSUBRACK IP LIST OF TPM POWERED ON: (%d): " % len(tpm_ip_from_subrack_short)
                            for i in tpm_ip_from_subrack_short:
                                details += "\n%s" % i
                            msgBox.setDetailedText(details)
                            msgBox.exec_()
                            station.configuration['tiles'] = list(tpm_ip_from_subrack_short)
                            self.wgLive.setupNewTilesIPs(list(tpm_ip_from_subrack))
                for tpm_ip in station.configuration['tiles']:
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


