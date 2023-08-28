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
from hardware_client import WebHardwareClient
from skalab_monitor_tab import TileInitialization
from skalab_log import SkalabLog
from skalab_utils import dt_to_timestamp, ts_to_datestring, parse_profile, COLORI, Led, getTextFromFile, colors, unfold_dictionary, merge_dicts, TILE_MONITORING_POINTS
from threading import Thread, Event, Lock
from time import sleep
from pathlib import Path

default_app_dir = str(Path.home()) + "/.skalab/"
default_profile = "Default"
profile_filename = "monitor.ini"

subrack_attribute = {
                "backplane_temperatures": [None]*4,
                "board_temperatures": [None]*4,
                "power_supply_fan_speeds": [None]*4,
                "power_supply_powers": [None]*4,
                "subrack_fan_speeds": [None]*8,
                "subrack_fan_speeds_percent": [None]*8,
                "power_supply_status": [None]*4,
                "board_pll_lock":[None]*2,
                "cpld_pll_lock":[None]*2,
                "pll_source":[None]*2
                }


def populateTable(frame, attributes,top):
    "Create Subrack table"
    qtable = []
    size_a = len(attributes)
    for j in range(size_a):
        sub_attr = []
        qtable.append(getattr(frame, f"table{top[j]}"))
        sub_attr = list(list(attributes[j].values())[0].keys())
        qtable[j].setRowCount(len(sub_attr))
        qtable[j].setColumnCount(2)
        qtable[j].setVerticalHeaderLabels(sub_attr)  
        qtable[j].setHorizontalHeaderLabels(("Value", "Warning/Alarm"))    
    return qtable

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

