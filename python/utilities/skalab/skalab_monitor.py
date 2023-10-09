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
#from timeit import default_timer as timer

from pyaavs.tile_wrapper import Tile
from pyaavs import station
from PyQt5 import QtWidgets, uic, QtCore
from PyQt5.QtGui import QColor
from hardware_client import WebHardwareClient
from skalab_monitor_tpm_utils import *
from skalab_log import SkalabLog
from skalab_utils import *
from threading import Thread, Event, Lock
from time import sleep
from pathlib import Path

default_app_dir = str(Path.home()) + "/.skalab/"
default_profile = "Default"
profile_filename = "monitor.ini"

standard_subrack_attribute = {
                "tpm_present": [None]*8,
                "tpm_on_off": [None]*8
                }


def populateTpmTable(frame, table, alarm):

    qtable_tpm = [None] * 8 
    for i in range(8): #Select TPM
        qtable_tpm[i] = []
        for j in range(len(table)): #Select table number
            for k,v in table[j].items(): #Get table name and address attribute 
                qtable_tpm[i].append(getattr(frame, f"{k}_tab_{i+1}"))
                qtable_tpm[i][-1].verticalHeader().setVisible(True)
                qtable_tpm[i][-1].setColumnCount(2)
                qtable_tpm[i][-1].setHorizontalHeaderLabels(("Value", "Warning/Alarm"))
                # Use eval to access the value in the dictionary
                if isinstance(v,list):
                    result = []
                    for attribute in v:
                        if isinstance(eval("alarm" + attribute),bool):
                            a = attribute[2:-2].replace('"]["',',').split(',')
                            result.append(a[-1])
                        else:
                            result.extend(list(eval("alarm" + attribute)))
                elif not(isinstance(eval("alarm" + v),tuple)) and not(isinstance(eval("alarm" + v),bool)) :
                    result = list(eval("alarm" + v))
                else:
                    a = v.replace('][','],[').split(',')
                    result = eval(a[-1])
                    qtable_tpm[i][-1].setRowCount(len(result))
                    qtable_tpm[i][-1].setVerticalHeaderLabels(result)
                    qtable_tpm[i][-1].horizontalHeader().setFixedHeight(20)
                    qtable_tpm[i][-1].resizeRowsToContents()
                    break 
                qtable_tpm[i][-1].setRowCount(len(result))
                qtable_tpm[i][-1].setVerticalHeaderLabels(result) 
                qtable_tpm[i][-1].horizontalHeader().setFixedHeight(20)
                if not(j in {4,5,6}):
                    qtable_tpm[i][-1].resizeRowsToContents()                
    return qtable_tpm

def populateSubrackTable(frame, attributes, top):
    "Create Subrack table"
    qtable = []
    sub_attr = []
    size_a = len(attributes)
    #error if monitor.ini has ",," in top level entry
    for j in range(size_a):
        qtable.append(getattr(frame, f"table{top[j]}"))
        sub_attr.append(list(list(attributes[j].values())[0].keys()))
        qtable[j].setRowCount(len(sub_attr[j]))
        qtable[j].setColumnCount(2)
        qtable[j].setVerticalHeaderLabels(sub_attr[j])  
        qtable[j].setHorizontalHeaderLabels(("Value", "Warning/Alarm")) 
    return qtable, sub_attr

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


