#!/usr/bin/env bash
#
# This script should be executed with sudo.
#
# This script uses /usr/bin/python3 as default Python interpreter. To use another interpreter, for instance python3.8
# instead of default python3, do as follows:
#
#   AAVS_PYTHON_BIN=/usr/bin/python3.8
#   export AAVS_PYTHON_BIN
#   sudo -E deploy.sh
#
echo "${AAVS_PYTHON_BIN}"
if [[ -z "${AAVS_PYTHON_BIN}" ]]; then
  export PYTHON=/usr/bin/python3
else
  export PYTHON=${AAVS_PYTHON_BIN}
fi
echo "Using python $PYTHON"

# Function to display installer help
function display_help(){
    echo "This script will install the AAVS system software in /opt/aavs. Arguments:"
    echo "-C    Correlator will be compiled, installing CUDA and xGPU in the process (off by default)"
    echo "      NOTE: Automated install of CUDA and xGPU not supported yet"
    echo "-p    Activate AAVS virtualenv in .bashrc (off by default)"
    echo "-h    Print this message"
}

# AAVS install directory. DO NOT CHANGE!
export AAVS_INSTALL=/opt/aavs

# Installation options
COMPILE_CORRELATOR=OFF
ACTIVATE_VENV=false
PRINT_HELP=false

# Process command-line argments
while getopts Chp flag
do
    case "${flag}" in
        C) COMPILE_CORRELATOR=ON ;;
        h) PRINT_HELP=true ;;
        p) ACTIVATE_VENV=true ;;
    esac
done

# Check if printing help
if [ $PRINT_HELP == true ]; then
    display_help
    exit
fi

# Check if compliing correlator
if [ $COMPILE_CORRELATOR == ON ]; then
    echo "============ COMPILING CORRELATOR ==========="
else
    echo "========== NOT COMPILING CORRELATOR ========="
fi

echo -e "\n==== Configuring AAVS System  ====\n"

# Helper function to install required package
function install_package(){
    PKG_OK=$(dpkg-query -W --showformat='${Status}\n' $1 | grep "install ok installed")
    if [[ "" == "$PKG_OK" ]]; then
      echo "Installing $1."
      sudo apt-get -qq --yes install $1 > /dev/null || exit
      return  0 # Return success status
    else
      echo "$1 already installed"
      return 1  # Return fail status (already installed)
    fi
}

# Create installation directory tree
function create_install() {

  # Create install directory if it does not exist
  if [ ! -d "$AAVS_INSTALL" ]; then
	  sudo mkdir -p $AAVS_INSTALL
	  sudo chown $USER $AAVS_INSTALL
  fi

  # Create lib directory
  if [ ! -d "$AAVS_INSTALL/lib" ]; then
    mkdir -p $AAVS_INSTALL/lib
    echo "export LD_LIBRARY_PATH=LD_LIBRARY_PATH:${AAVS_INSTALL}/lib" >> ~/.bashrc
  fi

  # Add directory to LD_LIBRARY_PATH
  if [[ ! ":$LD_LIBRARY_PATH:" == *"aavs"* ]]; then
    export LD_LIBRARY_PATH=$AAVS_INSTALL/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH} 
  fi
  
  # Create bin directory and add to path
  if [ ! -d "$AAVS_INSTALL/bin" ]; then
    mkdir -p $AAVS_INSTALL/bin
    export PATH=$AAVS_INSTALL/bin:$PATH
    echo "export PATH=PATH:${AAVS_INSTALL}/bin" >> ~/.bashrc
  fi

  # Export AAVS bin directory
  if [ -z "$AAVS_BIN" ]; then
    export AAVS_BIN=$AAVS_INSTALL/bin
  fi

  # Create include directory
  if [[ ! -d "$AAVS_INSTALL/include" ]]; then
    mkdir -p $AAVS_INSTALL/include
  fi
  
  # Create log directory
  if [[ ! -d "$AAVS_INSTALL/log" ]]; then
    mkdir -p $AAVS_INSTALL/log
	chmod a+rw $AAVS_INSTALL/log
  fi

  # Create python3 virtual environment
  if [[ ! -d "$AAVS_INSTALL/python" ]]; then
    mkdir -p $AAVS_INSTALL/python

    # Create python virtual environment
    # virtualenv -p python3 $AAVS_INSTALL/python
    $PYTHON -m venv $AAVS_INSTALL/python

    # Add AAVS virtual environment alias to .bashrc
    if [[ ! -n "`cat ~/.bashrc | grep aavs_python`" ]]; then
      echo "alias aavs_python=\"source /opt/aavs/python/bin/activate\"" >> ~/.bashrc
      echo "Setting virtual environment alias"

      # Check if compliing correlator
      if [ $ACTIVATE_VENV == true ]; then
          echo "aavs_python" >> ~/.bashrc
      fi
    fi
  fi
}

