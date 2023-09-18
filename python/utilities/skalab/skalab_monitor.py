"Set screen Resolution 1920 x 1080"
import os.path
import sys
import gc
import copy
import h5py
import numpy as np
import logging
import yaml
import datetime
import importlib.resources

import skalab_monitor_tab
from pyaavs.tile_wrapper import Tile
from pyaavs import station
from PyQt5 import QtWidgets, uic, QtCore
from PyQt5.QtGui import QColor
from hardware_client import WebHardwareClient
from skalab_monitor_tab import TileInitialization
from skalab_log import SkalabLog
from skalab_utils import *
from threading import Thread, Event, Lock
from time import sleep
from pathlib import Path

default_app_dir = str(Path.home()) + "/.skalab/"
default_profile = "Default"
profile_filename = "monitor.ini"

standard_subrack_attribute = {
                "tpm_supply_fault": [None]*8,
                "tpm_on_off": [None]*8
                }


def populateTable(frame, attributes,top):
    "Create Subrack table"
    qtable = []
    sub_attr = []
    size_a = len(attributes)
    for j in range(size_a):
        qtable.append(getattr(frame, f"table{top[j]}"))
        sub_attr.append(list(list(attributes[j].values())[0].keys()))
        qtable[j].setRowCount(len(sub_attr[j]))
        qtable[j].setColumnCount(2)
        qtable[j].setVerticalHeaderLabels(sub_attr[j])  
        qtable[j].setHorizontalHeaderLabels(("Value", "Warning/Alarm")) 
    return qtable, sub_attr

    # qtable.setRowCount(8)
    # qtable.setColumnCount(len(attribute))
    # for key in attribute.keys():
    #         horHeaders.append(key)
    # qtable.setHorizontalHeaderLabels(horHeaders)
    # qtable.horizontalHeader().setDefaultSectionSize(100)
    # "Fill table"
    # j = 0
    # for k in attribute:
    #     for v in range(0,16,2):
    #         layout = 0
    #         layout=QtWidgets.QVBoxLayout()
    #         attribute[k][v] = QtWidgets.QLineEdit(qtable)
    #         attribute[k][v+1]= QtWidgets.QLineEdit(qtable)
    #         layout.addWidget(attribute[k][v])
    #         layout.addWidget(attribute[k][v+1])
    #         cellWidget = QtWidgets.QWidget()
    #         cellWidget.setLayout(layout)
    #         qtable.setCellWidget(int(v/2),j,cellWidget)
    #     j+=1
    # a=1
    # return

# def populateSubrack(self,wg, attribute):
#     j=0
#     size_x = 120
#     size_y = 60
#     for k in attribute:
#         for v in range(0,len(attribute[k]),2):
#             if (k == "subrack_fan_speeds_percent"):
#                 subrack_attribute[k][v] = wg.grid_sub_fan.addWidget(QtWidgets.QLineEdit(wg.frame_subrack),3,v)
#                 subrack_attribute[k][v+1] = wg.grid_sub_fan.addWidget(QtWidgets.QLineEdit(wg.frame_subrack),4,v)
#                 j-=0.25
#                 continue
#             if (k == "subrack_fan_speeds"):
#                 subrack_attribute[k][v] = wg.grid_sub_fan.addWidget(QtWidgets.QLineEdit(wg.frame_subrack),1,v)
#                 subrack_attribute[k][v+1] = wg.grid_sub_fan.addWidget(QtWidgets.QLineEdit(wg.frame_subrack),2,v) 
#                 j-=0.25
#                 continue   
#             subrack_attribute[k][v] = QtWidgets.QLineEdit(wg.frame_subrack)
#             subrack_attribute[k][v+1]= QtWidgets.QLineEdit(wg.frame_subrack)
#             subrack_attribute[k][v].setGeometry(QtCore.QRect(  size_x+45*v, 10 +  20+(size_y*(j)),  70,19))
#             subrack_attribute[k][v+1].setGeometry(QtCore.QRect(size_x+45*v, 30 +  20+(size_y*(j)),  70,19))
#         j+=1


def populateSlots(grid):
    qbutton_tpm = []
    for i in range(8):
        qbutton_tpm.append(QtWidgets.QPushButton("TPM #%d" % (i + 1)))
        grid.addWidget(qbutton_tpm[i],int(i/4), int(i/4)*(-4)+i)
        qbutton_tpm[i].setGeometry(QtCore.QRect(10, 80 + (66 * (i)), 80, 30))
        qbutton_tpm[i].setObjectName("qbutton_tpm_%d" % i)
        #qbutton_tpm[i].setText("TPM #%d" % (i + 1))
        qbutton_tpm[i].setEnabled(False)
    return qbutton_tpm          

