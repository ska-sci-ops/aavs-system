#!/bin/bash

# Helper function to install required package
function install_package(){
    PKG_OK=$(dpkg-query -W --showformat='${Status}\n' $1 | grep "install ok installed")
    if [ "" == "$PKG_OK" ]; then
      echo "Installing $1."
      sudo apt-get --force-yes --yes install $1
    else
      echo "$1 already installed"
    fi
}

echo -e "\n==== Boostrapping AAVS ====\n"

# Install git core to clone repositories
install_package git

# Configure git to cache password for 30 days
echo -e "\nSetting up git cache"
git config --global credential.helper "cache --timeout=1296000"

# Clone system repository, which will boostrap the rest of the packages
if [ ! -d "aavs-system" ]; then
    echo -e "\nCloning AAVS System"
    git clone https://lessju@bitbucket.org/aavslmc/aavs-system.git
else
    echo -e "\nAAVS System already cloned"
fi

# Setting top level AAVS directory
if [ -z "$AAVS_PATH" ]; then 
    echo -e "Setting AAVS PATH tp `pwd`"
    echo "export AAVS_PATH=`pwd`" >> ~/.bashrc 
    export AAVS_PATH=$PWD
fi

# Check if AAVS install directory has been passed as an argument
if [ -z "$AAVS_INSTALL" ]; then
 if [[ $# -lt 1 ]]; then
    echo "AAVS install directory required as argument"
    exit 1
  else
    echo "export AAVS_INSTALL=`echo $1`" >> ~/.bashrc 
    export AAVS_INSTALL=`echo $1`
  fi
else
  echo "AAVS_INSTALL already defined, ignoring argument $1"
fi

# Launch deployment script in aavs-system
pushd $AAVS_PATH/aavs-system
. deploy.sh $1
popd

