FROM turbointegrations/base

RUN mkdir -p /opt/turbonomic/data
COPY ./csv_to_app_topology.py /opt/turbonomic/
COPY ./Filtered_Apps_Host_List.csv /opt/turbonomic/Filtered_Apps_Host_List.csv
COPY ./output_business_app.csv /opt/turbonomic/output_business_app.csv
COPY ./output_svc_ci_assoc.csv /opt/turbonomic/output_svc_ci_assoc.csv

ENTRYPOINT python /opt/turbonomic/csv_to_app_topology.py /opt/turbonomic/data/config.json $VMT_USERNAME $VMT_PASSWORD
