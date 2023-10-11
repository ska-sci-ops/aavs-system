FROM artefact.skao.int/ska-tango-images-pytango-builder:9.3.35 AS buildenv
FROM artefact.skao.int/ska-tango-images-pytango-runtime:9.3.22 AS runtime

USER root

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive TZ="United_Kingdom/London" apt-get install -y \
    build-essential ca-certificates cmake libcap2-bin git make tzdata xattr


ENV AAVS_PYTHON_BIN=/usr/bin/python3

RUN chmod +x /app/deploy.sh

RUN ["/bin/bash", "-c", "/app/deploy.sh -c"]

ENV VIRTUAL_ENV=/opt/aavs/python/
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /app/
USER tango
