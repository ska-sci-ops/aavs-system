#!/usr/bin/env python
"""

   The SKA in LAB Project

   Easy and Quick Access Monitor and Control the SKA-LFAA Devices in Lab based on aavs-system

   Supported Devices are:

      - TPM_1_2 and TPM_1_6
      - Subrack with WebServer API

"""

__copyright__ = "Copyright 2023, Istituto di RadioAstronomia, Radiotelescopi di Medicina, INAF, Italy"
__author__ = "Andrea Mattana"
__credits__ = ["Andrea Mattana"]
__license__ = "BSD3"
__version__ = "2.0.5"
__release__ = "2023-10-03"
__maintainer__ = "Andrea Mattana"

import gc
import shutil
import sys
import os
import threading
import time
from threading import Thread

import numpy as np
import configparser
from PyQt5 import QtCore, QtGui, QtWidgets, uic

from skalab_live import Live
from skalab_playback import Playback
from skalab_subrack import Subrack
from skalab_monitor import Monitor
from skalab_station import SkalabStation
from skalab_utils import parse_profile, getTextFromFile
from skalab_base import ConfWizard
from pathlib import Path
import logging
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)


default_app_dir = str(Path.home()) + "/.skalab/"
default_profile = "Default"
profile_filename = "skalab.ini"

COLORI = ["b", "g"]


def runWizard(fullpath=""):
    if not os.path.exists(fullpath):
        conf = configparser.ConfigParser()
        conf['Base'] = {'subrack': "Default",
                        'live': "Default",
                        'playback': "Default",
                        'station': "Default"}
        if not os.path.exists(default_app_dir):
            print("\nCouldn't find SKALAB configuration files directory,\nGenerating a new one in " + default_app_dir)
            os.makedirs(default_app_dir)
        conf_path = default_app_dir + profile
        if not os.path.exists(conf_path):
            os.makedirs(conf_path)
        print("\nGenerating a new SKALAB default configuration file: " + fullpath)
        conf_path = conf_path + "/skalab.ini"
        with open(conf_path, 'w') as configfile:
            conf.write(configfile)
    profiles = parse_profile(fullpath)

    msgBox = QtWidgets.QMessageBox()
    msgBox.setText("\n\n                       Welcome to SKALAB v." + __version__ + "                     " +
                   "\n\n\n   the WIZARD assistant will help you generating the            " +
                   "\n                SKALAB Modules configuration files                 " +
                   "\n\n   EDIT the proposed configuration for each module             " +
                   "\n\n    click DONE to validate it and go to the next step             \n\n")
    msgBox.setWindowTitle("SKALAB Setup")
    msgBox.setIcon(QtWidgets.QMessageBox.Information)
    # msgBox.setWindowIcon(QtGui.QIcon('Pictures/wizard.png'))
    msgBox.exec_()
    if profiles.sections():
        for n, module_name in enumerate(profiles['Base']):
            # if not os.path.exists(default_app_dir + profiles['Base'][module_name] + "/" + module_name + ".ini"):
            wg = ConfWizard(App=module_name, Profile=profiles['Base'][module_name], Path=default_app_dir,
                            msg="Step %d/%d" % (n + 1, len(profiles['Base'])))
            wg.wg.show()
            wg.wg.raise_()
            done = app.exec_()
            wg.wg.close()
            del wg
            gc.collect()


