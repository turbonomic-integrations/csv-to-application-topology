import csv
import json
import sys
import logging
import re
import copy
import os
import time
from io import StringIO

import vmtconnect as vc
import umsg
import requests
import boto3
import azure.core.exceptions
import botocore.exceptions
from azure.storage.blob import BlobServiceClient


class IpAddressNotFoundError(Exception):
    pass


class InvalidConfigError(Exception):
    pass


class CsvDownloadError(Exception):
    pass


class CsvFileNotFoundError(CsvDownloadError):
    pass


class UserDefinedApp():
    """Represents user-defined application topology
    """
    def __init__(self, app_name):
        self.name = app_name
        self.members = []
        self.member_uuids = set()

    @staticmethod
    def _process_ips(ips):
        ip_addresses = []
        ip_regex = r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"

        if isinstance(ips, list):
            for ip in ips:
                matches = re.findall(ip_regex, ips)
                ip_addresses.extend(matches)

        if isinstance(ips, str):
            matches = re.findall(ip_regex, ips)
            ip_addresses.extend(matches)

        if not ip_addresses:
            raise IpAddressNotFoundError()

        return ','.join(ip_addresses)

    def _prep_app_topo_dto(self):
        dto_template = {"displayName": self.name,
                        "entityType": "BusinessApplication",
                        "entityDefinitionData": {
                            "manualConnectionData": {
                                "VirtualMachine": {
                                    "staticConnections": list(self.member_uuids)
                                    }
                                }
                            }
                        }
        return json.dumps(dto_template)

    def add_member(self, member_name, member_ip):
        member_info = {'name': member_name,
                       'ip_address': '',
                       'turbo_oid': None}

        try:
            member_info['ip_address'] = self._process_ips(member_ip)

        except IpAddressNotFoundError:
            umsg.log(f'No IP address defined for VM {member_name}', level='debug')
            pass

        if member_info in self.members:
            umsg.log(f'Member {member_info["name"]} already exists in {self.name} application group',
                     level='warn')
            pass

        else:
            self.members.append(member_info)

    def del_member(self, member):
        self.members.remove(member)

    def remove_members_without_matches(self):
        member_copy = copy.deepcopy(self.members.copy())

        for member in member_copy:
            if not member['turbo_oid']:
                self.del_member(member)

    def create_appl_topo(self, conn):
        umsg.log(f'Creating application for BusinessApplication named: {self.name}')
        dto = self._prep_app_topo_dto()
        res = conn.request('topologydefinitions', method='POST', dto=dto)
        umsg.log(f'Successfully created app {self.name}.')
        umsg.log(f'Response Details: {res}', level='debug')

        return True

    def update_appl_topo(self, conn, uuid):
        umsg.log(f'Updating BusinessApplication named: {self.name}')
        dto = self._prep_app_topo_dto()
        res = conn.request(f'topologydefinitions/{uuid}', method='PUT', dto=dto)
        umsg.log(f'Successfully updated app {self.name}.')
        umsg.log(f'Response Details: {res}', level='debug')

        return True


