FROM turbointegrations/base

# Setup directory and scripts
RUN mkdir -p /opt/turbonomic/data
RUN mkdir -p /opt/turbonomic/config
COPY ./csv_to_app_topology.py /opt/turbonomic

# Download required Python packages
RUN python -m pip install boto3
RUN python -m pip install azure.storage.blob

ENTRYPOINT python /opt/turbonomic/csv_to_app_topology.py /opt/turbonomic/config/config.json
