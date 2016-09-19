#!/bin/bash

# Declare array containing repositories to clone
declare -a repos=("aavs-access-layer" "aavs-daq" "aavs-tango" "aavs-backend")

# Loop over all required repos
cd $AAVS_PATH
current=`pwd`
for repo in "${repos[@]}"; do

  # Check if directory already exists
  if [ ! -d $repo ]; then
    echo -e "\nCloning $repo"
    git clone https://bitbucket.org/aavslmc/$repo.git
  else
    echo -e "\n$repo already cloned"
  fi

  # Repository cloned, pull to latest
  cd $AAVS_PATH/$repo
  if [ $repo == "aavs-backend" ]; then
      git checkout mwa-nodb
  fi
  if [ $repo == "aavs-tango" ]; then
      git checkout dev
  fi
  git pull

  # Repository pulled, call deployment script
  if [ ! -e "deploy.sh" ]; then
    echo "No deployment script for $repo"
  else
    echo "Deploying $repo"
    bash deploy.sh
  fi
  cd $current 
done
