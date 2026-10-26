FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    P4P_DATA_DIR=/data

WORKDIR /app

RUN apt-get update \
    && apt-get upgrade --yes \
    && apt-get install --yes --no-install-recommends gosu=1.14-1+b10 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 p4p \
    && useradd --uid 10001 --gid p4p --home-dir /nonexistent --shell /usr/sbin/nologin p4p

COPY requirements.lock.txt ./
COPY registry/requirements.txt registry/requirements.txt
COPY demo-node/requirements.txt demo-node/requirements.txt
COPY pilot-node/requirements.txt pilot-node/requirements.txt

RUN python -m pip install --no-cache-dir \
    --constraint requirements.lock.txt \
    --requirement registry/requirements.txt \
    --requirement demo-node/requirements.txt \
    --requirement pilot-node/requirements.txt

COPY p4p_core p4p_core
COPY registry registry
COPY demo-node demo-node
COPY pilot-node pilot-node
COPY modules modules
COPY module_catalog.py p4p_identity.py ./
COPY deploy/container-entrypoint.sh deploy/container-entrypoint.sh

RUN chmod 0755 deploy/container-entrypoint.sh \
    && install -d -o p4p -g p4p -m 0700 /data

EXPOSE 8000

USER p4p

ENTRYPOINT ["/app/deploy/container-entrypoint.sh"]
