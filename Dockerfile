FROM artefact.skao.int/ska-tango-images-pytango-builder:9.3.35 AS buildenv
FROM artefact.skao.int/ska-tango-images-pytango-runtime:9.3.22 AS runtime

USER root

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive TZ="United_Kingdom/London" apt-get install -y \
    build-essential ca-certificates cmake libcap2-bin git make tzdata xattr


ENV AAVS_PYTHON_BIN=/usr/bin/python3.10

RUN ["/bin/bash", "-c", "source /app/deploy.sh -c"]

WORKDIR /app/

USER aavs