class Monitor(TileInitialization):

    signal_update_tpm_attribute = QtCore.pyqtSignal(dict,int)
    signal_update_log = QtCore.pyqtSignal(str,str)
    with open(r'tpm_monitoring_min_max.yaml') as file:
        MIN_MAX_MONITORING_POINTS = (
            yaml.load(file, Loader=yaml.Loader)["tpm_monitoring_points"] or {})
    res  = merge_dicts(MIN_MAX_MONITORING_POINTS, TILE_MONITORING_POINTS)
   
    def __init__(self, config="", uiFile="", profile="", size=[1170, 919], swpath=""):
        """ Initialise main window """
        # Load window file
        self.wg = uic.loadUi(uiFile)
        
        self.wgProBox = QtWidgets.QWidget(self.wg.qtab_conf)
        self.wgProBox.setGeometry(QtCore.QRect(1, 1, 800, 860))
        self.wgProBox.setVisible(True)
        self.wgProBox.show()
        super(Monitor, self).__init__(profile, swpath)
        self.logger = SkalabLog(parent=self.wg.qt_log, logname=__name__, profile=self.profile)
        self.setCentralWidget(self.wg)
        self.loadEventsMonitor()
        # Set variable
        self.from_subrack = {}
        self.tpm_interval = self.profile['Monitor']['tpm_query_interval']
        self.tlm_hdf_monitor = None
        self.tpm_initialized = [False] * 8
        # Populate table
        #populateSubrack(self, self.wg, subrack_attribute)
        self.populate_table_profile()
        self.subrack_led = Led(self.wg.overview_frame)
        self.wg.grid_led.addWidget(self.subrack_led)
        self.subrack_led.setObjectName("qled_warn_alar")
        self.qbutton_tpm = populateSlots(self.wg.grid_tpm)
        self.populateTileInstance()
        self.top_attr = list(self.profile['Monitor']['top_level_attributes'].split(","))
        self.text_editor = ""
        if 'Extras' in self.profile.keys():
            if 'text_editor' in self.profile['Extras'].keys():
                self.text_editor = self.profile['Extras']['text_editor']
        
        #self.tile_table_attr = copy.deepcopy(self.tpm_alarm)
        # for i in self.tile_table_attr.keys():
        #     self.tile_table_attr[i] = [None] * 16            
        # self.alarm = dict(self.tile_table_attr, **subrack_attribute)
        # for k in self.alarm.keys():
        #     self.alarm[k] = [False]*8
            #load_tpm_1_6_lookup
        #populateTable(self.wg.qtable_tile, self.tile_table_attr)
        
        # Start thread
        self.show()
        self._lock_led = Lock()
        self._lock_tab1 = Lock()
        self._lock_tab2 = Lock()
        self.check_tpm_tm = Thread(name= "TPM telemetry", target=self.monitoringTpm, daemon=True)
        self._tpm_lock = Lock()
        self.wait_check_tpm = Event()
        #self.check_tpm_tm.start()

    def writeLog(self,message,priority):
        if priority == "info":
            self.logger.info(message)
        elif priority == "warning":
            self.logger.warning(message)
        else:
            self.logger.error(message)
    
    def loadEventsMonitor(self):
        self.wg.qbutton_clear_subrack.clicked.connect(lambda: self.clearValues())
        self.wg.qbutton_clear_tpm.clicked.connect(lambda: self.clearValues())
        self.wgProfile.qbutton_load.clicked.connect(lambda: self.loadNewTable())
        self.wg.check_subrack_savedata.toggled.connect(self.setupSubrackHdf5) # TODO ADD toggled

    def loadNewTable(self):
        self.loadWarningAlarmValues()
    
    def clearValues(self):
        with (self._lock_led and self._lock_tab1 and self._lock_tab2):
            self.subrack_led.Colour = Led.Grey
            self.subrack_led.m_value = False
            for table in self.subrack_table:
                table.clearContents()
            
            # for i in range(16):
            #     self.qled_alert[int(i/2)].Colour = Led.Grey
            #     self.qled_alert[int(i/2)].value = False  
            #     for attr in self.alarm:
            #         self.alarm[attr][int(i/2)] = False
            #         if attr in self.tile_table_attr:
            #             self.tile_table_attr[attr][i].setText(str(""))
            #             self.tile_table_attr[attr][i].setStyleSheet("color: black; background:white")  
                         
    def populateTileInstance(self):
        keys_to_be_removed = []
        self.tpm_on_off = [False] * 8
        self.tpm_active = [None] * 8
        #self.tpm_slot_ip = list(station.configuration['tiles'])
        # Comparing ip to assign slot number to ip: file .ini and .yaml
        self.tpm_slot_ip = eval(self.profile['Tpm']['tiles_slot_ip'])
        self.tpm_ip_check= list(station.configuration['tiles'])
        for k, j in self.tpm_slot_ip.items():
            if j in self.tpm_ip_check:
                pass
            else:
                keys_to_be_removed.append(k)
        for a in keys_to_be_removed:
            del self.tpm_slot_ip[a]
        self.bitfile = station.configuration['station']['bitfile']

    def loadTopLevelAttributes(self):
        # self.tpm_warning = self.profile['TPM Warning']
        # self.warning = dict(self.tpm_warning, **self.subrack_warning)
        # self.subrack_alarm = self.profile['Subrack Alarm']
        # self.tpm_alarm = self.profile['TPM Alarm']
        # self.alarm_values = dict(self.tpm_alarm, **self.subrack_alarm)
        # for attr in self.warning:
        #     self.warning[attr] = eval(self.warning[attr])
        #     self.alarm_values[attr] = eval(self.alarm_values[attr])
        #     if self.warning[attr][0] == None: self.warning[attr][0] = -float('inf')
        #     if self.alarm_values[attr][0]   == None: self.alarm_values[attr][0]   = -float('inf')
        #     if self.warning[attr][1] == None: self.warning[attr][1] =  float('inf')
        #     if self.alarm_values[attr][1]   == None: self.alarm_values[attr][1]   =  float('inf')   
        # skalab_monitor_tab.populateWarningAlarmTable(self.wg.true_table, self.warning, self.alarm_values)
        pass

    def tpmStatusChanged(self):
        # self.wait_check_tpm.clear()
        # with self._tpm_lock:
        #     for k in range(8):
        #         if self.tpm_on_off[k] and not self.tpm_active[k]:
        #             self.tpm_active[k] = Tile(self.tpm_slot_ip[k+1], self.cpld_port, self.lmc_ip, self.dst_port)
        #             self.tpm_active[k].program_fpgas(self.bitfile)
        #             self.tpm_active[k].connect()
        #         elif not self.tpm_on_off[k] and self.tpm_active[k]:
        #             self.tpm_active[k] = None
        # if any(self.tpm_initialized):
        #     self.wait_check_tpm.set()
        pass
            

    def monitoringTpm(self):
        while True:
            self.wait_check_tpm.wait()
            # Get tm from tpm
            with self._tpm_lock:
                for i in range(0,15,2):
                    index = int(i/2)
                    if self.tpm_on_off[index]:
                        try:
                            L = list(self.tpm_active[index].get_health_status().values())
                            tpm_monitoring_points = {}
                            for d in L:
                                tpm_monitoring_points.update(d)
                        except:
                            self.signal_update_log.emit(f"Failed to get TPM Telemetry. Are you turning off TPM#{index+1}?","warning")
                            #self.logger.warning(f"Failed to get TPM Telemetry. Are you turning off TPM#{index+1}?")
                            tpm_monitoring_points = "ERROR"
                            continue
                        self.signal_update_tpm_attribute.emit(tpm_monitoring_points,i)
            #if self.wg.check_savedata.isChecked(): self.saveTlm(tpm_monitoring_points)
            sleep(float(self.interval_monitor))    


    def writeTpmAttribute(self,tpm_tmp,i):
        for attr in self.tile_table_attr:
            value = tpm_tmp[attr]
            self.tile_table_attr[attr][i].setStyleSheet("color: black; background:white")
            self.tile_table_attr[attr][i].setText(str(value))
            self.tile_table_attr[attr][i].setAlignment(QtCore.Qt.AlignCenter)
            with self._lock_tab1:
                if not(type(value)==str or type(value)==str) and not(self.alarm_values[attr][0] <= value <= self.alarm_values[attr][1]):
                    # # tile_table_attr[attr][i].setStyleSheet("color: white; background:red")  
                    # segmentation error or free() pointer error
                    self.tile_table_attr[attr][i+1].setText(str(value))
                    self.tile_table_attr[attr][i+1].setStyleSheet("color: white; background:red")
                    self.tile_table_attr[attr][i+1].setAlignment(QtCore.Qt.AlignCenter)
                    self.alarm[attr][int(i/2)] = True
                    self.logger.error(f"ERROR: {attr} parameter is out of range!")
                    with self._lock_led:
                        self.qled_alert[int(i/2)].Colour = Led.Red
                        self.qled_alert[int(i/2)].value = True
                elif not(type(value)==str or type(value)==str) and not(self.warning[attr][0] <= value <= self.warning[attr][1]):
                    if not self.alarm[attr][int(i/2)]:
                        self.tile_table_attr[attr][i+1].setText(str(value))
                        self.tile_table_attr[attr][i+1].setStyleSheet("color: white; background:orange")
                        self.tile_table_attr[attr][i+1].setAlignment(QtCore.Qt.AlignCenter)
                        self.logger.warning(f"WARNING: {attr} parameter is near the out of range threshold!")
                        if self.qled_alert[int(i/2)].Colour==4:
                            with self._lock_led:
                                self.qled_alert[int(i/2)].Colour=Led.Orange
                                self.qled_alert[int(i/2)].value = True        
                 

