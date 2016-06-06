#!/bin/sh
cd aavs-backend 
git checkout mwa-nodb
echo "aavs-backend checked out mwa-nodb"
cd ../aavs-tango  
git checkout dev
echo "aavs-tango checked out dev"

sudo service aavs-api restart
sudo service tango-runner restart