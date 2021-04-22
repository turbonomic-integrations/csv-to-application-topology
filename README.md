## CSV to Application Topology Mapping

### Description
This script takes a CSV as input and creates Business Applications in Turbonomic using the Application Topology feature. It runs as a Kubernetes Job in a Turbonomic Kubernetes cluster, and is intended for a one-time or ad-hoc execution.  

There are two main ways to deliver the CSV data to the script:

* Cloud-based storage (Azure Blob or AWS S3 are supported)
* Local FTP container  

The setup and files required will be different depending on whether you choose Cloud or FTP, so please read through the **Script Setup** carefully. Either way, once the script is done running, the containers supporting it will be stopped, so if using the FTP, it will only be accessible until the process finishes.  

All credentials for accessing both the Turbonomic API and Cloud providers are presented through Kubernetes secrets, detailed below in the **Secret Details** section.  

Lastly, The script also requires a config file, implemented as a Kubernetes configMap, that includes a mapping of the columns provided in the input CSV to a common name that the script can use. Additional configs are detailed below in the **ConfigMap Details** section.

Examples of each of the necessary Kubernetes YAML files are included, so please take a look at those if anything is unclear.  

### Script Setup    
1. Upload required containers  
    * FTP: *csv-to-app-topo*, *dif-ftp*
    * Cloud: *csv-to-app-topo*  
2. Complete and upload secrets yaml (see **Secret Details** below for further details)
    * `kubectl apply -f turboauth_secret.yml`
3. Complete and upload the ConfigMap with the appropriate fields (see **ConfigMap Details** below for further details)
    * `kubectl apply -f csv_to_app_topo_configmap.yml`
4. Upload and apply Job yaml definition
    * FTP: `kubectl apply -f csv_to_app_topo_ftp.yml`
    * Cloud: `kubectl apply -f csv_to_app_topo_cloud.yml`
5. Upload CSV to either FTP or Cloud destination
    * FTP: The FTP can be accessed via port 31234 on the Turbonomic instance, with passive connection on ports 30020 and 30021
    * Cloud: The Turbonomic instance must have connection to the outside internet

### ConfigMap Details  
* CSV_LOCATION - Location of CSV. One of *AWS*, *AZURE* or *FTP*
* INPUT_CSV_NAME - CSV file name
* ENTITY_FIELD_MAP - Mapping for supported fields to columns defined in CSV
    - Required Fields: 
        - app_name - Business App name
        - entity_name - VM name
        - entity_ip - VM IP address (optional if MATCH_IP is false) 
* MATCH_IP - True/False flag to enforce strict VM matching based on input IP address. If *false*, matches between input CSV and Turbonomic system will be based on VM name only.
* APP_PREFIX - Optional Prefix for Business App names
* LOG_DIR - Optional log directory for persistent log files. Defaults to Container STDOUT
* LOG_FILE - Optional log file for persistent log files. Defaults to Container STDOUT
* LOG_LEVEL - Optional flag for setting logging level. One of *DEBUG*, *INFO*, *WARNING*, *ERROR*. Defaults to INFO

### Secret Details 
Secret must be named **turboauth**  

Required secrets:  
1. TURBO_ADDRESS - IP address of Turbonomic instance  
2. TURBO_USERNAME - Administrator level user in Turbonomic instance  
3. TURBO_PASSWORD - User password  

Depending on CSV_LOCATION, you will need to add the following fields to the secret 

##### Azure Blob:  
1. AZURE_CONNECTION_STRING - The Azure Blob connection string  
    To find the Azure connection string:
    1. Sign in to the Azure portal.
    2. Locate your storage account.
    3. In the Settings section of the storage account overview, select Access keys. Here, you can view your account access keys and the complete connection string for each key.
    4. Find the Connection string value under key1, and select the Copy button to copy the connection string.
2. AZURE_CONTAINER_NAME - The Azure Blob Container name

##### AWS S3 Bucket:
1. AWS_ACCESS_KEY_ID - Account Access Key ID
2. AWS_SECRET_ACCESS_KEY - Account Secret Access Key
3. AWS_REGION_NAME - Region name where S3 bucket is located
4. AWS_BUCKET_NAME - S3 Bucket name

##### Local FTP Server:
1. No additional action needed

### Logs
By default, if no persistent logs are defined in the ConfigMap input, the script logs can be accessed by connecting directly to the container output:  
    `kubectl logs <csv-to-app-topo-container> -c csv-to-app-topo`