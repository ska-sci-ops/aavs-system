
# Deploying AAVS LMC

This README file described how to deploy, configure and run the AAVS1 LMC system.
The source code is split into multiple separate git repositories, and the aim of
this repository (AAVS System) is to combine the packages together and deploy
them onto an Ubuntu 14.04 installation. This has been tested on a clean installation
(on a Virtual Machine).

Before deploying the LMC system make sure that:
- At least one network interface is configured to be on the same subnet as a TPM
(the system has only been tested with a single TPM). If running in a VM, the network
settings for the VM should be set to NAT, assuming that one of the host's interface
is on the TPM's subnet. Default TPM subnet is 10.0.10.0/24
- Port 80 on the server is accessible by the TM emulator on the IP address to which the
API is bound (by default it is bound to all interface on the machine)

## Deploying the LMC

This repository contains a bootstrap scripts which will kickstart automatic deployment
of the system. The following steps should be performed:

1. Create a directory where the repositories will be cloned <br/>
`mkdir AAVS`

2. Go into the directory. This will be the AAVS path<br/>
`cd AAVS`

3. Create an empty bootstrap file and make it executable <br/>
`touch bootstrap.sh; chmod u+x bootstrap.sh`

4. Copy the contents of the `bootstrap.sh` file from the *AAVS System* into the created
file

5. Run `bootstrap.sh`, giving it the LMC installation directory as a parameters. In this case,
it will be installed in `/opt/aavs`, so this directory must be created as well<br/>
`sudo mkdir -p /opt/aavs`</br>
`sudo chown $USER /opt/aavs `
`./bootstrap.sh /opt/aavs`

6. When deployment is ready, the environment should be updated if the same terminal will be
used for other operations<br/>
`source ~/.bashrc`

The deployment procedure will take about 30 minutes to complete, and will as for sudo
password almost immediately. Once the password is provided, it will use it for all operations
requiring root. Note that after installation, all operations (apart from data acquisition) can
be performed without root privileges. After some time, it will prompt for several settings
 (for MySQL and TANGO), simple use the default option (and blank for passwords).

##### Notes on deployment:
- Several environmental variables will be defined in the user's `.bashrc` file
- An installation directory will be generated in the specified install path. These include
`lib` for generated libraries, `bin` for generated binary files, `log` to store log files and
`bitfiles` to store TPM firmware. The `lib` and `bin` directories will be added to the
`LD_LIBRARY_PATH` and `PATH` environmental variables respectively.
- All python packages are installed in a virtual environment set up during the deployment
procedure. Any operations requiring these packages (or when using any of the LMC packages)
need to be performed in this environment. To start this environment, use the command `aavs_env`
- TANGO device servers and the AAVS backend are automatically started on deployment

## Updating Deployment

To update the installation, simple re-run the bootstrap script<br/>
`cd $AAVS_PATH; ./bootstrap.sh`

This will pull any changes in repositories, install any new requirements needed by any of them, rebuild all source file and python packages and re-start all services
