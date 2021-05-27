
# AAVS System

This is the base repository for the AAVS software systems, organised as follows:

- bitfiles: TPM Firmware bitfiles
- config: Station configuration files
- python/pyaavs: Station monitoring and control
- python/pydaq: Data acquisition
- python/aavs_calibration: Calibration database
- python/utilities: Useful scripts
- src: Data acqusition backend
- python/pyaavs/tests: Firmware and software tests
- web: Monitoring page
- python/utilities: additional utilities

The deploy script deploy.sh will create the execution environment to run the AAVS software,
execute ./deploy.sh -h for details.

After sucessful execution of the deploy script, a station configuration file should be 
created in order to define the hardware setup and observation parameter of the station.
Refer to config/default_config.yml for detail.

The test environment is described in a dedicated document located in 
python/pyaavs/tests/doc, refer to the document in order to configure and use it.
