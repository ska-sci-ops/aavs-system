# -*- coding: utf-8 -*-
#
# This file is part of the SKA Low MCCS project
#
#
#
# Distributed under the terms of the GPL license.
# See LICENSE.txt for more info.
"""
Hardware functions for monitoring of TPM hardware health status.

This depends heavily on the
pyfabil low level software and specific hardware module plugins.
"""

import time
from pyfabil.base.definitions import LibraryError, BoardError


def health_monitoring_compatible(func):
    """
    Decorator method to check if provided firmware supports TPM health monitoring.
    Achieved by attempting to access a register which was added for TPM health monitoring.
    Bitstreams generated prior to ~03/2023 will not support TPM health monitoring.
    """
    def inner_func(self):
        try:
            self['fpga1.pps_manager.pps_errors']
        except Exception as e:  # noqa: F841
            raise LibraryError(f"TPM Health Monitoring not supported by FPGA firmware!")
        return func(self)
    return inner_func


def communication_check(func):
    """
    Decorator method to check if communication is established between FPGA and CPLD.
    Non-destructive version of tile tpm_communication_check.
    """
    def inner_func(self):
        try:
            magic0 = self[0x4]
        except Exception as e:  # noqa: F841
            raise BoardError(f"Not possible to communicate with the FPGA0: " + str(e))
        try:
            magic1 = self[0x10000004]
        except Exception as e:  # noqa: F841
            raise BoardError(f"Not possible to communicate with the FPGA1: " + str(e))
        if magic0 == magic1 == 0xA1CE55AD:
            return func(self)
        else:
            if magic0 != 0xA1CE55AD:
                self.logger.error(f"FPGA0 magic number is not correct {hex(magic0)}, expected: 0xA1CE55AD")
            if magic1 != 0xA1CE55AD:
                self.logger.error(f"FPGA1 magic number is not correct {hex(magic1)}, expected: 0xA1CE55AD")
            return
    return inner_func