class DifCsvReader():
    def __init__(self, filename, csv_location, entity_headers, match_ip=False):
        self.filename = filename
        self.entity_headers = entity_headers
        self.file_downloaded = False
        self.match_ip = match_ip
        self._check_headers()
        self.process_csv_location(csv_location)

    def _process_entity_headers(self, row):
        entities = {}
        for k, v in self.entity_headers.items():
            try:
                entities[k] = row[v]

            except KeyError:
                umsg.log(f'Incorrect entity field map entry: key: {k}, value: {v}', level='error')
                raise

        return entities

    def _check_headers(self):
        """Initialize default header dictionaries based on header type"""
        valid_entity_columns = {'app_name', 'entity_name', 'entity_ip'}

        if self.entity_headers:
            bad_headers = set(self.entity_headers.keys()) - valid_entity_columns
            if bad_headers:
                msg = f'The following entity field map keys are invalid: [ {", ".join(bad_headers)} ]'
                umsg.log(msg, level='error')
                raise InvalidConfigError(msg)

        else:
            umsg.log(f'No CSV entity header mapping provided, using defaults',
                     level='warn')
            self.entity_headers = {x: x for x in valid_entity_columns}

        if self.match_ip and 'entity_ip' not in self.entity_headers.keys():
            msg = f'entity_ip must be defined when MATCH_IP is True'
            umsg.log(msg, level='error')
            raise InvalidConfigError(msg)

    def process_csv_location(self, provider):
        if provider not in {'AZURE', 'AWS', 'FTP'}:
            umsg.log('Value for CSV_LOCATION is invalid. It must be one of: [ AZURE, AWS, FTP ]',
                     level='error')
            raise InvalidConfigError()

        if provider == 'AZURE':
            self.provider = 'AZURE'
            self.connect_str = os.environ['AZURE_CONNECTION_STRING']
            self.container_name = os.environ['AZURE_CONTAINER_NAME']

        if provider == 'AWS':
            self.provider = 'AWS'
            self.access_key_id = os.environ['AWS_ACCESS_KEY_ID']
            self.secret_access_key = os.environ['AWS_SECRET_ACCESS_KEY']
            self.region_name = os.environ['AWS_REGION_NAME']
            self.bucket_name = os.environ['AWS_BUCKET_NAME']
            self.endpoint_url = os.environ.get('AWS_ENDPOINT_URL', None)

        if provider == 'FTP':
            self.provider = 'FTP'
            self.path = os.environ.get('FILE_PATH', '/opt/turbonomic/data')

    def download_csv_data(self):
        umsg.log(f'Downloading CSV data from {self.provider}')
        try:
            if self.provider == 'AZURE':
                service_client = BlobServiceClient.from_connection_string(self.connect_str)
                blob_client = service_client.get_blob_client(container=self.container_name,
                                                             blob=self.filename)
                file_data = blob_client.download_blob().readall()
                file = file_data.decode('utf-8-sig')

            if self.provider == 'AWS':
                s3_client = boto3.resource(service_name='s3',
                                           region_name=self.region_name,
                                           aws_access_key_id=self.access_key_id,
                                           aws_secret_access_key=self.secret_access_key,
                                           endpoint_url=self.endpoint_url)
                try:
                    file_data = s3_client.Object(self.bucket_name, self.filename).get()['Body'].read()
                    file = file_data.decode('utf-8-sig')

                except s3_client.meta.client.exceptions.NoSuchKey:
                    raise FileNotFoundError

            if self.provider == 'FTP':
                filepath = os.path.join(self.path, self.filename)
                with open(filepath, 'r', encoding='utf-8-sig') as fp:
                    file = fp.read()

        except (botocore.exceptions.ClientError,
                botocore.exceptions.InvalidRegionError,
                azure.core.exceptions.HttpResponseError) as e:
            msg = f'Error connecting to cloud provider: {e}'
            umsg.log(msg, level='error')
            raise CsvDownloadError(msg)

        except (azure.core.exceptions.ResourceNotFoundError, FileNotFoundError):
            msg = 'CSV file not found'
            umsg.log(msg, level='error')
            raise CsvFileNotFoundError(msg)

        self.file_downloaded = True

        return StringIO(file)

    def read_csv(self, csv_str_io):
        """Parse CSV StringIO to dict
        Parameters:
            filename - StringIO - IO data from CSV file

        Returns:
            List of dicts, where each dict is a row in the input CSV
        """
        data = []
        csv_data = csv.DictReader(csv_str_io)

        row_count = 1
        for row in csv_data:
            row_count += 1

            if not row[self.entity_headers['app_name']]:
                umsg.log(f'No application defined on row {row_count} of input CSV, skipping',
                         level='warn')
                continue

            try:
                data.append(self._process_entity_headers(row))

            except KeyError:
                umsg.log(f'Something went wrong on line {row_count} while processing CSV')
                raise

        return data


def read_config_file(config_file):
    """Read JSON config file"""
    with open(config_file, 'r') as fp:
        try:
            return json.loads(fp.read())

        except TypeError:
            umsg.log(f'{config_file} must be JSON format', level='error')


def parse_csv_into_apps(csv_data, prefix=''):
    """Parse input CSV into dictionary of UserDefinedApps
    Parameters:
        csv_data - list - List of dicts from read_csv
        prefix - str - Optional prefix for user-defined app name
    """
    app_dict = {}
    row_count = 1

    umsg.log('Looking for apps and associated VMs...')

    for row in csv_data:
        row_count += 1
        if not row['app_name']:
            umsg.log(f'No application defined on row {row_count} of input CSV, skipping',
                     level='warn')
            continue

        app_name = f"{prefix}{row['app_name']}"

        if app_name in app_dict.keys():
            app = app_dict[app_name]

        else:
            app = UserDefinedApp(app_name)
            app_dict[app_name] = app

        app.add_member(member_name=row['entity_name'],
                       member_ip=row.get('entity_ip'))

    return app_dict


def get_vm_info(vm_details):
    vm_oid = vm_details['uuid']
    vm_name = vm_details['displayName']

    try:
        ip_address = vm_details['aspects']['virtualMachineAspect']['ip']

    except KeyError:
        ip_address = []

    return vm_oid, vm_name, ip_address


def get_individual_vm_details(conn, uuids, count):
    vm_list = []

    for vm_uuid in uuids:
        umsg.log(f'Processing VM {count}')
        count += 1

        try:
            single_vm_results = conn.get_entities(uuid=vm_uuid, detail=True)[0]

        except vc.HTTP500Error:
            umsg.log(f'Error getting details for VM with UUID: {vm_uuid}, skipping',
                     level='error')
            continue

        try:
            vm_details = get_vm_info(single_vm_results)

        except KeyError:
            continue

        vm_list.append({'uuid': vm_details[0],
                        'name': vm_details[1],
                        'ip_address': vm_details[2]})
    return vm_list