class SkaLab(QtWidgets.QMainWindow):
    """ Main UI Window class """

    def __init__(self, uiFile, profile="Default"):
        """ Initialise main window """
        super(SkaLab, self).__init__()
        # Load window file
        self.wg = uic.loadUi(uiFile)
        self.setCentralWidget(self.wg)
        self.resize(1210, 970)
        self.setWindowTitle("The SKA in LAB Project")
        self.profile_name = ""
        self.profile_file = ""
        self.load_profile(profile)
        self.updateProfileCombo(current=self.profile_name)

        self.tabStationIndex = 1
        self.tabSubrackIndex = 2
        self.tabLiveIndex = 3
        self.tabPlayIndex = 4

        self.pic_ska = QtWidgets.QLabel(self.wg.qwpics)
        self.pic_ska.setGeometry(1, 1, 1111, 401)
        self.pic_ska.setPixmap(QtGui.QPixmap(os.getcwd() + "/Pictures/bungarra.png"))

        self.pic_ska_auth = QtWidgets.QLabel(self.wg.qwpics_authpic)
        self.pic_ska_auth.setGeometry(0, 0, 80, 78)
        self.pic_ska_auth.setPixmap(QtGui.QPixmap(os.getcwd() + "/Pictures/People/AMattana.png"))

        self.pic_ska_help = QtWidgets.QLabel(self.wg.qwpics_help)
        self.pic_ska_help.setGeometry(1, 1, 380, 118)
        self.pic_ska_help.setPixmap(QtGui.QPixmap(os.getcwd() + "/Pictures/ska_inaf_logo.png"))

        self.wg.qlabel_sw2_version.setText(__version__)
        self.wg.qlabel_sw2_release.setText(__release__)
        self.wg.qlabel_sw2_author.setText(__author__)

        # Instantiating Station Tab. This must be always done as first
        QtWidgets.QTabWidget.setTabVisible(self.wg.qtabMain, self.tabStationIndex, True)
        self.wgStationLayout = QtWidgets.QVBoxLayout()
        self.wgStation = SkalabStation(uiFile="Gui/skalab_station.ui", size=[1190, 936],
                           profile=self.profile['Base']['station'],
                           swpath=default_app_dir)
        self.wgStationLayout.addWidget(self.wgStation)
        self.wg.qwStation.setLayout(self.wgStationLayout)
        self.config_file = self.wgStation.profile['Station']['station_file']

        QtWidgets.QTabWidget.setTabVisible(self.wg.qtabMain, self.tabLiveIndex, True)
        self.wgLiveLayout = QtWidgets.QVBoxLayout()
        self.wgLive = Live(uiFile="Gui/skalab_live.ui", size=[1190, 936],
                           profile=self.profile['Base']['live'],
                           swpath=default_app_dir)
        self.wgLive.signalTemp.connect(self.wgLive.updateTempPlot)
        self.wgLive.signalRms.connect(self.wgLive.updateRms)
        self.wgLiveLayout.addWidget(self.wgLive)
        self.wg.qwLive.setLayout(self.wgLiveLayout)

        QtWidgets.QTabWidget.setTabVisible(self.wg.qtabMain, self.tabPlayIndex, True)
        self.wgPlayLayout = QtWidgets.QVBoxLayout()
        self.wgPlay = Playback(self.config_file, "Gui/skalab_playback.ui", size=[1190, 936],
                               profile=self.profile['Base']['playback'],
                               swpath=default_app_dir)
        self.wgPlayLayout.addWidget(self.wgPlay)
        self.wg.qwPlay.setLayout(self.wgPlayLayout)

        QtWidgets.QTabWidget.setTabVisible(self.wg.qtabMain, self.tabSubrackIndex, True)
        self.wgSubrackLayout = QtWidgets.QVBoxLayout()
        self.wgSubrack = Subrack(uiFile="Gui/skalab_subrack.ui", size=[1190, 936],
                                 profile=self.profile['Base']['subrack'],
                                 swpath=default_app_dir)
        self.wgSubrackLayout.addWidget(self.wgSubrack)
        self.wg.qwSubrack.setLayout(self.wgSubrackLayout)
        self.wgSubrack.signalTlm.connect(self.wgSubrack.updateTlm)
        # self.wgSubrack.signal_to_monitor.connect(self.wgMonitor.read_subrack_attribute)
        # self.wgSubrack.signal_to_monitor_for_tpm.connect(self.wgMonitor.tpm_status_changed)

        self.show()
        self.load_events()

        self.station_name = ""
        self.folder = ""
        self.nof_files = 0
        self.nof_tiles = 0
        self.data_tiles = []
        self.nof_antennas = 0
        self.bitfile = ""
        self.truncation = 0
        self.resolutions = 2 ** np.array(range(16)) * (800000.0 / 2 ** 15)
        self.rbw = 100
        self.avg = 2 ** self.rbw
        self.nsamples = int(2 ** 15 / self.avg)
        self.RBW = (self.avg * (400000.0 / 16384.0))
        self.asse_x = np.arange(self.nsamples/2 + 1) * self.RBW * 0.001

        self.input_list = np.arange(1, 17)

        self.tiles = []
        self.data = []
        self.power = {}
        self.raw = {}
        self.rms = {}
        self.populate_help()
        self.stopThreads = False
        self.procUpdate = Thread(target=self.procUpdateChildren)
        self.procUpdate.start()
        # print("Start Thread Skalab procUpdateChildren")

    def load_events(self):
        self.wg.qbutton_profile_save.clicked.connect(lambda: self.save_profile(self.wg.qcombo_profiles.currentText()))
        self.wg.qbutton_profile_saveas.clicked.connect(lambda: self.save_as_profile())
        self.wg.qbutton_profile_load.clicked.connect(lambda: self.reload_profile(self.wg.qcombo_profiles.currentText()))
        self.wg.qbutton_profile_delete.clicked.connect(lambda: self.delete_profile(self.wg.qcombo_profiles.currentText()))

    def procUpdateChildren(self):
        while True:
            # If a connection to the Subrack has been estabilished update the list of TPM IPs
            if self.wgSubrack.updateRequest:
                self.wgSubrack.updateRequest = False
                #print("RECEIVED TPM IPs: ", self.wgSubrack.tpm_ips)
                self.wgStation.tpm_ips_from_subrack = self.wgSubrack.tpm_ips.copy()
                self.wgLive.setupNewTilesIPs(self.wgSubrack.tpm_ips)

            if self.wgLive.updateRequest:
                pass
            if self.wgStation.updateRequest:
                pass
            if self.stopThreads:
                #print("Stopping Thread SKALAB Update children")
                break
            time.sleep(1)

    def load_profile(self, profile):
        if not profile == "":
            self.profile = []
            fullpath = default_app_dir + profile + "/" + profile_filename
            if os.path.exists(fullpath):
                print("Loading Skalab Profile: " + profile + " (" + fullpath + ")")
            else:
                print("\nThe Skalab Profile does not exist.\nGenerating a new one in " + fullpath)
                self.make_profile(profile=profile)
            self.profile = parse_profile(fullpath)
            self.profile_name = profile
            self.profile_file = fullpath
            self.wg.qline_profile.setText(fullpath)

            if not self.profile.sections():
                msgBox = QtWidgets.QMessageBox()
                msgBox.setText("Cannot find this profile!")
                msgBox.setWindowTitle("Error!")
                msgBox.exec_()
            else:
                # self.config_file = self.profile['Init']['station_file']
                self.populate_table_profile()

    def reload_profile(self, profile):
        self.load_profile(profile=profile)
        if self.profile.sections():
            if self.profile['Base']['subrack']:
                self.wgSubrack.load_profile(App="subrack", Profile=self.profile['Base']['subrack'], Path=default_app_dir)
            # if self.profile['Base']['monitor']:
            #     self.wgMonitor.load_profile(App="monitor", Profile=self.profile['Base']['monitor'], Path=default_app_dir)
            if self.profile['Base']['live']:
                self.wgLive.load_profile(App="live", Profile=self.profile['Base']['live'], Path=default_app_dir)
            if self.profile['Base']['playback']:
                self.wgPlay.load_profile(App="playback", Profile=self.profile['Base']['playback'], Path=default_app_dir)

    def delete_profile(self, profile):
        if os.path.exists(default_app_dir + profile):
            shutil.rmtree(default_app_dir + profile)
        self.updateProfileCombo(current="")
        self.load_profile(self.wg.qcombo_profiles.currentText())

    def updateProfileCombo(self, current):
        profiles = []
        for d in os.listdir(default_app_dir):
            if os.path.exists(default_app_dir + d + "/skalab.ini"):
                profiles += [d]
        if profiles:
            self.wg.qcombo_profiles.clear()
            for n, p in enumerate(profiles):
                self.wg.qcombo_profiles.addItem(p)
                if current == p:
                    self.wg.qcombo_profiles.setCurrentIndex(n)

    def populate_help(self, uifile="Gui/skalab_main.ui"):
        with open(uifile) as f:
            data = f.readlines()
        helpkeys = [d[d.rfind('name="Help_'):].split('"')[1] for d in data if 'name="Help_' in d]
        for k in helpkeys:
            self.wg.findChild(QtWidgets.QTextEdit, k).setHtml(getTextFromFile(k.replace("_", "/")+".html"))

    def populate_table_profile(self):
        #self.wg.qtable_profile = QtWidgets.QTableWidget(self.wg.qtabMain)
        #self.wg.qtable_profile.setGeometry(QtCore.QRect(20, 575, 461, 351))
        self.wg.qtable_profile.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        self.wg.qtable_profile.setObjectName("qtable_profile")
        self.wg.qtable_profile.setColumnCount(1)
        nrows = len(self.profile.sections())
        for i in self.profile.sections():
            nrows = nrows + len(self.profile[i].keys()) + 1
        self.wg.qtable_profile.setRowCount(nrows)

        # Header Horizontal
        item = QtWidgets.QTableWidgetItem()
        item.setTextAlignment(QtCore.Qt.AlignLeading | QtCore.Qt.AlignVCenter)
        item.setFlags(item.flags() ^ QtCore.Qt.ItemIsEditable)
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        item.setFont(font)
        self.wg.qtable_profile.setHorizontalHeaderItem(0, item)
        item = self.wg.qtable_profile.horizontalHeaderItem(0)
        item.setText("Profile: " + self.profile_name)
        __sortingEnabled = self.wg.qtable_profile.isSortingEnabled()
        self.wg.qtable_profile.setSortingEnabled(False)

        row = 0
        for k in self.profile.sections():
            # Empty Row
            item = QtWidgets.QTableWidgetItem()
            item.setFlags(item.flags() ^ QtCore.Qt.ItemIsEditable)
            self.wg.qtable_profile.setVerticalHeaderItem(row, item)
            item = self.wg.qtable_profile.verticalHeaderItem(row)
            item.setFlags(item.flags() ^ QtCore.Qt.ItemIsEditable)
            item.setText(" ")
            item = QtWidgets.QTableWidgetItem()
            item.setText(" ")
            self.wg.qtable_profile.setItem(row, 0, item)
            row = row + 1

            item = QtWidgets.QTableWidgetItem()
            font = QtGui.QFont()
            font.setBold(True)
            font.setWeight(75)
            item.setFont(font)
            item.setText("[" + k + "]")
            item.setFlags(item.flags() ^ QtCore.Qt.ItemIsEditable)
            self.wg.qtable_profile.setVerticalHeaderItem(row, item)
            row = row + 1

            for s in self.profile[k].keys():
                item = QtWidgets.QTableWidgetItem()
                item.setFlags(item.flags() ^ QtCore.Qt.ItemIsEditable)
                self.wg.qtable_profile.setVerticalHeaderItem(row, item)
                item = self.wg.qtable_profile.verticalHeaderItem(row)
                item.setText(s)
                item = QtWidgets.QTableWidgetItem()
                item.setText(self.profile[k][s])
                item.setFlags(item.flags() ^ QtCore.Qt.ItemIsEditable)
                self.wg.qtable_profile.setItem(row, 0, item)
                row = row + 1

        self.wg.qtable_profile.horizontalHeader().setDefaultSectionSize(365)
        self.wg.qtable_profile.setSortingEnabled(__sortingEnabled)

    def make_profile(self, profile="Default", subrack="Default", live="Default", playback="Default", station="Default"):
        conf = configparser.ConfigParser()
        conf['Base'] = {'subrack': subrack,
                        'live': live,
                        'playback': playback,
                        'station': station}
        #conf['Init'] = {'station_file': config}
        #conf['Extras'] = {'text_editor': self.text_editor}
        if not os.path.exists(default_app_dir):
            os.makedirs(default_app_dir)
        conf_path = default_app_dir + profile
        if not os.path.exists(conf_path):
            os.makedirs(conf_path)
        conf_path = conf_path + "/skalab.ini"
        with open(conf_path, 'w') as configfile:
            conf.write(configfile)

    def setAutoload(self, load_profile=""):
        conf = configparser.ConfigParser()
        conf['Base'] = {'autoload_profile': load_profile}
        if not os.path.exists(default_app_dir):
            os.makedirs(default_app_dir)
        conf_path = default_app_dir + "/startup.ini"
        with open(conf_path, 'w') as configfile:
            conf.write(configfile)

    def save_profile(self, this_profile, reload=True):
        self.make_profile(profile=this_profile,
                          subrack=self.wgSubrack.profile['Base']['profile'],
                          live=self.wgLive.profile['Base']['profile'],
                          playback=self.wgPlay.profile['Base']['profile'],
                          station=self.wgStation.profile['Base']['profile']) #  ,
                          #  config=self.config_file)
        if reload:
            self.load_profile(profile=this_profile)

    def save_as_profile(self):
        text, ok = QtWidgets.QInputDialog.getText(self, 'Profiles', 'Enter a Profile name:')
        if ok:
            self.save_profile(this_profile=text)
            self.updateProfileCombo(current=text)
            #self.load_profile(profile=text)

    def closeEvent(self, event):
        result = QtWidgets.QMessageBox.question(self, "Confirm Exit...", "Are you sure you want to exit ?",
                                                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        event.ignore()

        if result == QtWidgets.QMessageBox.Yes:
            event.accept()
            # print("Total Threads to close: ", threading.activeCount())
            self.stopThreads = True
            self.wgLive.cmdClose()
            self.wgStation.cmdClose()
            self.wgSubrack.cmdClose()
            self.wgPlay.cmdClose()
            time.sleep(1)
            # print("Still active Threads: ", threading.activeCount())
            if self.wg.qradio_autosave.isChecked():
                self.save_profile(this_profile=self.profile_name, reload=False)

            if self.wg.qradio_autoload.isChecked():
                self.setAutoload(load_profile=self.profile_name)
            else:
                self.setAutoload()


if __name__ == "__main__":
    from optparse import OptionParser
    from sys import argv, stdout

    app = QtWidgets.QApplication(sys.argv)
    parser = OptionParser(usage="usage: %skalab [options]")
    parser.add_option("--wizard", action="store_true", dest="wizard",
                      default=False, help="Run the configuration Wizard")
    (opt, args) = parser.parse_args(argv[1:])

    profile = "Default"
    if os.path.exists(default_app_dir + "startup.ini"):
        autoload = parse_profile(default_app_dir + "startup.ini")
        if autoload.sections():
            profile = autoload['Base']["autoload_profile"]

    fullpath = default_app_dir + profile + "/" + profile_filename

    if (not os.path.exists(fullpath)) or opt.wizard:
        runWizard(fullpath=fullpath)

    print("\nStarting SKALAB...\n")
    window = SkaLab("Gui/skalab_main.ui", profile=profile)
    sys.exit(app.exec_())
