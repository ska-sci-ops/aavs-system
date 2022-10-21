FROM python:3.9

# ENV http_proxy=http://delphoenix.atnf.csiro.au:8888
# ENV https_proxy=http://delphoenix.atnf.csiro.au:8888

RUN echo "http_proxy=http://delphoenix.atnf.csiro.au:8888\nhttps_proxy=http://delphoenix.atnf.csiro.au:8888" >> /etc/environment

COPY . /aavs-system/

WORKDIR /aavs-system

RUN echo "#!/bin/sh\n\"\$@\"" > /usr/bin/sudo
RUN chmod +x /usr/bin/sudo

RUN apt update
RUN apt install -y apt-utils dialog python3-venv libcap2-bin

RUN USER=root ./deploy.sh

# squash bug
RUN sed -i 's/savefig(output, figsize=/savefig(output) #, figsize=/g' /opt/aavs/python/lib/python3.9/site-packages/aavs_system-1.1-py3.9.egg/pydaq/plotters/raw_data.py

WORKDIR /opt/aavs/bin

ENTRYPOINT ["/opt/aavs/python/bin/python"]