def populateSubrack(self,wg, attribute):
    j=0
    size_x = 120
    size_y = 60
    for k in attribute:
        for v in range(0,len(attribute[k]),2):
            if (k == "subrack_fan_speeds_percent"):
                subrack_attribute[k][v] = wg.grid_sub_fan.addWidget(QtWidgets.QLineEdit(wg.frame_subrack),3,v)
                subrack_attribute[k][v+1] = wg.grid_sub_fan.addWidget(QtWidgets.QLineEdit(wg.frame_subrack),4,v)
                j-=0.25
                continue
            if (k == "subrack_fan_speeds"):
                subrack_attribute[k][v] = wg.grid_sub_fan.addWidget(QtWidgets.QLineEdit(wg.frame_subrack),1,v)
                subrack_attribute[k][v+1] = wg.grid_sub_fan.addWidget(QtWidgets.QLineEdit(wg.frame_subrack),2,v) 
                j-=0.25
                continue   
            subrack_attribute[k][v] = QtWidgets.QLineEdit(wg.frame_subrack)
            subrack_attribute[k][v+1]= QtWidgets.QLineEdit(wg.frame_subrack)
            subrack_attribute[k][v].setGeometry(QtCore.QRect(  size_x+45*v, 10 +  20+(size_y*(j)),  70,19))
            subrack_attribute[k][v+1].setGeometry(QtCore.QRect(size_x+45*v, 30 +  20+(size_y*(j)),  70,19))
        j+=1


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
        self.interval_monitor = self.profile['Monitor']['query_interval']
        self.tlm_hdf_monitor = None
        self.tpm_initialized = [False] * 8
        # Populate table
        #populateSubrack(self, self.wg, subrack_attribute)
        self.populate_table_profile()
        self.qled_alert = Led(self.wg.overview_frame)
        self.wg.grid_led.addWidget(self.qled_alert)
        self.qled_alert.setObjectName("qled_warn_alar")
        self.qbutton_tpm = populateSlots(self.wg.grid_tpm)
        self.populateTileInstance()
        self.loadTopLevelAttributes()
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
        self.check_tpm_tm.start()

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
        self.wg.check_savedata.toggled.connect(self.setupHdf5) # TODO ADD toggled

    def loadNewTable(self):
        self.loadWarningAlarmValues()
    
    def clearValues(self):
        with (self._lock_led and self._lock_tab1 and self._lock_tab2):
            for i in range(16):
                self.qled_alert[int(i/2)].Colour = Led.Grey
                self.qled_alert[int(i/2)].value = False  
                for attr in self.alarm:
                    self.alarm[attr][int(i/2)] = False
                    if attr in self.tile_table_attr:
                        self.tile_table_attr[attr][i].setText(str(""))
                        self.tile_table_attr[attr][i].setStyleSheet("color: black; background:white")  
                    elif attr in subrack_attribute:
                        try:
                            subrack_attribute[attr][int(i/2)].setText(str(""))
                            subrack_attribute[attr][int(i/2)].setStyleSheet("color: black; background:white")
                        except:
                            pass
                         
    def populateTileInstance(self):
        keys_to_be_removed = []
        self.tpm_on_off = [False] * 8
        self.tpm_active = [None] * 8
        #self.tpm_slot_ip = list(station.configuration['tiles'])
        # Comparing ip to assign slot number to ip: file .ini and .yaml
        self.tpm_slot_ip = eval(self.profile['Monitor']['tiles_slot_ip'])
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
        self.warning_factor = [None,None]
        self.warning_factor[0] = eval((self.profile['Warning Factor']['subrack_warning_parameter']))
        self.warning_factor[1] = eval((self.profile['Warning Factor']['tpm_warning_parameter']))
        self.top_attr = list(self.profile['Monitor']['top_level_attributes'].split(","))
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

    def tpmStatusChanged(self):
        self.wait_check_tpm.clear()
        with self._tpm_lock:
            for k in range(8):
                if self.tpm_on_off[k] and not self.tpm_active[k]:
                    self.tpm_active[k] = Tile(self.tpm_slot_ip[k+1], self.cpld_port, self.lmc_ip, self.dst_port)
                    self.tpm_active[k].program_fpgas(self.bitfile)
                    self.tpm_active[k].connect()
                elif not self.tpm_on_off[k] and self.tpm_active[k]:
                    self.tpm_active[k] = None
        if any(self.tpm_initialized):
            self.wait_check_tpm.set()
            

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

    def readSubrackAttribute(self):
        for attr in self.from_subrack:
            if attr in subrack_attribute:
                self.writeSubrackAttribute(attr,subrack_attribute,False)

    def writeSubrackAttribute(self,attr,table,led_flag):
        for ind in range(0,len(table[attr]),2):
            value = self.from_subrack[attr][int(ind/2)]
            if (not(type(value) == bool) and not(type(value) == str)): value = round(value,1) 
            table[attr][ind].setStyleSheet("color: black; background:white")
            table[attr][ind].setText(str(value))
            table[attr][ind].setAlignment(QtCore.Qt.AlignCenter)
            with self._lock_tab2:
                if not(type(value)==str or type(value)==bool) and not(self.alarm_values[attr][0] <= value <= self.alarm_values[attr][1]):
                    table[attr][ind+1].setText(str(value))
                    table[attr][ind+1].setStyleSheet("color: white; background:red")
                    table[attr][ind+1].setAlignment(QtCore.Qt.AlignCenter)
                    self.logger.error(f"ERROR: {attr} parameter is out of range!")
                    self.alarm[attr][int(ind/2)] = True
                    if led_flag:
                        with self._lock_led:
                            self.qled_alert[int(ind/2)].Colour = Led.Red
                            self.qled_alert[int(ind/2)].value = True
                elif not(type(value)==str or type(value)==bool) and not(self.warning[attr][0] <= value <= self.warning[attr][1]):
                    if not self.alarm[attr][int(ind/2)]:
                        table[attr][ind+1].setText(str(value))
                        table[attr][ind+1].setStyleSheet("color: white; background:orange")
                        table[attr][ind+1].setAlignment(QtCore.Qt.AlignCenter)
                        self.logger.warning(f"WARNING: {attr} parameter is near the out of range threshold!")
                        if self.qled_alert[int(ind/2)].Colour==4 and led_flag:
                            with self._lock_led:
                                self.qled_alert[int(ind/2)].Colour=Led.Orange
                                self.qled_alert[int(ind/2)].value = True


    def setupHdf5(self):
        if not(self.tlm_hdf_monitor):
            if not self.profile['Monitor']['data_path'] == "":
                fname = self.profile['Monitor']['data_path']
                if not fname[-1] == "/":
                    fname = fname + "/"
                    if  os.path.exists(str(Path.home()) + fname) != True:
                        os.makedirs(str(Path.home()) + fname)
                fname += datetime.datetime.strftime(datetime.datetime.utcnow(), "monitor_tlm_%Y-%m-%d_%H%M%S.h5")
                self.tlm_hdf_monitor = h5py.File(str(Path.home()) + fname, 'a')
                return self.tlm_hdf_monitor
            else:
                msgBox = QtWidgets.QMessageBox()
                msgBox.setText("Please Select a valid path to save the Monitor data and save it into the current profile")
                msgBox.setWindowTitle("Error!")
                msgBox.setIcon(QtWidgets.QMessageBox.Critical)
                msgBox.exec_()
                return None

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