# Installing required system packages
install_package cmake
install_package git
install_package git-lfs
install_package libyaml-dev 
install_package python3-dev
install_package python3-virtualenv
install_package libnuma-dev
install_package build-essential

# Set up NTP synchronisation
if install_package ntp; then
    sudo service ntp reload
fi

# Create installation directory
create_install
echo "Created installation directory tree"

# If software directory is not defined in environment, set it
if [ -z "$AAVS_SOFTWARE_DIRECTORY" ]; then
  export AAVS_SOFTWARE_DIRECTORY=`pwd`
fi

# Start python virtual environment
source $AAVS_INSTALL/python/bin/activate

# Update pip
pip install -U pip

# Install ipython
pip install ipython

# Give python interpreter required capabilities for accessing raw sockets and kernel space
PYTHON_BINARY=`readlink -f /opt/aavs/python/bin/python`
sudo setcap cap_net_raw,cap_ipc_lock,cap_sys_nice,cap_sys_admin,cap_kill+ep $PYTHON_BINARY || exit

# Create a temporary setup directory and cd into it
if [[ ! -d "third_party" ]]; then
  mkdir third_party
fi

pushd third_party || exit

  # Install PyFABIL
  pip install git+https://lessju@bitbucket.org/lessju/pyfabil.git

  # Install DAQ
  if [[ ! -d "aavs-daq" ]]; then
    git clone https://lessju@bitbucket.org/aavslmc/aavs-daq.git

    pushd aavs-daq/src || exit
      if [[ ! -d build ]]; then
        mkdir build
      fi
      
	  # Install DAQ C++ core
	  pushd build || exit
        cmake -DCMAKE_INSTALL_PREFIX=$AAVS_INSTALL -DWITH_BCC=OFF .. || exit
        make -B -j8 install || exit
      popd
    popd
  fi

popd

# Install C++ src
pushd src || exit
  if [ ! -d build ]; then
    mkdir build
  fi

  pushd build || exit
    cmake -DCMAKE_INSTALL_PREFIX=$AAVS_INSTALL/lib -DWITH_CORRELATOR=$COMPILE_CORRELATOR .. || exit
    make -B -j4 install || exit
  popd
popd


# Install required python packages
pushd python || exit
  python setup.py install || exit
popd

# Link required scripts to bin directory
FILE=$AAVS_BIN/daq_plotter.py
if [ -e $FILE ]; then
  sudo rm $FILE
fi
sudo ln -s $PWD/python/pydaq/daq_plotter.py $FILE
chmod u+x $FILE

FILE=$AAVS_BIN/daq_receiver.py
if [ -e $FILE ]; then
  sudo rm $FILE
fi
ln -s $PWD/python/pydaq/daq_receiver.py $FILE
chmod u+x $FILE

FILE=$AAVS_BIN/station.py
if [ -e $FILE ]; then
  sudo rm $FILE
fi
ln -s $PWD/python/pyaavs/station.py $FILE
chmod u+x $FILE

DIR=$AAVS_INSTALL/bitfiles
if [ -d $DIR ]; then
  sudo rm -r $DIR
fi
ln -s $PWD/bitfiles $DIR

DIR=$AAVS_INSTALL/config
if [ -d $DIR ]; then
  sudo rm -r $DIR
fi
ln -s $PWD/config $DIR


echo ""
echo "Installation finished. Please check your .bashrc file and source it to update your environment"
echo ""