def get_multiple_vm_details(conn, uuids, count):
    vm_list = []

    try:
        multi_vm_results = conn.get_supplychains(uuids,
                                                 types=['VirtualMachine'],
                                                 detail='aspects',
                                                 aspects=['virtualMachineAspect'])[0]
        for vm in multi_vm_results['seMap']['VirtualMachine']['instances'].values():
            try:
                vm_details = get_vm_info(vm)
                vm_list.append({'uuid': vm_details[0],
                                'name': vm_details[1],
                                'ip_address': vm_details[2]})
            except KeyError:
                continue

    except vc.HTTP500Error as e:
        umsg.log('Problem retrieving bulk VM information, trying individual VMs', level='error')
        umsg.log(e)
        vm_list.extend(get_individual_vm_details(conn, uuids, count))

    return vm_list


def get_turbo_vms(conn, start=None, end=None, step=100):
    vm_list = []
    uuids = [x['uuid']
             for x in conn.search(types=['VirtualMachine'],
                                  detail_type='compact')]
    if not start:
        start = 0
    if not end:
        end = len(uuids)

    while end < len(uuids):
        umsg.log(f'Getting VMs between {start} and {end}, out of a total {len(uuids)}', level='debug')
        uuid_subset = uuids[start:end]

        vm_details = get_multiple_vm_details(conn, uuid_subset, start)
        vm_list.extend(vm_details)
        start += step
        end += step

    else:
        if start < len(uuids):
            umsg.log(f'Getting VMs between {start} and {len(uuids)}, out of a total {len(uuids)}', level='debug')
            uuid_subset = uuids[start:len(uuids)]
            vm_details = get_multiple_vm_details(conn, uuid_subset, start)
            vm_list.extend(vm_details)

    return vm_list


def match_apps_to_turbo_vms(apps, turbo_vms, match_ip=True):
    for app in apps.values():
        for member in app.members:
            for vm in turbo_vms:
                if match_ip:
                    vm_ips = set(member['ip_address'].split(','))

                    if (vm['name'].lower() == member['name'].lower() and
                            vm_ips & set(vm['ip_address'])):
                        member['ip_address'] = vm['ip_address']
                        member['turbo_oid'] = vm['uuid']
                        app.member_uuids.add(vm['uuid'])
                        break

                if not match_ip:
                    if vm['name'].lower() == member['name'].lower():
                        member['ip_address'] = vm['ip_address']
                        member['turbo_oid'] = vm['uuid']
                        app.member_uuids.add(vm['uuid'])
                        break

    return apps


def make_apps_thru_atm(conn, apps):
    current_apps = {app['displayName']: app['uuid']
                    for app in conn.request('topologydefinitions')}

    for app in apps.values():
        if not app.member_uuids:
            umsg.log(f'No matching VMs found for app named: {app.name}, skipping')
            continue

        app.remove_members_without_matches()

        try:
            app.update_appl_topo(conn, current_apps[app.name])

        except KeyError:
            app.create_appl_topo(conn)

    return True


def get_csv_data(filename, csv_location, entity_headers, match_ip):
    reader = DifCsvReader(filename, csv_location, entity_headers, match_ip)
    while not reader.file_downloaded:
        try:
            data = reader.download_csv_data()

        except CsvFileNotFoundError:
            umsg.log('No CSV found, waiting and then retrying')
            time.sleep(60)

    return reader.read_csv(data)


def main(config_file):
    args = read_config_file(config_file)

    requests.packages.urllib3.disable_warnings(
        requests.packages.urllib3.exceptions.InsecureRequestWarning)
    umsg.init(level=args.get('LOG_LEVEL', 'info'))
    log_file = os.path.join(args.get('LOG_DIR', ''), args.get('LOG_FILE', ''))

    if log_file:
        handler = logging.handlers.RotatingFileHandler(log_file,
                                                       mode='a',
                                                       maxBytes=10*1024*1024,
                                                       backupCount=1,
                                                       encoding=None,
                                                       delay=0)
        umsg.add_handler(handler)

    else:
        umsg.add_handler(logging.StreamHandler())

    umsg.log('Starting script')
    csv_data = get_csv_data(filename=args['INPUT_CSV_NAME'],
                            csv_location=args['CSV_LOCATION'],
                            entity_headers=args.get('ENTITY_FIELD_MAP'),
                            match_ip=args.get('MATCH_IP', False))
    apps = parse_csv_into_apps(csv_data, args.get('APP_PREFIX', ''))
    vmt_conn = vc.Connection(os.environ['TURBO_ADDRESS'],
                             os.environ['TURBO_USERNAME'],
                             os.environ['TURBO_PASSWORD'])
    turbo_vms = get_turbo_vms(vmt_conn, start=0, end=500, step=500)
    apps = match_apps_to_turbo_vms(apps, turbo_vms, args.get('MATCH_IP', False))
    make_apps_thru_atm(vmt_conn, apps)

    umsg.log('Finished script')


if __name__ == '__main__':
    main(sys.argv[1])