class MonitorTPM(TileInitialization):

    signal_update_tpm_attribute = QtCore.pyqtSignal(dict,int)
    signal_update_log = QtCore.pyqtSignal(str,str)
   
    def __init__(self, config="", uiFile="", profile="", size=[1170, 919], swpath=""):
        """ Initialise main window """
        # Load window file
        self.wg = uic.loadUi(uiFile)
        
        self.wgProBox = QtWidgets.QWidget(self.wg.qtab_conf)
        self.wgProBox.setGeometry(QtCore.QRect(1, 1, 800, 860))
        self.wgProBox.setVisible(True)
        self.wgProBox.show()
        super(MonitorTPM, self).__init__(profile, swpath)
        self.logger = SkalabLog(parent=self.wg.qt_log, logname=__name__, profile=self.profile)
        self.setCentralWidget(self.wg)
        self.loadEventsMonitor()
        # Set variable
        self.tpm_table_address = []       
        self.tpm_alarm_thresholds = {}
        self.tpm_interval = self.profile['Monitor']['tpm_query_interval']
        self.tpm_table_address = tpm_tables_address
        self.tlm_hdf_tpm_monitor = []
        self.tpm_initialized = [False] * 8
        self.tpm_table = []
        self.flag = False
        # Populate table
        self.populate_table_profile()
        self.qbutton_tpm = populateSlots(self.wg.grid_tpm)
        self.text_editor = ""
        if 'Extras' in self.profile.keys():
            if 'text_editor' in self.profile['Extras'].keys():
                self.text_editor = self.profile['Extras']['text_editor']
        self.tpm_warning_factor = eval(self.profile['Warning Factor']['tpm_warning_parameter'])
        self.show()
        with open(r'tpm_monitoring_min_max.yaml') as file:
            MIN_MAX_MONITORING_POINTS = (yaml.load(file, Loader=yaml.Loader)["tpm_monitoring_points"] or {})
        self.tpm_alarm_thresholds = copy.deepcopy(MIN_MAX_MONITORING_POINTS )    
        self.fixed_attr = ['temperatures','voltages','currents']
        for a in self.fixed_attr:
            for key, value in MIN_MAX_MONITORING_POINTS[a].items():
                self.tpm_alarm_thresholds[a][key] = [value['min'], value['max']]
        self.tpm_table = populateTpmTable(self.wg,self.tpm_table_address,MIN_MAX_MONITORING_POINTS)
        self.setTpmThreshold(self.tpm_warning_factor)
        self.populateTpmLed(MIN_MAX_MONITORING_POINTS)
        self.tlm_hdf_tpm_monitor = self.setupTpmHdf5()
        # Start thread
        self.check_tpm_tm = Thread(name= "TPM telemetry", target=self.monitoringTpm, daemon=True)
        self._tpm_lock = Lock()
        self._tpm_lock_GUI = Lock()
        self.flag_lock = Lock()
        self.wait_check_tpm = Event()
        self.check_tpm_tm.start()

    def populateTpmLed(self,MIN_MAX_MONITORING_POINTS):
        self.qled_tpm = [None] * 8 
        for i in range(8):
            self.qled_tpm[i] = []
            for j in range(len(MIN_MAX_MONITORING_POINTS)):
                self.qled_tpm[i].append(Led(self.wg.table_alarms))
                self.wg.led_layout.addWidget(self.qled_tpm[i][-1],j,i,QtCore.Qt.AlignCenter)
                

    def setTpmThreshold(self, warning_factor):
        default = self.wg.qline_tpm_threshold.text()
        if default != 'default_tpm_alarm.txt':
            with open(default, 'r') as file:
                a_lines = []
                self.tpm_alarm_shadow = []
                for line in file:
                    line = line.strip()
                    line = eval(line)
                    a_lines = line
            self.tpm_alarm_thresholds = a_lines
            [self.tpm_alarm_shadow.append(copy.deepcopy(self.tpm_alarm_thresholds)) for i in range(8)]

        else:
            file = open('default_tpm_alarm.txt','w+')
            file.write(str(self.tpm_alarm_thresholds))
            file.close()
        self.tpm_warning_thresholds = copy.deepcopy(self.tpm_alarm_thresholds)

        #this is the actual paramen ter used by the program to execute the check value/threshold.
        #it is necessary since, when the clear button is pushed, the actual counters values are stored here. 
        # if a new thresholds table is loaded, this shodow paraemter is overwritten.
        self.tpm_alarm_shadow = copy.deepcopy(self.tpm_alarm_thresholds)

        for i in self.fixed_attr:
            keys = list(self.tpm_alarm_thresholds[i].keys())
            for j in keys:
                try:
                    al_max = self.tpm_alarm_thresholds[i][j][1]
                    al_min = self.tpm_alarm_thresholds[i][j][0]
                    factor = (al_max - al_min) * (warning_factor)
                    self.tpm_warning_thresholds[i][j][0] = round(al_min + factor,2)
                    self.tpm_warning_thresholds[i][j][1] = round(al_max - factor,2)
                except:
                    pass
        writeThresholds(self.wg.ala_text_2, self.wg.war_text_2, self.tpm_alarm_thresholds, self.tpm_warning_thresholds)


    def loadTpmThreshold(self):
        fd = QtWidgets.QFileDialog()
        fd.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, True)
        options = fd.options()
        self.filename = fd.getOpenFileName(self, caption="Select a Tpm Alarm Thresholds file...",
                                              directory="./", options=options)[0]
        if not(self.filename == ''):
            self.wg.qline_tpm_threshold.setText(self.filename)
            with self._tpm_lock_GUI:
                self.setTpmThreshold(self.tpm_warning_factor)
        return


    def writeLog(self,message,priority):
        """To pass the log info from thread to main"""
        if priority == "info":
            self.logger.info(message)
        elif priority == "warning":
            self.logger.warning(message)
        else:
            self.logger.error(message)


    def loadEventsMonitor(self):
        self.wg.qbutton_tpm_edit.clicked.connect(lambda: editClone(self.wg.qline_tpm_threshold.text(), self.text_editor))
        self.wg.qbutton_tpm_threshold.clicked.connect(lambda: self.loadTpmThreshold())
        self.wg.qbutton_clear_tpm.clicked.connect(lambda: self.clearTpmValues())
    

    def clearTpmValues(self):
        with (self._tpm_lock_GUI):
            for i in range(8):
                for led in self.qled_tpm[i]:
                    led.Colour = Led.Grey
                    led.m_value = False
                for table in self.tpm_table[i]:
                    table.clearContents()
                         

    def populateTileInstance(self):
        if (self.connected and self.tpm_assigned_tpm_ip_adds):
            # Comparing ip to assign slot number to ip: file .ini and .yaml
            self.tpm_slot_ip = self.tpm_assigned_tpm_ip_adds
            self.tpm_ip_check= station.configuration['tiles']
            for j in self.tpm_ip_check:
                if j in self.tpm_slot_ip:
                    pass
                else:
                    self.logger.warning(f"ATTENTION: TMP IP: {j} in {self.config_file} is not detected by the Subrack.")


    def tpmStatusChanged(self):
        self.wait_check_tpm.clear()
        for k in range(8):
            if not(self.tpm_on_off[k]) and self.tpm_active[k]:
                self.tpm_active[k] = None
        if any(self.tpm_initialized):
            self.wg.check_tpm_savedata.setEnabled(True)
            self.wait_check_tpm.set()
        else:
            self.wg.check_tpm_savedata.setEnabled(False)

    def monitoringTpm(self):
        while True:
            self.wait_check_tpm.wait()
            # Get tm from tpm
            for index in range(8): # loop to select tpm
                with self._tpm_lock:
                    if self.tpm_active[index]:
                        try:
                            L = self.tpm_active[index].get_health_status()
                            if self.wg.check_tpm_savedata.isChecked(): self.saveTpmData(L,index)
                        except:
                            self.signal_update_log.emit(f"Failed to get TPM Telemetry. Are you turning off TPM#{index+1}?","warning")
                            continue
                        with self._tpm_lock_GUI:
                            self.signal_update_tpm_attribute.emit(L,index)
            sleep(float(self.interval_monitor))    

    def unfoldTpmAttribute(self, tpm_dict, tpm_index):
        with self._tpm_lock_GUI:
            for i in range(len(self.tpm_table[tpm_index])): #loop to select table
                led_id = self.select_led(i)
                table = self.tpm_table[tpm_index][i]
                for key in list(self.tpm_table_address[i].values()): # loop to select the content of the table
                    if isinstance(key,list):
                        tpm_values = []
                        filtered_alarm =  []
                        filtered_warning = []
                        tpm_attr = []
                        for attribute in key:
                            v = eval("tpm_dict" + attribute)
                            va = eval("self.tpm_alarm_shadow" + attribute)
                            vw = eval("self.tpm_warning_thresholds" + attribute)
                            tpm_values.extend(list(v.values())) if not(isinstance(v,bool)) else tpm_values.append(v)
                            ta = list(v.keys()) if not(isinstance(v,bool)) else v
                            tpm_attr.extend([f"{attribute} {x}" for x in ta] if not (isinstance(v,bool)) else [attribute])
                            filtered_alarm.extend(list(va.values())) if not(isinstance(va,bool)) else filtered_alarm.append(va)
                            filtered_warning.extend(list(vw.values())) if not(isinstance(vw,bool)) else filtered_warning.append(vw)
                    elif not(isinstance(eval("tpm_dict" + key),tuple)) and not(isinstance(eval("tpm_dict" + key),bool)):
                        tpm_values = list(eval('tpm_dict'+key).values())
                        ta = list(eval('tpm_dict'+key).keys())
                        tpm_attr = [f"{key} {x}" for x in ta]
                        filtered_alarm = list(eval('self.tpm_alarm_shadow'+key).values())
                        filtered_warning = list(eval('self.tpm_warning_thresholds'+key).values())
                    else:
                        tpm_attr = [key]
                        tpm_values = [eval('tpm_dict'+key)] #for a tuple
                        filtered_alarm = [eval('self.tpm_alarm_shadow'+key)]
                        filtered_warning = [eval('self.tpm_warning_thresholds'+key)]

                    for j in range(len(tpm_values)): #loop to write values in the proper table cell
                        value = tpm_values[j]
                        table.setItem(j,0, QtWidgets.QTableWidgetItem(str(value)))
                        item = table.item(j, 0)
                        item.setTextAlignment(QtCore.Qt.AlignCenter)
                        if isinstance(filtered_alarm[j],list):
                            min_alarm = filtered_alarm[j][0]
                            min_warn = filtered_warning[j][0]
                            max_alarm = filtered_alarm[j][1] 
                            max_warn = filtered_warning[j][1]
                        else:
                            max_alarm =filtered_alarm[j]
                            min_alarm = max_alarm
                            max_warn = filtered_warning[j]
                            min_warn = max_warn
                        if not(type(value) == str or value == None):
                            if not(min_alarm <= value <= max_alarm): 
                                table.setItem(j,1, QtWidgets.QTableWidgetItem(str(value)))
                                item = table.item(j,1)
                                item.setForeground(QColor("white"))
                                item.setBackground(QColor("#ff0000")) # red
                                self.logger.error(f"ERROR in TPM{tpm_index+1}: {tpm_attr[j]} parameter is out of range!")
                                # Change the color only if it not 1=red
                                if not(self.qled_tpm[tpm_index][led_id].Colour==1):
                                    self.qled_tpm[tpm_index][led_id].Colour = Led.Red
                                    self.qled_tpm[tpm_index][led_id].value = True 
                            elif not(min_warn <= value <= max_warn) and not(item.background().color().name() == '#ff0000'):
                                table.setItem(j,1, QtWidgets.QTableWidgetItem(str(value)))
                                item = table.item(j, 1)
                                item.setTextAlignment(QtCore.Qt.AlignCenter)
                                item.setForeground(QColor("white"))
                                item.setBackground(QColor("#ff8000")) #orange
                                self.logger.warning(f"WARNING in TPM{tpm_index+1}: {tpm_attr[j]} parameter is near the out of range threshold!")
                                # Change the color only if it is 4=Grey
                                if self.qled_tpm[tpm_index][led_id].Colour==4: 
                                    self.qled_tpm[tpm_index][led_id].Colour=Led.Orange
                                    self.qled_tpm[tpm_index][led_id].value = True
    
    def select_led(self,index):
        # with if for python<3.10
        if index < 5:
            return index
        elif index > 27:
            return 8
        elif 4<index<8:
            return 5
        elif 7<index<12:
            return 6
        else:
            return 7

    def setupTpmHdf5(self):
        default_app_dir = str(Path.home()) + "/.skalab/monitoring/tpm_monitor/"
        if not(self.tlm_hdf_tpm_monitor):
            if not self.profile['Tpm']['tpm_data_path'] == "":
                fname = self.profile['Tpm']['tpm_data_path']
                if not fname[-1] == "/":
                    fname = fname + "/"
                    if  os.path.exists(str(Path.home()) + fname) != True:
                        try:
                            os.makedirs(str(Path.home()) + fname)
                        except:
                            fname = default_app_dir
                for tpm_id in range(8):
                    temp = fname+datetime.datetime.strftime(datetime.datetime.utcnow(), "monitor_tpm"+ f"{tpm_id}"+"_%Y-%m-%d_%H%M%S.h5")
                    self.tlm_hdf_tpm_monitor.append(h5py.File(str(Path.home()) + temp, 'a'))
                return self.tlm_hdf_tpm_monitor
            else:
                msgBox = QtWidgets.QMessageBox()
                msgBox.setText("Please Select a valid path to save the Monitor data and save it into the current profile")
                msgBox.setWindowTitle("Error!")
                msgBox.setIcon(QtWidgets.QMessageBox.Critical)
                msgBox.exec_()
                return None

    def saveTpmData(self, tpm_tlm, tpm_id):
        currentDateAndTime = datetime.datetime.now()
        currentTime = currentDateAndTime.strftime("%H:%M:%S:%SS")
        if self.tlm_hdf_tpm_monitor[tpm_id]:
            filename = self.tlm_hdf_tpm_monitor[tpm_id]
            try:
                dt = h5py.special_dtype(vlen=str) 
                feature_names = np.array(str(tpm_tlm), dtype=dt) 
                filename.create_dataset(currentTime,data=feature_names)
            except:
                self.logger.error(f"WRITE SUBRACK TELEMETRY ERROR at {datetime}")    
                 