class MonitorSubrack(Monitor):
    """ Main UI Window class """
    # Signal for Slots
    signalTlm = QtCore.pyqtSignal()
    signal_to_monitor = QtCore.pyqtSignal()
    signal_to_monitor_for_tpm = QtCore.pyqtSignal()

    def __init__(self, ip=None, port=None, uiFile="", profile="", size=[1190, 936], swpath=""):
        """ Initialise main window """

        super(MonitorSubrack, self).__init__(uiFile="Gui/skalab_monitor.ui", size=[1190, 936], profile=opt.profile, swpath=default_app_dir)   
        self.interval_monitor = self.profile['Monitor']['tpm_query_interval']
        self.subrack_interval = self.profile['Monitor']['subrack_query_interval']
        self.warning_factor = eval(self.profile['Warning Factor']['subrack_warning_parameter'])
        self.tlm_keys = []
        self.tpm_status_info = {} 
        self.last_telemetry = {"tpm_supply_fault":[None] *8,"tpm_present":[None] *8,"tpm_on_off":[None] *8}
        self.query_once = []
        self.query_deny = []
        self.query_tiles = []
        self.connected = False
        self.reload(ip=ip, port=port)
        self.tlm_file = ""
        self.tlm_hdf = None
        self.wg.subrackbar.setStyleSheet("QProgressBar"
                          "{"
                            "background-color : rgba(255, 0, 0, 255);"
                            "border : 1px"
                          "}"
  
                          "QProgressBar::chunk"
                          "{"
                            "background : rgba(0, 255, 0, 255);"
                          "}"
                          )
        self.wg.subrackbar.hide()

        self.client = None
        self.data_charts = {}

        self.loadEventsSubrack()
        self.show()
        self.skipThreadPause = False
        self.subrackTlm = Thread(name="Subrack Telemetry", target=self.readSubrackTlm, daemon=True)
        self.wait_check_subrack = Event()
        self._subrack_lock = Lock()
        self._subrack_lock_threshold = Lock()
        self.subrackTlm.start()

    def loadEventsSubrack(self):
        self.wg.subrack_button.clicked.connect(lambda: self.connect())
        self.wg.qbutton_subrack_edit.clicked.connect(lambda: editThresholds(self.wg,self.text_editor))
        self.wg.qbutton_subrack_threshold.clicked.connect(lambda: self.loadThreshold())
        for n, t in enumerate(self.qbutton_tpm):
            t.clicked.connect(lambda state, g=n: self.cmdSwitchTpm(g))


    def loadThreshold(self):
        fd = QtWidgets.QFileDialog()
        fd.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, True)
        options = fd.options()
        self.filename = fd.getOpenFileName(self, caption="Select a Subrack Alarm Thresholds file...",
                                              directory="./", options=options)[0]
        if not(self.filename == ''):
            self.wg.qline_subrack_threshold.setText(self.filename)
            with self._subrack_lock_threshold:
                if self.connected:
                    [self.alarm, self.warning] = getThreshold(self.wg,self.tlm_keys,self.top_attr,self.warning_factor)
        return


    def reload(self, ip=None, port=None):
        if ip is not None:
            self.ip = ip
        else:
            self.ip = str(self.profile['Subrack']['ip'])
        if port is not None:
            self.port = port
        else:
            self.port = int(self.profile['Subrack']['port'])
        self.wg.qline_ip.setText("%s (%d)" % (self.ip, self.port))
        if 'Query' in self.profile.keys():
            if 'once' in self.profile['Query'].keys():
                self.query_once = list(self.profile['Query']['once'].split(","))
            if 'deny' in self.profile['Query'].keys():
                self.query_deny = list(self.profile['Query']['deny'].split(","))
            if 'deny' in self.profile['Query'].keys():
                self.query_tiles = list(self.profile['Query']['tiles'].split(","))

    
    def cmdSwitchTpm(self, slot):
        self.wait_check_subrack.clear()
        self.skipThreadPause = True
        with self._subrack_lock:
            if self.connected:
                if self.tpm_status_info["tpm_on_off"][slot]:
                    self.client.execute_command(command="turn_off_tpm", parameters="%d" % (int(slot) + 1))
                    self.logger.info("Turn OFF TPM-%02d" % (int(slot) + 1))
                else:
                    self.client.execute_command(command="turn_on_tpm", parameters="%d" % (int(slot) + 1))
                    self.logger.info("Turn ON TPM-%02d" % (int(slot) + 1)) 
            sleep(2.0) # Sleep required to wait for the turn_off/on_tpm command to complete
        self.wait_check_subrack.set()

    
    def connect(self):
        self.tlm_keys = []
        if not self.wg.qline_ip.text() == "":
            if not self.connected:
                self.wg.subrackbar.show()
                self.logger.info("Connecting to Subrack %s:%d..." % (self.ip, int(self.port)))
                self.client = WebHardwareClient(self.ip, self.port)
                self.wg.subrackbar.setValue(20)
                if self.client.connect():
                    self.logger.info("Successfully connected")
                    self.logger.info("Querying list of Subrack API attributes...")
                    self.subrack_dictionary = self.client.execute_command(command="get_health_dictionary")["retvalue"]
                    self.wg.subrackbar.setValue(30)
                    del self.subrack_dictionary['iso_datetime']
                    for i in range(len(self.top_attr)):
                        #diz = self.client.execute_command(command="get_health_dictionary",parameters=self.top_attr[i])["retvalue"]
                        #del diz['iso_datetime']
                        if self.top_attr[i] in self.subrack_dictionary.keys():
                            diz = {self.top_attr[i]: self.subrack_dictionary[self.top_attr[i]]}
                        else:
                            res = {}
                            for key, value in self.subrack_dictionary.items():
                                if isinstance(value, dict):
                                    for subkey, subvalue in value.items():
                                        if isinstance(subvalue, dict) and self.top_attr[i] in subvalue:
                                            res[subkey] = {
                                                'unit': subvalue[self.top_attr[i]]['unit'],
                                                'exp_value': subvalue[self.top_attr[i]]['exp_value']
                                            }  
                            diz = {self.top_attr[i] : res}
                            
                        self.tlm_keys.append(diz)
                    self.logger.info("Populate monitoring table...")
                    [self.subrack_table, self.sub_attribute] = populateTable(self.wg,self.tlm_keys,self.top_attr)
                    self.wg.subrackbar.setValue(40)
                    self.wg.qbutton_clear_subrack.setEnabled(True)
                    for tlmk in self.query_once:
                        data = self.client.get_attribute(tlmk)
                        if data["status"] == "OK":
                            self.tpm_status_info[tlmk] = data["value"]
                        else:
                            self.tpm_status_info[tlmk] = data["info"]
                    if 'api_version' in self.tpm_status_info.keys():
                        self.logger.info("Subrack API version: " + self.tpm_status_info['api_version'])
                    else:
                        self.logger.warning("The Subrack is running with a very old API version!")
                    self.wg.subrackbar.setValue(60)
                    [item.setEnabled(True) for item in self.qbutton_tpm]
                    self.connected = True
                    self.tlm_hdf = self.setupSubrackHdf5()
                    [self.alarm, self.warning] = getThreshold(self.wg, self.tlm_keys,self.top_attr,self.warning_factor)
                    self.wg.subrackbar.setValue(90)
                    for tlmk in standard_subrack_attribute: 
                        data = self.client.get_attribute(tlmk)
                        if data["status"] == "OK":
                            self.tpm_status_info[tlmk] = data["value"]
                        else:
                            self.tpm_status_info[tlmk] = data["info"]
                    self.wg.subrackbar.setValue(100)
                    self.wg.subrack_button.setStyleSheet("background-color: rgb(78, 154, 6);")
                    self.wg.subrack_button.setText("ONLINE")
                    self.wg.subrack_button.setStyleSheet("background-color: rgb(78, 154, 6);")
                    with self._subrack_lock:
                        self.updateTpmStatus()
                    self.wait_check_subrack.set()
                    self.wg.subrackbar.hide()
                else:
                    self.logger.error("Unable to connect to the Subrack server %s:%d" % (self.ip, int(self.port)))
                    self.wg.subrack_button.setStyleSheet("background-color: rgb(204, 0, 0);")
                    self.wg.subrack_button.setStyleSheet("background-color: rgb(204, 0, 0);")
                    self.wg.subrack_button.setText("OFFLINE")
                    [item.setEnabled(False) for item in self.qbutton_tpm]
                    self.client = None
                    self.connected = False

            else:
                self.logger.info("Disconneting from Subrack %s:%d..." % (self.ip, int(self.port)))
                self.wait_check_tpm.clear()
                self.wait_check_subrack.clear()
                self.connected = False
                self.wg.subrack_button.setStyleSheet("background-color: rgb(204, 0, 0);")
                self.wg.subrack_button.setText("OFFLINE")
                #[item.setEnabled(False) for item in self.qbutton_tpm]
                self.client.disconnect()
                del self.client
                gc.collect()
                if (type(self.tlm_hdf) is not None) or (type(self.tlm_hdf_monitor) is not None):
                    try:
                        self.tlm_hdf.close()
                        self.tlm_hdf_monitor.close()
                    except:
                        pass
        else:
            self.wg.qlabel_connection.setText("Missing IP!")
            self.wait_check_tpm.clear()
            self.wait_check_subrack.clear()

    
    def getTelemetry(self):
        tkey = ""
        telem = {}
        data = self.client.execute_command(command="get_health_status")
        if data["status"] == "OK":
            self.from_subrack =  data['retvalue']
            if self.wg.check_subrack_savedata.isChecked(): self.saveSubrackData(self.from_subrack)
        else:
            self.logger.warning("Subrack Data NOT AVAILABLE...")
            self.from_subrack =  data['retvalue']
        try:
            for tlmk in standard_subrack_attribute:
                tkey = tlmk
                if not tlmk in self.query_deny:
                    if self.connected:
                        data = self.client.get_attribute(tlmk)
                        if data["status"] == "OK":
                            telem[tlmk] = data["value"]
                            self.tpm_status_info[tlmk] = telem[tlmk]
                        else:
                            self.tpm_status_info[tlmk] = "NOT AVAILABLE"
        except:
            self.signal_update_log.emit("Error reading Telemetry [attribute: %s], skipping..." % tkey,"error")
        
        return
    
    
    def getTiles(self):
        try:
            for tlmk in self.query_tiles:
                data = self.client.get_attribute(tlmk)
                if data["status"] == "OK":
                    self.tpm_status_info[tlmk] = data["value"]
                else:
                    self.tpm_status_info[tlmk] = []
            return self.tpm_status_info['tpm_ips']
        except:
            return []

    
    def readSubrackTlm(self):
        while True:
            self.wait_check_subrack.wait()
            with self._subrack_lock:
                if self.connected:
                    try:
                        self.getTelemetry()
                    except:
                        self.signal_update_log.emit("Failed to get Subrack Telemetry!","warning")
                        pass
                    self.signalTlm.emit()
                    self.signal_to_monitor.emit()
                    cycle = 0.0
                    while cycle < (float(self.subrack_interval)) and not self.skipThreadPause:
                        sleep(0.1)
                        cycle = cycle + 0.1
                    self.skipThreadPause = False
            sleep(0.5)  

    
    def readwriteSubrackAttribute(self):
        #for attr in self.from_subrack:
        diz = self.from_subrack
        for index_table in range(len(self.top_attr)):
            table = self.subrack_table[index_table]
            if not(self.top_attr[index_table] in diz.keys()):
                res = {}
                for key, value in diz.items():
                    if isinstance(value, dict):
                        for subkey, subvalue in value.items():
                            if isinstance(subvalue, dict) and self.top_attr[index_table] in subvalue:
                                res[subkey] = subvalue[self.top_attr[index_table]]
                                diz[key][subkey].pop(self.top_attr[index_table])
                attribute_data = res
                with self._subrack_lock_threshold:
                    filtered_alarm =  self.alarm[index_table][self.top_attr[index_table]]
                    filtered_warning = self.warning[index_table][self.top_attr[index_table]]
            else:
                if (list(diz[self.top_attr[index_table]]) == self.sub_attribute[index_table]):
                    attribute_data = diz[self.top_attr[index_table]]
                    with self._subrack_lock_threshold:
                        filtered_alarm =  self.alarm[index_table][self.top_attr[index_table]]
                        filtered_warning = self.warning[index_table][self.top_attr[index_table]]
                    diz.pop(self.top_attr[index_table])
                else:
                    break
            #self.tlm_keys.append(diz)
            attrs = list(attribute_data.keys())
            values = list(attribute_data.values())
            for i in range(len(attribute_data)):
                value = values[i]
                attr = attrs[i]
                table.setItem(i,0, QtWidgets.QTableWidgetItem(str(value)))
                item = table.item(i, 0)
                item.setTextAlignment(QtCore.Qt.AlignCenter)
                # TODO: Add bool comparison
                if not(type(value)==str or type(value)==bool or value==None or filtered_alarm[attr][0]==None):
                    if not(filtered_alarm[attr][0] < value < filtered_alarm[attr][1]): 
                        with self._lock_tab2:
                            table.setItem(i,1, QtWidgets.QTableWidgetItem(str(value)))
                            item = table.item(i, 1)
                            item.setTextAlignment(QtCore.Qt.AlignCenter)
                            item.setForeground(QColor("white"))
                            item.setBackground(QColor("#ff0000")) # red
                            self.logger.error(f"ERROR: {attr} parameter is out of range!")
                            #self.alarm[attr][int(ind/2)] = True
                            # Change the color only if it not 1=red
                            if not(self.subrack_led.Colour==1):
                                with self._lock_led:
                                    self.subrack_led.Colour = Led.Red
                                    self.subrack_led.value = True
                    elif not(filtered_warning[attr][0] < value < filtered_warning[attr][1]) and not(item.background().color().name() == '#ff0000'):
                        with self._lock_tab2:
                            table.setItem(i,1, QtWidgets.QTableWidgetItem(str(value)))
                            item = table.item(i, 1)
                            item.setTextAlignment(QtCore.Qt.AlignCenter)
                            item.setForeground(QColor("white"))
                            item.setBackground(QColor("#ff8000")) #orange
                            self.logger.warning(f"WARNING: {attr} parameter is near the out of range threshold!")
                            # Change the color only if it is 4=Grey
                            if self.subrack_led.Colour==4: 
                                with self._lock_led:
                                    self.subrack_led.Colour=Led.Orange
                                    self.subrack_led.value = True
            # except:
            #     self.signal_update_log.emit("Error reading Telemetry [attribute: %s], skipping..." % tkey,"error")
            #     #self.logger.error("Error reading Telemetry [attribute: %s], skipping..." % tkey)
            #     monitor_tlm[tlmk] = f"ERROR{tkey}"
            #     self.from_subrack =  monitor_tlm       

    
    def updateTpmStatus(self):
        # TPM status on QButtons
        if "tpm_supply_fault" in self.tpm_status_info.keys():
            for n, fault in enumerate(self.tpm_status_info["tpm_supply_fault"]):
                if fault:
                    self.qbutton_tpm[n].setStyleSheet(colors("yellow_on_black"))
                    self.tpm_on_off[n] = False
                else:
                    if "tpm_present" in self.tpm_status_info.keys():
                        if self.tpm_status_info["tpm_present"][n]:
                            self.qbutton_tpm[n].setStyleSheet(colors("black_on_red"))
                            self.tpm_on_off[n] = False
                        else:
                            self.qbutton_tpm[n].setStyleSheet(colors("black_on_grey"))
                            self.tpm_on_off[n] = False
                    if "tpm_on_off" in self.tpm_status_info.keys():
                        if self.tpm_status_info["tpm_on_off"][n]:
                            self.qbutton_tpm[n].setStyleSheet(colors("black_on_green"))
                            self.tpm_on_off[n] = True
            try:
                if (self.tpm_status_info["tpm_supply_fault"]!= self.last_telemetry["tpm_supply_fault"]) | (self.tpm_status_info["tpm_present"]!= self.last_telemetry["tpm_present"]) | (self.tpm_status_info["tpm_on_off"]!= self.last_telemetry["tpm_on_off"]):
                    self.signal_to_monitor_for_tpm.emit()
                    self.last_telemetry["tpm_supply_fault"] = self.tpm_status_info["tpm_supply_fault"]
                    self.last_telemetry["tpm_present"] = self.tpm_status_info["tpm_present"]
                    self.last_telemetry["tpm_on_off"] = self.tpm_status_info["tpm_on_off"]
                    
            except:
                pass
                #self.signal_to_monitor_for_tpm.emit()            

    
    def setupSubrackHdf5(self):
        if not(self.tlm_hdf_monitor):
            if not self.profile['Subrack']['subrack_data_path'] == "":
                fname = self.profile['Subrack']['subrack_data_path']
                if not fname[-1] == "/":
                    fname = fname + "/"
                    if  os.path.exists(str(Path.home()) + fname) != True:
                        os.makedirs(str(Path.home()) + fname)
                fname += datetime.datetime.strftime(datetime.datetime.utcnow(), "monitor_subrack_%Y-%m-%d_%H%M%S.h5")
                self.tlm_hdf_monitor = h5py.File(str(Path.home()) + fname, 'a')
                return self.tlm_hdf_monitor
            else:
                msgBox = QtWidgets.QMessageBox()
                msgBox.setText("Please Select a valid path to save the Monitor data and save it into the current profile")
                msgBox.setWindowTitle("Error!")
                msgBox.setIcon(QtWidgets.QMessageBox.Critical)
                msgBox.exec_()
                return None

    
    def saveSubrackData(self, subrack_tlm):
        datetime = subrack_tlm['iso_datetime']
        del subrack_tlm['iso_datetime']
        if self.tlm_hdf_monitor:
            try:
                    #self.tlm_hdf_monitor.create_dataset(datetime, data=str(subrack_tlm))
                dt = h5py.special_dtype(vlen=str) 
                feature_names = np.array(str(subrack_tlm), dtype=dt) 
                self.tlm_hdf_monitor.create_dataset(datetime, data=feature_names)

            except:
                self.logger.error(f"WRITE SUBRACK TELEMETRY ERROR at {datetime}")
                # else:
                #     self.tlm_hdf_monitor[attr].resize((self.tlm_hdf_monitor[attr].shape[0] +
                #                                 np.asarray([self.tlm_hdf_monitor[attr]]).shape[0]), axis=0)
                #     self.tlm_hdf_monitor[attr][self.tlm_hdf_monitor[attr].shape[0]-1]=np.asarray([data_tile[attr]]) 

    def saveTlm(self,data_tile):
        if self.tlm_hdf_monitor:
            for attr in self.tile_table_attr:
                data_tile[attr][:] = [0.0 if type(x) is str else x for x in data_tile[attr]]
                if attr not in self.tlm_hdf_monitor:
                    try:
                        self.tlm_hdf_monitor.create_dataset(attr, data=np.asarray([data_tile[attr]]), chunks = True, maxshape =(None,None))
                    except:
                        self.logger.error("WRITE TLM ERROR in ", attr, "\nData: ", data_tile[attr])
                else:
                    self.tlm_hdf_monitor[attr].resize((self.tlm_hdf_monitor[attr].shape[0] +
                                                np.asarray([self.tlm_hdf_monitor[attr]]).shape[0]), axis=0)
                    self.tlm_hdf_monitor[attr][self.tlm_hdf_monitor[attr].shape[0]-1]=np.asarray([data_tile[attr]])                  

    
    def closeEvent(self, event):
        result = QtWidgets.QMessageBox.question(self,
                                                "Confirm Exit...",
                                                "Are you sure you want to exit ?",
                                                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        event.ignore()
        if result == QtWidgets.QMessageBox.Yes:
            event.accept()
            self.stopThreads = True
            self.logger.info("Stopping Threads")
            if type(self.tlm_hdf) is not None:
                try:
                    self.tlm_hdf.close()
                    self.tlm_hdf_monitor.close()
                except:
                    pass
        self.logger.logger.info("Stopping Threads")
        self.logger.stopLog()    
        sleep(1) 

if __name__ == "__main__":
    from optparse import OptionParser
    from sys import argv, stdout 

    parser = OptionParser(usage="usage: %station_subrack [options]")
    parser.add_option("--profile", action="store", dest="profile",
                      type="str", default="Default", help="Monitor Profile to load")
    parser.add_option("--ip", action="store", dest="ip",
                      type="str", default=None, help="Subrack IP address [default: None]")
    parser.add_option("--port", action="store", dest="port",
                      type="int", default=8081, help="Subrack WebServer Port [default: 8081]")
    parser.add_option("--interval", action="store", dest="interval",
                      type="int", default=5, help="Time interval (sec) between telemetry requests [default: 1]")
    parser.add_option("--nogui", action="store_true", dest="nogui",
                      default=False, help="Do not show GUI")
    parser.add_option("--single", action="store_true", dest="single",
                      default=False, help="Single Telemetry Request. If not provided, the script runs indefinitely")
    parser.add_option("--directory", action="store", dest="directory",
                      type="str", default="", help="Output Directory [Default: "", it means do not save data]")
    (opt, args) = parser.parse_args(argv[1:])

    monitor_logger = logging.getLogger(__name__)
    if not opt.nogui:
        app = QtWidgets.QApplication(sys.argv)
        window = MonitorSubrack(uiFile="Gui/skalab_monitor.ui", size=[1190, 936],
                                 profile=opt.profile,
                                 swpath=default_app_dir)
        window.setFixedSize(1350,950)
        window.dst_port = station.configuration['network']['lmc']['lmc_port']
        window.lmc_ip = station.configuration['network']['lmc']['lmc_ip']
        window.cpld_port = station.configuration['network']['lmc']['tpm_cpld_port']
        window.signalTlm.connect(window.updateTpmStatus)
        window.signal_to_monitor.connect(window.readwriteSubrackAttribute)
        window.signal_to_monitor_for_tpm.connect(window.tpmStatusChanged)
        window.signal_update_tpm_attribute.connect(window.writeTpmAttribute)
        window.signal_update_log.connect(window.writeLog)
        window.signal_station_init.connect(window.do_station_init)
        sys.exit(app.exec_())
    else:
        profile = []
        fullpath = default_app_dir + opt.profile + "/" + profile_filename
        if not os.path.exists(fullpath):
            monitor_logger.error("\nThe Monitor Profile does not exist.\n")
        else:
            monitor_logger.info("Loading Monitor Profile: " + opt.profile + " (" + fullpath + ")")
            profile = parse_profile(fullpath)
            profile_name = profile
            profile_file = fullpath

            # Overriding Configuration File with parameters
            if opt.ip is not None:
                ip = opt.ip
            else:
                ip = str(profile['Device']['ip'])
            if opt.port is not None:
                port = opt.port
            else:
                port = int(profile['Device']['port'])
            interval = int(profile['Device']['query_interval'])
            if not opt.interval == int(profile['Device']['query_interval']):
                interval = opt.interval

            connected = False
            if not opt.ip == "":
                client = WebHardwareClient(opt.ip, opt.port)
                if client.connect():
                    connected = True
                    tlm_keys = client.execute_command("list_attributes")["retvalue"]
                else:
                    monitor_logger.error("Unable to connect to the Webserver on %s:%d" % (opt.ip, opt.port))
            if connected:
                if opt.single:
                    monitor_logger.info("SINGLE REQUEST")
                    tstamp = dt_to_timestamp(datetime.datetime.utcnow())
                    attributes = {}
                    monitor_logger.info("\nTstamp: %d\tDateTime: %s\n" % (tstamp, ts_to_datestring(tstamp)))
                    for att in tlm_keys:
                        attributes[att] = client.get_attribute(att)["value"]
                        monitor_logger.info(att, attributes[att])
                else:
                    try:
                        monitor_logger.info("CONTINUOUS REQUESTS")
                        while True:
                            tstamp = dt_to_timestamp(datetime.datetime.utcnow())
                            attributes = {}
                            monitor_logger.info("\nTstamp: %d\tDateTime: %s\n" % (tstamp, ts_to_datestring(tstamp)))
                    except KeyboardInterrupt:
                        monitor_logger.warning("\nTerminated by the user.\n")
                client.disconnect()
                del client