class MonitorSubrack(Monitor):
    """ Main UI Window class """
    # Signal for Slots
    signalTlm = QtCore.pyqtSignal()
    signal_to_monitor = QtCore.pyqtSignal()
    signal_to_monitor_for_tpm = QtCore.pyqtSignal()

    def __init__(self, ip=None, port=None, uiFile="", profile="", size=[1190, 936], swpath=""):
        """ Initialise main window """

        super(MonitorSubrack, self).__init__(uiFile="Gui/skalab_monitor.ui", size=[1190, 936], profile=opt.profile, swpath=default_app_dir)   
        self.interval_monitor = self.profile['Monitor']['query_interval']

        self.tlm_keys = []
        self.telemetry = {} 
        self.last_telemetry = {"tpm_supply_fault":[None] *8,"tpm_present":[None] *8,"tpm_on_off":[None] *8}
        self.query_once = []
        self.query_deny = []
        self.query_tiles = []
        self.connected = False
        self.reload(ip=ip, port=port)

        self.tlm_file = ""
        self.tlm_hdf = None

        self.client = None
        self.data_charts = {}

        self.load_events_subrack()
        self.show()
        self.skipThreadPause = False
        self.processTlm = Thread(name="Subrack Telemetry", target=self.readTlm, daemon=True)
        self.wait_check_subrack = Event()
        self._subrack_lock = Lock()
        self.processTlm.start()

    def load_events_subrack(self):
        self.wg.subrack_button.clicked.connect(lambda: self.connect())
        for n, t in enumerate(self.qbutton_tpm):
            t.clicked.connect(lambda state, g=n: self.cmdSwitchTpm(g))

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
                if self.telemetry["tpm_on_off"][slot]:
                    self.client.execute_command(command="turn_off_tpm", parameters="%d" % (int(slot) + 1))
                    self.logger.info("Turn OFF TPM-%02d" % (int(slot) + 1))
                else:
                    self.client.execute_command(command="turn_on_tpm", parameters="%d" % (int(slot) + 1))
                    self.logger.info("Turn ON TPM-%02d" % (int(slot) + 1)) 
            sleep(2.0) # Sleep required to wait for the turn_off/on_tpm command to complete
        self.wait_check_subrack.set()

    def connect(self):
        if not self.wg.qline_ip.text() == "":
            if not self.connected:
                self.logger.info("Connecting to Subrack %s:%d..." % (self.ip, int(self.port)))
                self.client = WebHardwareClient(self.ip, self.port)
                if self.client.connect():
                    self.logger.info("Successfully connected")
                    self.logger.info("Querying list of Subrack API attributes...")
                    for i in range(len(self.top_attr)):
                        diz = self.client.execute_command(command="get_health_dictionary",parameters=self.top_attr[i])["retvalue"]
                        del diz['iso_datetime']
                        if not(self.top_attr[i] in diz.keys()):
                            res = {}
                            for key, value in diz.items():
                                if isinstance(value, dict):
                                    for subkey, subvalue in value.items():
                                        if isinstance(subvalue, dict) and self.top_attr[i] in subvalue:
                                            res[subkey] = {
                                                'unit': subvalue[self.top_attr[i]]['unit'],
                                                'exp_value': subvalue[self.top_attr[i]]['exp_value']
                                            }  
                            diz = {self.top_attr[i]:res}
                        else:
                            diz = {self.top_attr[i]: diz[self.top_attr[i]]}
                        self.tlm_keys.append(diz)                                                                                
                    self.logger.info("Populate monitoring table...")
                    
                    populateTable(self.wg,self.tlm_keys,self.top_attr)
                    for tlmk in self.tlm_keys:
                        if tlmk in self.query_once:
                            data = self.client.get_attribute(tlmk)
                            if data["status"] == "OK":
                                self.telemetry[tlmk] = data["value"]
                            else:
                                self.telemetry[tlmk] = data["info"]
                    if 'api_version' in self.telemetry.keys():
                        self.logger.info("Subrack API version: " + self.telemetry['api_version'])
                    else:
                        self.logger.warning("The Subrack is running with a very old API version!")
                    self.wg.subrack_button.setStyleSheet("background-color: rgb(78, 154, 6);")
                    self.wg.subrack_button.setText("ONLINE")
                    self.wg.subrack_button.setStyleSheet("background-color: rgb(78, 154, 6);")
                    [item.setEnabled(True) for item in self.qbutton_tpm]
                    self.connected = True

                    self.tlm_hdf = self.setupHdf5()
                    data = self.client.execute_command(command="get_health_dictionary")
                    [alarm,warning] = unfold_dictionary(data['retvalue'])
                    with self._subrack_lock:
                        telemetry = self.getTelemetry()
                        self.telemetry = dict(telemetry)
                        self.signal_to_monitor.emit()
                        self.signalTlm.emit()
                    self.wait_check_subrack.set()
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
                self.wg.subrack_button.setStyleSheet("background-color: rgb(204, 0, 0);")
                [item.setEnabled(False) for item in self.qbutton_tpm]
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
        monitor_tlm = {}
        try:
            for tlmk in self.tlm_keys:
                tkey = tlmk
                if not tlmk in self.query_deny:
                    if self.connected:
                        data = self.client.get_attribute(tlmk)
                        if data["status"] == "OK":
                            telem[tlmk] = data["value"]
                            monitor_tlm[tlmk] = telem[tlmk]
                        else:
                            monitor_tlm[tlmk] = "NOT AVAILABLE"
        except:
            self.signal_update_log.emit("Error reading Telemetry [attribute: %s], skipping..." % tkey,"error")
            #self.logger.error("Error reading Telemetry [attribute: %s], skipping..." % tkey)
            monitor_tlm[tlmk] = f"ERROR{tkey}"
            self.from_subrack =  monitor_tlm 
            return
        self.from_subrack =  monitor_tlm  
        return telem

    def getTiles(self):
        try:
            for tlmk in self.query_tiles:
                data = self.client.get_attribute(tlmk)
                if data["status"] == "OK":
                    self.telemetry[tlmk] = data["value"]
                else:
                    self.telemetry[tlmk] = []
            return self.telemetry['tpm_ips']
        except:
            return []

    def readTlm(self):
        while True:
            self.wait_check_subrack.wait()
            with self._subrack_lock:
                if self.connected:
                    try:
                        telemetry = self.getTelemetry()
                        self.telemetry = dict(telemetry)
                    except:
                        self.signal_update_log.emit("Failed to get Subrack Telemetry!","warning")
                        pass
                    self.signalTlm.emit()
                    self.signal_to_monitor.emit()
                    cycle = 0.0
                    while cycle < (float(self.profile['Subrack']['query_interval'])) and not self.skipThreadPause:
                        sleep(0.1)
                        cycle = cycle + 0.1
                    self.skipThreadPause = False
            sleep(0.5)        

    def updateTpmStatus(self):
        # TPM status on QButtons
        if "tpm_supply_fault" in self.telemetry.keys():
            for n, fault in enumerate(self.telemetry["tpm_supply_fault"]):
                if fault:
                    self.qbutton_tpm[n].setStyleSheet(colors("yellow_on_black"))
                    self.tpm_on_off[n] = False
                else:
                    if "tpm_present" in self.telemetry.keys():
                        if self.telemetry["tpm_present"][n]:
                            self.qbutton_tpm[n].setStyleSheet(colors("black_on_red"))
                            self.tpm_on_off[n] = False
                        else:
                            self.qbutton_tpm[n].setStyleSheet(colors("black_on_grey"))
                            self.tpm_on_off[n] = False
                    if "tpm_on_off" in self.telemetry.keys():
                        if self.telemetry["tpm_on_off"][n]:
                            self.qbutton_tpm[n].setStyleSheet(colors("black_on_green"))
                            self.tpm_on_off[n] = True
            try:
                if (self.telemetry["tpm_supply_fault"]!= self.last_telemetry["tpm_supply_fault"]) | (self.telemetry["tpm_present"]!= self.last_telemetry["tpm_present"]) | (self.telemetry["tpm_on_off"]!= self.last_telemetry["tpm_on_off"]):
                    self.signal_to_monitor_for_tpm.emit()
                    self.last_telemetry["tpm_supply_fault"] = self.telemetry["tpm_supply_fault"]
                    self.last_telemetry["tpm_present"] = self.telemetry["tpm_present"]
                    self.last_telemetry["tpm_on_off"] = self.telemetry["tpm_on_off"]
                    
            except:
                self.signal_to_monitor_for_tpm.emit()            

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
        window.signal_to_monitor.connect(window.readSubrackAttribute)
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

