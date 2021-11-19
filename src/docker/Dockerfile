FROM python:3.8-alpine AS compile-image

RUN apk add --update --no-cache gcc musl-dev libc-dev libxslt-dev libffi-dev openssl-dev
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --upgrade pip && \
    pip install 'vmtconnect>3.2,<4' && \
    pip install umsg && \
    pip install boto3 && \
    pip install azure.storage.blob


FROM python:3.8-alpine
RUN mkdir -p /opt/turbonomic/data
COPY --from=compile-image /opt/venv /opt/venv
COPY ./csv_to_app_topology.py /opt/turbonomic


ENV PATH="/opt/venv/bin:$PATH"
ENTRYPOINT python /opt/turbonomic/csv_to_app_topology.py /opt/turbonomic/config/config.json