class MonitorSubrack(MonitorTPM):
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
        self.subrack_warning_factor = eval(self.profile['Warning Factor']['subrack_warning_parameter'])
        self.tlm_keys = []
        self.tpm_status_info = {} 
        self.from_subrack = {}
        self.top_attr = list(self.profile['Monitor']['top_level_attributes'].split(","))

        self.last_telemetry = {"tpm_supply_fault":[None] *8,"tpm_present":[None] *8,"tpm_on_off":[None] *8}
        self.query_once = []
        self.query_deny = []
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
        self.wg.tpmbar.hide()
        self.subrack_led = Led(self.wg.overview_frame)
        self.wg.grid_led.addWidget(self.subrack_led)
        self.subrack_led.setObjectName("qled_warn_alar")
        self.client = None
        self.data_charts = {}
        self.loadEventsSubrack()
        self.show()
        
        self.skipThreadPause = False
        #self.slot_thread = Thread(name="Slot", target= self.slot1)
        #self.temperature_thread = Thread(name="temp", target = self.temp1)   
        self.subrackTlm = Thread(name="Subrack Telemetry", target=self.readSubrackTlm, daemon=True)
        self.wait_check_subrack = Event()
        self._subrack_lock = Lock()
        self._subrack_lock_GUI = Lock()
        self.subrackTlm.start()


    def loadSubrackThreshold(self):
        fd = QtWidgets.QFileDialog()
        fd.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, True)
        options = fd.options()
        self.filename = fd.getOpenFileName(self, caption="Select a Subrack Alarm Thresholds file...",
                                              directory="./", options=options)[0]
        if not(self.filename == ''):
            self.wg.qline_subrack_threshold.setText(self.filename)
            with self._subrack_lock_GUI:
                if self.connected:
                    # TODO self.subrack_warning_factor
                    self.alarm = getThreshold(self.wg,self.tlm_keys,self.top_attr)#,self.subrack_warning_factor)
                else:
                    self.logger.warning("Connect to the Subrack to load the threshold table.")    
        return


    def loadEventsSubrack(self):
        self.wg.qbutton_clear_subrack.clicked.connect(lambda: self.clearSubrackValues())
        self.wg.subrack_button.clicked.connect(lambda: self.connect())
        self.wg.qbutton_subrack_edit.clicked.connect(lambda: editClone(self.wg.qline_subrack_threshold.text(), self.text_editor))
        self.wg.qbutton_subrack_threshold.clicked.connect(lambda: self.loadSubrackThreshold())
        for n, t in enumerate(self.qbutton_tpm):
            t.clicked.connect(lambda state, g=n: self.cmdSwitchTpm(g))

    # def slot1(self):
    #     start1 = timer()
    #     self.client.execute_command(command="get_health_status",parameters ='psus')
    #     end1 = timer()
    #     print(f"SLOT1 {end1 - start1}")
    #     return

    # def temp1(self):
    #     start2 = timer()
    #     self.client.execute_command(command="get_health_status",parameters ='SLOT1')
    #     end2 = timer()
    #     print(f"temperatures {end2 - start2}")
    #     return

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

    
    def connect(self):
        self.tlm_keys = []
        self.tpm_on_off = [False] * 8
        self.tpm_active = [None] * 8
        if not self.wg.qline_ip.text() == "":
            if not self.connected:
                self.wg.subrackbar.show()
                self.logger.info("Connecting to Subrack %s:%d..." % (self.ip, int(self.port)))
                self.client = WebHardwareClient(self.ip, self.port)
                self.wg.subrackbar.setValue(20)
                if self.client.connect():
                    self.logger.info("Successfully connected")
                    self.logger.info("Querying list of Subrack API attributes...")
                    # The following command is necessary in order to fill the subrack paraemeters table,\
                    # to set the thresholds values and to know the key paramenters exposed by the API.
                    self.subrack_dictionary = self.client.execute_command(command="get_health_dictionary")["retvalue"]
                    self.wg.subrackbar.setValue(30)
                    del self.subrack_dictionary['iso_datetime']

                    for i in range(len(self.top_attr)):
                        if self.top_attr[i] in self.subrack_dictionary.keys():
                            diz = {self.top_attr[i]: self.subrack_dictionary[self.top_attr[i]]}
                            del self.subrack_dictionary[self.top_attr[i]]
                        elif self.top_attr[i] != 'others':
                            res = {}
                            for key, value in self.subrack_dictionary.items():
                                if isinstance(value, dict):
                                    for subkey, subvalue in value.items():
                                        if isinstance(subvalue, dict) and self.top_attr[i] in subvalue:
                                            res[subkey] = {
                                                'unit': subvalue[self.top_attr[i]]['unit'],
                                                'exp_value': subvalue[self.top_attr[i]]['exp_value']
                                            } 
                                            #delete empty dictionary
                                            del self.subrack_dictionary[key][subkey][self.top_attr[i]]
                                    for jk in list(self.subrack_dictionary[key]):
                                        if len(self.subrack_dictionary[key][jk]) == 0: del self.subrack_dictionary[key][jk]
                            for k in list(self.subrack_dictionary.keys()):
                                if len(self.subrack_dictionary[k]) == 0:  del self.subrack_dictionary[k]
                            diz = {self.top_attr[i] : res} 
                        else:
                            res = {}
                            for value in self.subrack_dictionary.values():
                                if isinstance(value, dict):
                                    res.update(value)
                                else:
                                    diz.update({self.top_attr[i] : value})  
                            diz = {self.top_attr[i]:res}
                        self.tlm_keys.append(diz)

                    self.logger.info("Populate monitoring table...")
                    [self.subrack_table, self.sub_attribute] = populateSubrackTable(self.wg,self.tlm_keys,self.top_attr)
                    self.wg.subrackbar.setValue(40)
                    for tlmk in self.query_once:
                        data = self.client.get_attribute(tlmk)
                        if data["status"] == "OK":
                            self.tpm_status_info[tlmk] = data["value"]
                        else:
                            self.tpm_status_info[tlmk] = data["info"]
                    if 'assigned_tpm_ip_adds' in self.tpm_status_info.keys():
                        self.tpm_assigned_tpm_ip_adds = self.tpm_status_info['assigned_tpm_ip_adds']
                    else:
                        self.tpm_assigned_tpm_ip_adds = self.client.get_attribute('assigned_tpm_ip_adds')
                    if 'api_version' in self.tpm_status_info.keys():
                        self.logger.info("Subrack API version: " + self.tpm_status_info['api_version'])
                    else:
                        self.logger.warning("The Subrack is running with a very old API version!")
                    self.wg.subrackbar.setValue(60)
                    self.connected = True
                    self.populateTileInstance()
                    self.tlm_hdf = self.setupSubrackHdf5()
                    # TODO: Uncomment the next line when subrack attributes are defined 
                    #[self.alarm, self.warning] = getThreshold(self.wg, self.tlm_keys,self.top_attr,self.subrack_warning_factor)
                    self.alarm = getThreshold(self.wg, self.tlm_keys,self.top_attr) # temporaney line. See TODO above
                    self.wg.subrackbar.setValue(70)
                    for tlmk in standard_subrack_attribute: 
                        data = self.client.get_attribute(tlmk)
                        if data["status"] == "OK":
                            self.tpm_status_info[tlmk] = data["value"]
                        else:
                            self.tpm_status_info[tlmk] = data["info"]
                            self.logger.error(f"Error with self.client.get_attribute({tlmk})")
                    self.wg.subrackbar.setValue(80)
                    self.wg.subrack_button.setStyleSheet("background-color: rgb(78, 154, 6);")
                    self.wg.subrack_button.setText("ONLINE")
                    self.wg.subrack_button.setStyleSheet("background-color: rgb(78, 154, 6);")
                    [item.setEnabled(True) for item in self.qbutton_tpm]
                    with self._subrack_lock:
                        self.updateTpmStatus()
                    self.wg.subrackbar.setValue(100)
                    self.wg.qbutton_clear_subrack.setEnabled(True)
                    self.wg.qbutton_clear_tpm.setEnabled(True)
                    # print("start temperature thread")
                    # self.temperature_thread.start()
                    # print("start slot thread")
                    # self.slot_thread.start()
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
                    self.wg.qbutton_station_init.setEnabled(False) 

            else:
                self.logger.info("Disconneting from Subrack %s:%d..." % (self.ip, int(self.port)))
                self.wait_check_tpm.clear()
                self.wait_check_subrack.clear()
                self.connected = False
                self.wg.qbutton_station_init.setStyleSheet("background-color: rgb(255, 255, 255);")
                self.wg.qbutton_station_init.setEnabled(False) 
                self.wg.subrack_button.setStyleSheet("background-color: rgb(204, 0, 0);")
                self.wg.subrack_button.setText("OFFLINE")
                self.wg.qbutton_clear_subrack.setEnabled(False)
                self.wg.qbutton_clear_tpm.setEnabled(False)
                [item.setEnabled(False) for item in self.qbutton_tpm]
                self.client.disconnect()
                del self.client
                self.tpm_on_off = [False] * 8
                self.tpm_active = [None] * 8
                gc.collect()
                # if (type(self.tlm_hdf) is not None) or (type(self.tlm_hdf_tpm_monitor) is not None):
                #     try:
                #         self.tlm_hdf.close()
                #         self.tlm_hdf_tpm_monitor.close()
                #     except:
                #         pass
        else:
            self.wg.qlabel_connection.setText("Missing IP!")
            self.wait_check_tpm.clear()
            self.wait_check_subrack.clear()

    
    def cmdSwitchTpm(self, slot):
            self.wg.tpmbar.show()
            self.wait_check_subrack.clear()
            self.skipThreadPause = True
            self.qbutton_tpm[slot].setEnabled(False)
            self.wg.tpmbar.setValue(10)
            # it seems that with ... and ... does not work
            self._subrack_lock.acquire()
            self._tpm_lock.acquire()
            if self.connected:
                if self.tpm_status_info["tpm_on_off"][slot]:
                    self.wg.tpmbar.setValue(30)
                    self.wg.qbutton_station_init.setEnabled(False)
                    self.client.execute_command(command="turn_off_tpm", parameters="%d" % (int(slot) + 1))
                    self.logger.info("Turn OFF TPM-%02d" % (int(slot) + 1))
                    self.wg.tpmbar.setValue(40)
                else:
                    self.wg.tpmbar.setValue(30)
                    self.wg.qbutton_station_init.setEnabled(False)
                    self.client.execute_command(command="turn_on_tpm", parameters="%d" % (int(slot) + 1))
                    self.logger.info("Turn ON TPM-%02d" % (int(slot) + 1)) 
                    self.wg.tpmbar.setValue(40)
                sleep(4.0) # Sleep required to wait for the turn_off/on_tpm command to complete
                self.wg.tpmbar.setValue(70)
                self.tpm_status_info['tpm_on_off'] = self.client.get_attribute('tpm_on_off')['value'] # update tpm on/off
                self.wg.tpmbar.setValue(90)
                self.updateTpmStatus()
                self.wg.tpmbar.setValue(100)
                self.qbutton_tpm[slot].setEnabled(True)
                self._subrack_lock.release()
                self._tpm_lock.release()
            self.wait_check_subrack.set()
            self.wg.tpmbar.hide()


    def getTelemetry(self):
        check_subrack_ready = 0
        with self._subrack_lock:
            while check_subrack_ready<5:
                data = self.client.execute_command(command="get_health_status")
                if data["status"] == "OK":
                    self.from_subrack =  data['retvalue']
                    self.tpm_status_info['tpm_present'] = list(self.from_subrack['slots']['presence'].values())
                    self.tpm_status_info['tpm_on_off'] = list(self.from_subrack['slots']['on'].values()) 
                    if self.wg.check_subrack_savedata.isChecked(): self.saveSubrackData(self.from_subrack)
                    if not(self.wg.qbutton_station_init.isEnabled()): self.wg.qbutton_station_init.setEnabled(True)
                    break
                else:
                    self.logger.warning(f"Subrack Data NOT AVAILABLE...try again: {check_subrack_ready}/5")
                    self.from_subrack =  data['retvalue']
                    check_subrack_ready +=1

            
    def readSubrackTlm(self):
        while True:
            self.wait_check_subrack.wait()
            if self.connected:
                self.getTelemetry()
                self.signalTlm.emit()
            with self._subrack_lock_GUI:            
                self.signal_to_monitor.emit()
            cycle = 0.0
            while cycle < (float(self.subrack_interval)) and not self.skipThreadPause:
                sleep(0.1)
                cycle = cycle + 0.1
            self.skipThreadPause = False

    
    def readwriteSubrackAttribute(self):
        diz = copy.deepcopy(self.from_subrack)
        if diz == '':
            self.logger.error(f"Warning: get_health_status return an empty dictionary. Try again at the next polling cycle")
            return
        with self._subrack_lock_GUI:
            for index_table in range(len(self.top_attr)):
                table = self.subrack_table[index_table]
                if self.top_attr[index_table] in diz.keys():
                    if (list(diz[self.top_attr[index_table]]) == self.sub_attribute[index_table]):
                        attribute_data = diz[self.top_attr[index_table]]
                        filtered_alarm =  self.alarm[index_table][self.top_attr[index_table]]
                        #filtered_warning = self.warning[index_table][self.top_attr[index_table]]
                        diz.pop(self.top_attr[index_table])
                    else:
                        break
                elif self.top_attr[index_table] != 'others':
                    res = {}
                    for key, value in diz.items():
                        if isinstance(value, dict):
                            for subkey, subvalue in value.items():
                                if isinstance(subvalue, dict) and self.top_attr[index_table] in subvalue:
                                    res[subkey] = subvalue[self.top_attr[index_table]]
                                    diz[key][subkey].pop(self.top_attr[index_table])
                            for jk in list(diz[key]):
                                if not bool(diz[key][jk]): del diz[key][jk]
                    for k in list(diz.keys()):
                        if len(diz[k]) == 0:  del diz[k]
                    attribute_data = res
                    filtered_alarm =  self.alarm[index_table][self.top_attr[index_table]]
                    #filtered_warning = self.warning[index_table][self.top_attr[index_table]]
                else:
                    res = {}
                    temp = []
                    for key, value in diz.items():
                        if isinstance(value, dict):
                            res.update(value)
                        temp.append(key)
                    [diz.pop(t) for t in temp]
                    attribute_data = res
                    filtered_alarm =  self.alarm[index_table][self.top_attr[index_table]]
                    #filtered_warning = self.warning[index_table][self.top_attr[index_table]]
                        
                attrs = list(attribute_data.keys())
                values = list(attribute_data.values())
                for i in range(len(attribute_data)):
                    value = values[i]
                    attr = attrs[i]
                    table.setItem(i,0, QtWidgets.QTableWidgetItem(str(value)))
                    item = table.item(i, 0)
                    item.setTextAlignment(QtCore.Qt.AlignCenter)
                    if not(type(value)==str or value==None or filtered_alarm[attr][0]==None):
                        if not(filtered_alarm[attr][0] <= value <= filtered_alarm[attr][1]): 
                            table.setItem(i,1, QtWidgets.QTableWidgetItem(str(value)))
                            item = table.item(i, 1)
                            item.setTextAlignment(QtCore.Qt.AlignCenter)
                            item.setForeground(QColor("white"))
                            item.setBackground(QColor("#ff0000")) # red
                            self.logger.error(f"ERROR: {attr} parameter is out of range!")
                            # Change the color only if it not 1=red
                            if not(self.subrack_led.Colour==1):
                                self.subrack_led.Colour = Led.Red
                                self.subrack_led.value = True
                                # TODO: Uncomment when subrack attributes are definitive.
                                """                     
                                elif not(filtered_warning[attr][0] < value < filtered_warning[attr][1]) and not(item.background().color().name() == '#ff0000'):
                                table.setItem(i,1, QtWidgets.QTableWidgetItem(str(value)))
                                item = table.item(i, 1)
                                item.setTextAlignment(QtCore.Qt.AlignCenter)
                                item.setForeground(QColor("white"))
                                item.setBackground(QColor("#ff8000")) #orange
                                self.logger.warning(f"WARNING: {attr} parameter is near the out of range threshold!")
                                # Change the color only if it is 4=Grey
                                if self.subrack_led.Colour==4: 
                                        self.subrack_led.Colour=Led.Orange
                                        self.subrack_led.value = True
                                """


    def updateTpmStatus(self):
        # TPM status on QButtons
        try:
            for n in range(8):
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
                if (self.tpm_status_info["tpm_present"]!= self.last_telemetry["tpm_present"]) | (self.tpm_status_info["tpm_on_off"]!= self.last_telemetry["tpm_on_off"]):
                    self.signal_to_monitor_for_tpm.emit()
                    self.last_telemetry["tpm_present"] = self.tpm_status_info["tpm_present"]
                    self.last_telemetry["tpm_on_off"] = self.tpm_status_info["tpm_on_off"]
        except:
            self.logger.info(f"Tpms status not updated: Subrack data are not ready yet")
           

    def clearSubrackValues(self):
        with (self._subrack_lock_GUI):
            self.subrack_led.Colour = Led.Grey
            self.subrack_led.m_value = False
            for table in self.subrack_table:
                table.clearContents()

    
    def setupSubrackHdf5(self):
        default_app_dir = str(Path.home()) + "/.skalab/monitoring/subrack_monitor/"
        if not(self.tlm_hdf):
            if not self.profile['Subrack']['subrack_data_path'] == "":
                fname = self.profile['Subrack']['subrack_data_path']
                if not fname[-1] == "/":
                    fname = fname + "/"
                    if  os.path.exists(str(Path.home()) + fname) != True:
                        try:
                            os.makedirs(str(Path.home()) + fname)
                        except:
                            fname = default_app_dir
                fname += datetime.datetime.strftime(datetime.datetime.utcnow(), "monitor_subrack_%Y-%m-%d_%H%M%S.h5")
                self.tlm_hdf = h5py.File(str(Path.home()) + fname, 'a')
                return self.tlm_hdf
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
        if self.tlm_hdf:
            try:
                dt = h5py.special_dtype(vlen=str) 
                feature_names = np.array(str(subrack_tlm), dtype=dt) 
                self.tlm_hdf.create_dataset(datetime, data=feature_names)

            except:
                self.logger.error(f"WRITE SUBRACK TELEMETRY ERROR at {datetime}")            

    
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
                    self.tlm_hdf_tpm_monitor.close()
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
        window.signal_update_tpm_attribute.connect(window.unfoldTpmAttribute)
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