class TileHealthMonitor:
    """
    Tile Health Monitor Mixin Class, must be inherited by Tile Class
    """

    @communication_check
    @health_monitoring_compatible
    def enable_health_monitoring(self):
        # For use with get_health_status and clear_health_status
        # Enable anything that requires an enable
        self.enable_clock_monitoring()
        return

    @communication_check
    @health_monitoring_compatible
    def get_health_status(self):
        """
        Returns the current value of all TPM monitoring points.
        https://confluence.skatelescope.org/x/nDhED
        """
        health_dict = {
            'temperature': self.get_fpga_temperature(fpga_id=None), 
            'voltage': self.get_voltage(fpga_id=None, voltage_name=None),
            'current': self.get_current(fpga_id=None, current_name=None),
            'alarms' : None if self.tpm_version() == "tpm_v1_2" else self.tpm.get_global_status_alarms(),
            'timing': {
                'clocks': self.check_clock_status(fpga_id=None, clock_name=None),
                'clock_managers': self.check_clock_manager_status(fpga_id=None, name=None),
                'pps': {
                    'status': self.check_pps_status(fpga_id=None)
                }
            },
            'io': {
                'jesd_if': {
                    'link_status' : self.check_jesd_link_status(fpga_id=None, core_id=None),
                    'lane_error_count': self.check_jesd_lane_error_counter(fpga_id=None, core_id=None),
                    'lane_status': self.check_jesd_lane_status(fpga_id=None, core_id=None),
                    'resync_count': self.check_jesd_resync_counter(fpga_id=None, show_result=False),
                    'qpll_status': self.check_jesd_qpll_status(fpga_id=None, show_result=False)
                },
                'ddr_if': {
                    'initialisation': self.check_ddr_initialisation(fpga_id=None),
                    'reset_counter': self.check_ddr_reset_counter(fpga_id=None, show_result=False)
                },
                'f2f_if': {
                    'pll_status': self.check_f2f_pll_status(core_id=None, show_result=False)
                },
                'udp_if': {
                    'arp': self.check_udp_arp_table_status(fpga_id=None, show_result=False),
                    'status': self.check_udp_status(fpga_id=None),
                    'crc_error_count': self.check_udp_crc_error_counter(fpga_id=None),
                    'bip_error_count': self.check_udp_bip_error_counter(fpga_id=None),
                    'linkup_loss_count': self.check_udp_linkup_loss_counter(fpga_id=None, show_result=False)
                }
            }, 
            'dsp': {
                'tile_beamf': self.check_tile_beamformer_status(fpga_id=None),
                'station_beamf': {
                    'status' : self.check_station_beamformer_status(fpga_id=None),
                    'ddr_parity_error_count': self.check_ddr_parity_error_counter(fpga_id=None)
                }
            }
        }
        health_dict['temperature']['board'] = round(self.get_temperature(), 2)
        return health_dict
    
    @communication_check
    @health_monitoring_compatible
    def clear_health_status(self):
        self.clear_clock_status(fpga_id=None, clock_name=None)
        self.clear_clock_manager_status(fpga_id=None, name=None)
        self.clear_pps_status(fpga_id=None)
        self.clear_jesd_error_counters(fpga_id=None)
        self.clear_ddr_reset_counter(fpga_id=None)
        self.clear_f2f_pll_lock_loss_counter(core_id=None)
        self.clear_udp_status(fpga_id=None)
        self.clear_tile_beamformer_status(fpga_id=None)
        self.clear_station_beamformer_status(fpga_id=None)
        return

    def get_health_acceptance_values(self):
        EXP_TEMP = {
            "board": { "min": 10.00, "max": 68.00},
            "FPGA0": { "min": 10.00, "max": 95.00},
            "FPGA1": { "min": 10.00, "max": 95.00}
        }
        # TPM 1.2 min and max ranges are estimated based on 5 or 8% tolerance
        # See https://confluence.skatelescope.org/x/nDhED
        EXP_VOLTAGE_TPM_V1_2 = {
            "5V0"         : { "min": 4.750, "max": 5.250},
            "FPGA0_CORE"  : { "min": 0.900, "max": 1.000},
            "FPGA1_CORE"  : { "min": 0.900, "max": 1.000},
            "MGT_AV"      : { "min": 0.850, "max": 0.950}, # Exp 0.90V instead of 1.0V
            "MGT_AVTT"    : { "min": 1.140, "max": 1.260},
            "SW_AVDD1"    : { "min": 1.560, "max": 1.730},
            "SW_AVDD2"    : { "min": 2.560, "max": 2.840},
            "SW_AVDD3"    : { "min": 3.320, "max": 3.680},
            "VCC_AUX"     : { "min": 1.710, "max": 1.890},
            "VIN"         : { "min": 11.40, "max": 12.60, "skip": True},  # TODO: add support for this measurement
            "VM_ADA0"     : { "min": 3.030, "max": 3.560, "skip": not self.tpm.adas_enabled},
            "VM_ADA1"     : { "min": 3.030, "max": 3.560, "skip": not self.tpm.adas_enabled},
            "VM_AGP0"     : { "min": 0.900, "max": 1.060},
            "VM_AGP1"     : { "min": 0.900, "max": 1.060},
            "VM_AGP2"     : { "min": 0.900, "max": 1.060},
            "VM_AGP3"     : { "min": 0.900, "max": 1.060},
            "VM_CLK0B"    : { "min": 3.030, "max": 3.560},
            "VM_DDR0_VREF": { "min": 0.620, "max": 0.730},
            "VM_DDR0_VTT" : { "min": 0.620, "max": 0.730},
            "VM_FE0"      : { "min": 3.220, "max": 3.780},
            "VM_MAN1V2"   : { "min": 1.100, "max": 1.300, "skip": True}, # Not currently turned on
            "VM_MAN2V5"   : { "min": 2.300, "max": 2.700},
            "VM_MAN3V3"   : { "min": 3.030, "max": 3.560},
            "VM_MGT0_AUX" : { "min": 1.650, "max": 1.940},
            "VM_PLL"      : { "min": 3.030, "max": 3.560},
            "VM_ADA3"     : { "min": 3.030, "max": 3.560, "skip": not self.tpm.adas_enabled},
            "VM_DDR1_VREF": { "min": 0.620, "max": 0.730},
            "VM_DDR1_VTT" : { "min": 0.620, "max": 0.730},
            "VM_AGP4"     : { "min": 0.900, "max": 1.060},
            "VM_AGP5"     : { "min": 0.900, "max": 1.060},
            "VM_AGP6"     : { "min": 0.900, "max": 1.060},
            "VM_AGP7"     : { "min": 0.900, "max": 1.060},
            "VM_FE1"      : { "min": 3.220, "max": 3.780},
            "VM_DDR_VDD"  : { "min": 1.240, "max": 1.460},
            "VM_SW_DVDD"  : { "min": 1.520, "max": 1.780},
            "VM_MGT1_AUX" : { "min": 1.650, "max": 1.940},
            "VM_ADA2"     : { "min": 3.030, "max": 3.560, "skip": not self.tpm.adas_enabled},
            "VM_SW_AMP"   : { "min": 3.220, "max": 3.780, "skip": True}, # Not currently turned on
            "VM_CLK1B"    : { "min": 3.030, "max": 3.560}
        }
        # TPM 1.6 min and max ranges are taken from factory acceptance testing
        # See https://confluence.skatelescope.org/x/nDhED
        EXP_VOLTAGE_TPM_V1_6 = {
            "VREF_2V5"    : { "min": 2.370, "max": 2.630, "skip": True}, # TODO: add support for this measurement
            "MGT_AVCC"    : { "min": 0.850, "max": 0.950},
            "MGT_AVTT"    : { "min": 1.140, "max": 1.260},
            "SW_AVDD1"    : { "min": 1.040, "max": 1.160},
            "SW_AVDD2"    : { "min": 2.180, "max": 2.420},
            "AVDD3"       : { "min": 2.370, "max": 2.600},
            "MAN_1V2"     : { "min": 1.140, "max": 1.260},
            "DDR0_VREF"   : { "min": 0.570, "max": 0.630},
            "DDR1_VREF"   : { "min": 0.570, "max": 0.630},
            "VM_DRVDD"    : { "min": 1.710, "max": 1.890},
            "VIN"         : { "min": 11.40, "max": 12.60},
            "MON_3V3"     : { "min": 3.130, "max": 3.460, "skip": True}, # Can be removed once MCCS-1348 is complete
            "MON_1V8"     : { "min": 1.710, "max": 1.890, "skip": True}, # Can be removed once MCCS-1348 is complete
            "MON_5V0"     : { "min": 4.690, "max": 5.190},
            "VM_ADA0"     : { "min": 3.040, "max": 3.560, "skip": not self.tpm.adas_enabled},
            "VM_ADA1"     : { "min": 3.040, "max": 3.560, "skip": not self.tpm.adas_enabled},
            "VM_AGP0"     : { "min": 0.840, "max": 0.990},
            "VM_AGP1"     : { "min": 0.840, "max": 0.990},
            "VM_AGP2"     : { "min": 0.840, "max": 0.990},
            "VM_AGP3"     : { "min": 0.840, "max": 0.990},
            "VM_CLK0B"    : { "min": 3.040, "max": 3.560},
            "VM_DDR0_VTT" : { "min": 0.550, "max": 0.650},
            "VM_FE0"      : { "min": 3.220, "max": 3.780, "skip": not self.preadus_enabled},
            "VM_MGT0_AUX" : { "min": 1.660, "max": 1.940},
            "VM_PLL"      : { "min": 3.040, "max": 3.560},
            "VM_AGP4"     : { "min": 0.840, "max": 0.990},
            "VM_AGP5"     : { "min": 0.840, "max": 0.990, "skip": True}, # Can be removed once MCCS-1348 is complete
            "VM_AGP6"     : { "min": 0.840, "max": 0.990},
            "VM_AGP7"     : { "min": 0.840, "max": 0.990},
            "VM_CLK1B"    : { "min": 3.040, "max": 3.560},
            "VM_DDR1_VDD" : { "min": 1.100, "max": 1.300},
            "VM_DDR1_VTT" : { "min": 0.550, "max": 0.650},
            "VM_DVDD"     : { "min": 1.010, "max": 1.190},
            "VM_FE1"      : { "min": 3.220, "max": 3.780, "skip": not self.preadus_enabled},
            "VM_MGT1_AUX" : { "min": 1.660, "max": 1.940},
            "VM_SW_AMP"   : { "min": 3.220, "max": 3.780},
        }
        # TPM 1.2 min and max ranges are provisional
        # See https://confluence.skatelescope.org/x/nDhED
        EXP_CURRENT_TPM_V1_2 = {
            "ACS_5V0_VI": { "min": 0.000, "max": 25.00, "skip": True}, # TODO: add support for this measurement
            "ACS_FE0_VI": { "min": 0.000, "max": 4.000, "skip": True}, # known defective
            "ACS_FE1_VI": { "min": 0.000, "max": 4.000, "skip": True}  # known defective
        }
        # TPM 1.6 min and max ranges are taken from factory acceptance testing
        # See https://confluence.skatelescope.org/x/nDhED
        EXP_CURRENT_TPM_V1_6 = {
            "FE0_mVA"     : { "min": 0.000, "max": 2.270},
            "FE1_mVA"     : { "min": 0.000, "max": 2.380}
        }
        return (EXP_TEMP, EXP_VOLTAGE_TPM_V1_2, EXP_CURRENT_TPM_V1_2) if self.tpm_version() == "tpm_v1_2" else (EXP_TEMP, EXP_VOLTAGE_TPM_V1_6, EXP_CURRENT_TPM_V1_6)

    def fpga_gen(self, fpga_id):
        return range(len(self.tpm.tpm_test_firmware)) if fpga_id is None else [fpga_id]

    def get_fpga_temperature(self, fpga_id=None):
        """
        Get FPGA temperature.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :return: FPGA temperature
        :rtype: dict
        """
        temperature_dict = {}
        for fpga in self.fpga_gen(fpga_id):
            if self.is_programmed():
                temperature_dict[f'FPGA{fpga}'] = round(self.tpm.tpm_sysmon[fpga].get_fpga_temperature(), 2)
            else:
                temperature_dict[f'FPGA{fpga}'] = 0
        return temperature_dict
    
    def get_available_voltages(self, fpga_id=None):
        """
        Get list of available voltage measurements for TPM.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :return: TPM voltage names
        :rtype: list
        """
        available_voltages = []
        # LASC Plugin TPM 1.2
        if hasattr(self.tpm, 'tpm_lasc'):
            available_voltages.extend(self.tpm.tpm_lasc[0].get_available_voltages())
        # MCU Plugin TPM 1.6
        if hasattr(self.tpm, 'tpm_monitor'):
            available_voltages.extend(self.tpm.tpm_monitor[0].get_available_voltages())
        # System Monitor Plugin
        for fpga in self.fpga_gen(fpga_id):
            available_voltages.extend(self.tpm.tpm_sysmon[fpga].get_available_voltages())
        return available_voltages

    def get_voltage(self, fpga_id=None, voltage_name=None):
        """
        Get voltage measurements for TPM.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param voltage_name: Specify name of voltage, None for all voltages
        :type voltage_name: string

        :return: TPM voltages
        :rtype: dict
        """
        voltage_dict = {}
        # LASC Plugin TPM 1.2
        if hasattr(self.tpm, 'tpm_lasc'):
            voltage_dict.update(self.tpm.tpm_lasc[0].get_voltage(voltage_name))
        # MCU Plugin TPM 1.6
        if hasattr(self.tpm, 'tpm_monitor'):
            voltage_dict.update(self.tpm.tpm_monitor[0].get_voltage(voltage_name))
        # System Monitor Plugin
        for fpga in self.fpga_gen(fpga_id):
            voltage_dict.update(self.tpm.tpm_sysmon[fpga].get_voltage(voltage_name))
        if voltage_name is not None and not voltage_dict:
            raise LibraryError(f"No voltage named '{voltage_name.upper()}' \n Options are {', '.join(self.get_available_voltages(fpga_id))} (not case sensitive)")
        return voltage_dict

    def get_available_currents(self, fpga_id=None):
        """
        Get list of available current measurements for TPM.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :return: TPM current names
        :rtype: list
        """
        available_currents = []
        # LASC Plugin TPM 1.2
        if hasattr(self.tpm, 'tpm_lasc'):
            available_currents.extend(self.tpm.tpm_lasc[0].get_available_currents())
        # MCU Plugin TPM 1.6
        if hasattr(self.tpm, 'tpm_monitor'):
            available_currents.extend(self.tpm.tpm_monitor[0].get_available_currents())
        # System Monitor Plugin
        for fpga in self.fpga_gen(fpga_id):
            available_currents.extend(self.tpm.tpm_sysmon[fpga].get_available_currents())
        return available_currents

    def get_current(self, fpga_id=None, current_name=None):
        """
        Get current measurements for TPM.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param current_name: Specify name of current, None for all currents
        :type current_name: string

        :return: TPM currents
        :rtype: dict
        """
        current_dict = {}
        # LASC Plugin TPM 1.2
        if hasattr(self.tpm, 'tpm_lasc'):
            current_dict.update(self.tpm.tpm_lasc[0].get_current(current_name))
        # MCU Plugin TPM 1.6
        if hasattr(self.tpm, 'tpm_monitor'):
            current_dict.update(self.tpm.tpm_monitor[0].get_current(current_name))
        # System Monitor Plugin
        for fpga in self.fpga_gen(fpga_id):
            current_dict.update(self.tpm.tpm_sysmon[fpga].get_current(current_name))
        if current_name is not None and not current_dict:
            raise LibraryError(f"No current named '{current_name.upper()}' \n Options are {', '.join(self.get_available_currents(fpga_id))} (not case sensitive)")
        return current_dict
    
    def get_available_clocks_to_monitor(self):
        """
        :return: list of clock names available to be monitored
        :rtype list of string
        """
        if self.is_programmed():
            return self.tpm.tpm_clock_monitor[0].get_available_clocks_to_monitor()

    def enable_clock_monitoring(self, fpga_id=None, clock_name=None):
        """
        Enable clock monitoring of named TPM clocks
        Options 'jesd', 'ddr', 'udp'
        Input is non case sensitive
        An FPGA ID can be optionally specified to only enable monitoring on one FPGA

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param clock_name: Specify name of clock or None for all clocks
        :type clock_name: string
        """
        if self.is_programmed():
            for fpga in self.fpga_gen(fpga_id):
                    self.tpm.tpm_clock_monitor[fpga].enable_clock_monitoring(clock_name)
        return

    def disable_clock_monitoring(self, fpga_id=None, clock_name=None):
        """
        Disable clock monitoring of named TPM clocks
        Options 'jesd', 'ddr', 'udp'
        Input is non case sensitive
        An FPGA ID can be optionally specified to only disable monitoring on one FPGA

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param clock_name: Specify name of clock or None for all clocks
        :type clock_name: string
        """
        if self.is_programmed():
            for fpga in self.fpga_gen(fpga_id):
                self.tpm.tpm_clock_monitor[fpga].disable_clock_monitoring(clock_name)
        return
    
    def check_clock_status(self, fpga_id=None, clock_name=None):
        """
        Check status of named TPM clocks
        Options 'jesd', 'ddr', 'udp'
        Input is non case sensitive
        An FPGA ID can be optionally specified to only check status on one FPGA

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param clock_name: Specify name of clock or None for all clocks
        :type clock_name: string

        :return: True when Status is OK, no errors
        :rtype bool
        """
        if self.is_programmed():
            result = {}
            for fpga in self.fpga_gen(fpga_id):
                result[f'FPGA{fpga}'] = self.tpm.tpm_clock_monitor[fpga].check_clock_status(clock_name)
            return result
        return
    
    def clear_clock_status(self, fpga_id=None, clock_name=None):
        """
        Clear status of named TPM clocks
        Used to Clear error flags in FPGA Firmware
        Options 'jesd', 'ddr', 'udp'
        Input is non case sensitive
        An FPGA ID can be optionally specified to only clear status on one FPGA

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param clock_name: Specify name of clock or None for all clocks
        :type clock_name: string
        """
        if self.is_programmed():
            for fpga in self.fpga_gen(fpga_id):
                self.tpm.tpm_clock_monitor[fpga].clear_clock_status(clock_name)
        return    

    def check_clock_manager_status(self, fpga_id=None, name=None):
        """
        Check status of named TPM clock manager cores (MMCM Core).
        Reports the status of each MMCM lock and its lock loss counter.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param name: Specify name of clock manager (non case sensitive)
        :type name: string

        :return: Status and Counter values
        :rtype dict
        """
        status = {}
        for fpga in self.fpga_gen(fpga_id):
            status[f'FPGA{fpga}'] = self.tpm.tpm_clock_monitor[fpga].check_clock_manager_status(name)
        return status
    
    def clear_clock_manager_status(self, fpga_id=None, name=None):
        """
        Clear status of named TPM clock manager cores (MMCM Core).
        Used to reset MMCM lock loss counters.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param name: Specify name of clock manager (non case sensitive)
        :type name: string
        """
        for fpga in self.fpga_gen(fpga_id):
            self.tpm.tpm_clock_monitor[fpga].clear_clock_manager_status(name)
        return    

    def get_available_clock_managers(self):
        return self.tpm.tpm_clock_monitor[0].available_clock_managers

    def check_pps_status(self, fpga_id=None):
        """
        Check PPS is detected and error free.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :return: true if all OK
        :rtype: bool
        """
        status = []
        for fpga in self.fpga_gen(fpga_id):
            status.append(self.tpm.tpm_test_firmware[fpga].check_pps_status())
        return all(status)
        
    def clear_pps_status(self, fpga_id=None):
        """
        Clear PPS error flags.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer
        """
        status = []
        for fpga in self.fpga_gen(fpga_id):
            self.tpm.tpm_test_firmware[fpga].clear_pps_status()
        return

    def check_jesd_link_status(self, fpga_id=None, core_id=None):
        """
        Check if JESD204 lanes are synchronized.
        Checks the FPGA sync status register.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param core_id: Specify which JESD Core, 0,1, or None for both cores
        :type core_id: integer

        :return: true if all OK
        :rtype: bool
        """
        jesd_cores_per_fpga = len(self.tpm.tpm_jesd) // len(self.tpm.tpm_test_firmware)
        cores = range(jesd_cores_per_fpga) if core_id is None else [core_id]
        result = []
        for fpga in self.fpga_gen(fpga_id):
            for core in cores:
                idx = fpga * jesd_cores_per_fpga + core
                result.append(self.tpm.tpm_jesd[idx].check_sync_status())
        return all(result)

    def clear_jesd_error_counters(self, fpga_id=None):
        """
        Reset JESD error counters.
         - JESD Error Counter
         - JESD Resync Counter (shared between JESD cores)
         - JESD QPLL Lock Loss Counter (shared between JESD cores)

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer
        """
        jesd_cores_per_fpga = len(self.tpm.tpm_jesd) // len(self.tpm.tpm_test_firmware)
        cores = range(jesd_cores_per_fpga)
        for fpga in self.fpga_gen(fpga_id):
            for core in cores:
                idx = fpga * jesd_cores_per_fpga + core
                self.tpm.tpm_jesd[idx].clear_error_counters()
        return

    def check_jesd_lane_error_counter(self, fpga_id=None, core_id=None):
        """
        Check JESD204 lanes errors.
        Checks the FPGA link error counter register.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param core_id: Specify which JESD Core, 0,1, or None for both cores
        :type core_id: integer

        :return: true if all OK
        :rtype: bool
        """
        jesd_cores_per_fpga = len(self.tpm.tpm_jesd) // len(self.tpm.tpm_test_firmware)
        cores = range(jesd_cores_per_fpga) if core_id is None else [core_id]
        counter_dict = {}
        for fpga in self.fpga_gen(fpga_id):
            counter_dict[f'FPGA{fpga}'] = {}
            for core in cores:
                idx = fpga * jesd_cores_per_fpga + core
                counter_dict[f'FPGA{fpga}'][f'Core{core}'] = self.tpm.tpm_jesd[idx].check_link_error_counter()
        return counter_dict

    def check_jesd_lane_status(self, fpga_id=None, core_id=None):
        """
        Check JESD204 lanes errors.
        Checks the FPGA link error counter register.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param core_id: Specify which JESD Core, 0,1, or None for both cores
        :type core_id: integer

        :return: true if all error counters are 0
        :rtype: bool
        """
        jesd_cores_per_fpga = len(self.tpm.tpm_jesd) // len(self.tpm.tpm_test_firmware)
        cores = range(jesd_cores_per_fpga) if core_id is None else [core_id]
        errors = []
        for fpga in self.fpga_gen(fpga_id):
            for core in cores:
                idx = fpga * jesd_cores_per_fpga + core
                count_dict = self.tpm.tpm_jesd[idx].check_link_error_counter()
                errors.extend(list(count_dict.values()))
        return not any(errors) # Return True if all error counters are 0

    def check_jesd_resync_counter(self, fpga_id=None, show_result=True):
        """
        Check JESD204 for resync events.
        Checks the FPGA resync counter register (shared between JESD cores).

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param show_result: prints error counts on logger
        :type show_result: bool

        :return: counter values
        :rtype: dict
        """
        jesd_cores_per_fpga = len(self.tpm.tpm_jesd) // len(self.tpm.tpm_test_firmware)
        counts = {}
        for fpga in self.fpga_gen(fpga_id):
            idx = fpga * jesd_cores_per_fpga
            counts[f'FPGA{fpga}'] = self.tpm.tpm_jesd[idx].check_resync_counter(show_result)
        return counts # Return dict of counter values

    def check_jesd_qpll_status(self, fpga_id=None, show_result=True):
        """
        Check JESD204 current status and for loss of QPLL lock events.
        Checks the FPGA qpll lock and qpll lock loss counter registers (shared between JESD cores).

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param show_result: prints error counts on logger
        :type show_result: bool

        :return: current status and counter value tuple
        :rtype: dict
        """
        jesd_cores_per_fpga = len(self.tpm.tpm_jesd) // len(self.tpm.tpm_test_firmware)
        status = {}
        for fpga in self.fpga_gen(fpga_id):
            idx = fpga * jesd_cores_per_fpga
            lock_status = self.tpm.tpm_jesd[idx].check_qpll_lock_status()
            lock_loss_cnt = self.tpm.tpm_jesd[idx].check_qpll_lock_loss_counter(show_result)
            status[f'FPGA{fpga}'] = (lock_status, lock_loss_cnt)
        return status # Return dict of tuple (current status and counter values)

    def check_ddr_initialisation(self, fpga_id=None):
        """
        Check whether DDR has initialised.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :return: true if all OK
        :rtype: bool
        """
        result = []
        for fpga in self.fpga_gen(fpga_id):
            result.append(self.tpm.tpm_test_firmware[fpga].check_ddr_initialisation())
        return all(result)
    
    def check_ddr_reset_counter(self, fpga_id=None, show_result=True):
        """
        Check status of DDR user reset counter - increments each falling edge 
        of the DDR generated user logic reset.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param show_result: prints error counts on logger
        :type show_result: bool

        :return: counter values
        :rtype: dict
        """
        counts = {}
        for fpga in self.fpga_gen(fpga_id):
            counts[f'FPGA{fpga}'] = self.tpm.tpm_test_firmware[fpga].check_ddr_user_reset_counter(show_result)
        return counts # Return dict of counter values
    
    def clear_ddr_reset_counter(self, fpga_id=None):
        """
        Reset value of DDR user reset counter.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer
        """
        for fpga in self.fpga_gen(fpga_id):
            self.tpm.tpm_test_firmware[fpga].clear_ddr_user_reset_counter()
        return

    def check_ddr_parity_error_counter(self, fpga_id=None):
        """
        Check status of DDR parity error counter - used only with station beamformer

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :return: counter values
        :rtype: dict
        """
        counts = {}
        for fpga in self.fpga_gen(fpga_id):
            counts[f'FPGA{fpga}'] = self.tpm.station_beamf[fpga].check_ddr_parity_error_counter()
        return counts
    

    def check_f2f_pll_status(self, core_id=None, show_result=True):
        """
        Check current F2F PLL lock status and for loss of lock events.

        :param core_id: Specify which F2F Core, 0,1, or None for both cores
        :type core_id: integer

        :param show_result: prints error counts on logger
        :type show_result: bool

        :return: current status and counter values
        :rtype: dict
        """
        # TPM 1.2 has 2 cores per FPGA while TPM 1.6 has 1
        # The below code is temporary until nof tpm_f2f instances is corrected and
        # nof_f2f_cores can be replaced with len(self.tpm.tpm_f2f)
        nof_f2f_cores = 2 if self.tpm_version() == "tpm_v1_2" else 1
        cores = range(nof_f2f_cores) if core_id is None else [core_id]
        counts = {}
        for core in cores:
            counts[f'Core{core}'] = self.tpm.tpm_f2f[core].check_pll_lock_status(show_result)
        return counts # Return dict of counter values

    def clear_f2f_pll_lock_loss_counter(self, core_id=None):
        """
        Reset value of F2F PLL lock loss counter.

        :param core_id: Specify which F2F Core, 0,1, or None for both cores
        :type core_id: integer
        """
        # TPM 1.2 has 2 cores per FPGA while TPM 1.6 has 1
        # The below code is temporary until nof tpm_f2f instances is corrected and
        # nof_f2f_cores can be replaced with len(self.tpm.tpm_f2f)
        nof_f2f_cores = 2 if self.tpm_version() == "tpm_v1_2" else 1
        cores = range(nof_f2f_cores) if core_id is None else [core_id]
        for core in cores:
            self.tpm.tpm_f2f[core].clear_pll_lock_loss_counter()
        return

    def check_udp_arp_table_status(self, fpga_id=None, show_result=True):
        """
        Check UDP ARP Table has been populated correctly. This is a non-
        destructive version of the method check_arp_table.

        :param show_result: prints ARP table contents on logger
        :type show_result: bool

        :return: true if each FPGA has at least one entry valid and resolved.
        :rtype: bool
        """
        # This method only supports the xg_40g_eth configuration with
        # one core per fpga
        silent_mode = not show_result
        arp_table_ids = range(self.tpm.tpm_10g_core[0].get_number_of_arp_table_entries())
        fpga_resolved_entries = []
        fpga_unresolved_entries = []
        for fpga in self.fpga_gen(fpga_id):
            resolved_cnt = 0
            unresolved_cnt = 0
            for arp_table in arp_table_ids:
                arp_status, mac = self.tpm.tpm_10g_core[fpga].get_arp_table_status(arp_table, silent_mode)
                if arp_status & 0x1:
                    if arp_status & 0x4:
                        resolved_cnt += 1
                    else:
                        unresolved_cnt += 1
            fpga_resolved_entries.append(resolved_cnt)
            fpga_unresolved_entries.append(unresolved_cnt)
        return True if all(fpga_resolved_entries) and not any(fpga_unresolved_entries) else False

    def check_udp_status(self, fpga_id=None):
        """
        Check for UDP C2C and BIP errors.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :return: true if all OK (all error counters are 0)
        :rtype: bool
        """
        # This method only supports the xg_40g_eth configuration with
        # one core per fpga, 4 ARP table IDs per core
        errors = []
        for fpga in self.fpga_gen(fpga_id):
            errors.append(self.tpm.tpm_10g_core[fpga].check_errors())
        return not any(errors) # Return True if status OK, all errors False
    
    def clear_udp_status(self, fpga_id=None):
        """
        Reset UDP C2C and BIP error counters.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer
        """
        # This method only supports the xg_40g_eth configuration with
        # one core per fpga, 4 ARP table IDs per core
        for fpga in self.fpga_gen(fpga_id):
            self.tpm.tpm_10g_core[fpga].reset_errors()
        return
    
    def check_udp_linkup_loss_counter(self, fpga_id=None, show_result=True):
        """
        Check UDP interface for linkup loss events.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param show_result: prints error counts on logger
        :type show_result: bool

        :return: counter values
        :rtype: dict
        """
        # This method only supports the xg_40g_eth configuration with
        # one core per fpga, 4 ARP table IDs per core
        counts = {}
        for fpga in self.fpga_gen(fpga_id):
            counts[f'FPGA{fpga}'] = self.tpm.tpm_10g_core[fpga].check_linkup_loss_cnt(show_result)
        return counts # Return dict of counter values

    def check_udp_crc_error_counter(self, fpga_id=None):
        """
        Check UDP interface for CRC errors.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :return: counter values
        :rtype: dict
        """
        counts = {}
        for fpga in self.fpga_gen(fpga_id):
            counts[f'FPGA{fpga}'] = self.tpm.tpm_10g_core[fpga].get_crc_error_count()
        return counts # Return dict of counter values
    
    def check_udp_bip_error_counter(self, fpga_id=None):
        """
        Check UDP interface for BIP errors.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :return: counter values
        :rtype: dict
        """
        counts = {}
        for fpga in self.fpga_gen(fpga_id):
            counts[f'FPGA{fpga}'] = self.tpm.tpm_10g_core[fpga].get_bip_error_count()
        return counts # Return dict of counter values
    
    def check_tile_beamformer_status(self, fpga_id=None):
        """
        Check tile beamformer error flags.
        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :return: True when Status is OK, no errors
        :rtype bool
        """
        if self.is_programmed():
            result = []
            for fpga in self.fpga_gen(fpga_id):
                result.append(self.tpm.beamf_fd[fpga].check_errors())
            return all(result)
        return
    
    def clear_tile_beamformer_status(self, fpga_id=None):
        """
        Clear tile beamformer error flags.
        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :return: True when Status is OK, no errors
        :rtype bool
        """
        if self.is_programmed():
            for fpga in self.fpga_gen(fpga_id):
                self.tpm.beamf_fd[fpga].clear_errors()
        return

    def check_station_beamformer_status(self, fpga_id=None):
        """
        Check status of Station Beamformer error flags and counters.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer

        :param show_result: prints error counts on logger
        :type show_result: bool

        :return: True when Status is OK, no errors
        :rtype bool
        """
        if self.is_programmed():
            errors = []
            for fpga in self.fpga_gen(fpga_id):
                errors.append(self.tpm.station_beamf[fpga].report_errors())
            return not any(errors) # Return True if all flags and counters are 0, else False
        return

    def clear_station_beamformer_status(self, fpga_id=None):
        """
        Clear status of Station Beamformer error flags and counters.
        Including DDR parity error counter.

        :param fpga_id: Specify which FPGA, 0,1, or None for both FPGAs
        :type fpga_id: integer
        """
        if self.is_programmed():
            for fpga in self.fpga_gen(fpga_id):
                self.tpm.station_beamf[fpga].clear_errors()
        return

    #######################################################################################
    # ------------------- Test methods

    def get_exp_health(self):
        EXP_TEMP, EXP_VOLTAGE, EXP_CURRENT = self.get_health_acceptance_values()
        health = {
            'temperature': EXP_TEMP, 'voltage': EXP_VOLTAGE, 'current': EXP_CURRENT,
            'alarms': None if self.tpm_version() == "tpm_v1_2" else {'I2C_access_alm': 0, 'temperature_alm': 0, 'voltage_alm': 0, 'SEM_wd': 0, 'MCU_wd': 0},
            'timing': {
                'clocks': {'FPGA0': {'JESD': True, 'DDR': True, 'UDP': True}, 'FPGA1': {'JESD': True, 'DDR': True, 'UDP': True}},
                'clock_managers' : {
                    'FPGA0': {'C2C_MMCM': (True, 0), 'JESD_MMCM': (True, 0), 'DSP_MMCM': (True, 0)},
                    'FPGA1': {'C2C_MMCM': (True, 0), 'JESD_MMCM': (True, 0), 'DSP_MMCM': (True, 0)}},
                'pps': {'status': True}},
            'io':{ 
                'jesd_if': {
                    'link_status': True, 
                    'lane_error_count': {
                        'FPGA0': {
                            'Core0': {'lane0': 0, 'lane1': 0, 'lane2': 0, 'lane3': 0, 'lane4': 0, 'lane5': 0, 'lane6': 0, 'lane7': 0}, 
                            'Core1': {'lane0': 0, 'lane1': 0, 'lane2': 0, 'lane3': 0, 'lane4': 0, 'lane5': 0, 'lane6': 0, 'lane7': 0}}, 
                        'FPGA1': {
                            'Core0': {'lane0': 0, 'lane1': 0, 'lane2': 0, 'lane3': 0, 'lane4': 0, 'lane5': 0, 'lane6': 0, 'lane7': 0}, 
                            'Core1': {'lane0': 0, 'lane1': 0, 'lane2': 0, 'lane3': 0, 'lane4': 0, 'lane5': 0, 'lane6': 0, 'lane7': 0}}},
                    'lane_status' : True, 
                    'resync_count': {'FPGA0': 0, 'FPGA1': 0}, 
                    'qpll_status': {'FPGA0': (True, 0), 'FPGA1': (True, 0)}},
                'ddr_if': {'initialisation': True, 'reset_counter': {'FPGA0': 0, 'FPGA1': 0}},
                'f2f_if': {'pll_status': {'Core0': [(True, 0), (True, 0)], 'Core1': [(True, 0), (True, 0)]} if self.tpm_version() == "tpm_v1_2" else {'Core0' : (True, 0)}},
                'udp_if': {
                    'arp': True, 
                    'status': True, 
                    'crc_error_count': {'FPGA0': 0, 'FPGA1': 0}, 
                    'bip_error_count': {'FPGA0': {'lane0': 0, 'lane1': 0, 'lane2': 0, 'lane3': 0}, 'FPGA1': {'lane0': 0, 'lane1': 0, 'lane2': 0, 'lane3': 0}}, 
                    'linkup_loss_count': {'FPGA0': 0, 'FPGA1': 0}}},
            'dsp': {
                'tile_beamf': True,
                'station_beamf': { 'status': True, 'ddr_parity_error_count': {'FPGA0': 0, 'FPGA1': 0}}
            }
        }
        return health
    
    def inject_ddr_parity_error(self, fpga_id=None):
        for fpga in self.fpga_gen(fpga_id):
            board = f'fpga{fpga+1}'
            self.logger.info(f"Injecting DDR Parity Error - FPGA{fpga}")
            self[f'{board}.beamf_ring.ddr_parity_error_inject'] = 1
            timeout = 60 # 30 seconds
            count = 0
            while True:
                reg = self[f'{board}.beamf_ring.ddr_parity_error_inject']
                if reg == 0:  # Register deasserts once injection has completed
                    break
                if count % 4 == 0: # Every 2 seconds
                    self.logger.info("Waiting for valid DDR read transaction...")
                if count > timeout:
                    self.logger.error("Timed out waiting for DDR parity error injection acknowledge. No valid DDR read transaction")
                    break
                time.sleep(0.5)
                count += 1
        return