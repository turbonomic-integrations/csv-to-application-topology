import csv
import json
import sys
import logging
import re
import copy
import os

import vmtconnect as vc
import umsg
import requests


class NoIpAddressFound(Exception):
    pass


class UnknownAppDefinitionMethod(Exception):
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

        if isinstance(ips, list):
            ip_addresses.extend(ips)

        if isinstance(ips, str):
            regex_str = "\\b\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\b"
            matches = re.findall(regex_str, ips)
            ip_addresses.extend(matches)

        if not ip_addresses:
            raise NoIpAddressFound()

        return ip_addresses

    def add_member(self, member_name, member_ip):
        member_info = {'name': member_name,
                       'ip_address': self._process_ips(member_ip),
                       'turbo_oid': None}

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

    def send_to_appl_topo(self, conn):
        umsg.log(f'Creating application for BusinessApplication named: {self.name}')
        dto_template = {"displayName": self.name,
                        "entityType": "BusinessApplication",
                        "entityDefinitionData": {
                            "manualConnectionData": {
                                "VirtualMachine": {
                                    "staticConnections": list(self.member_uuids)
                                    }
                                }
                            },
                        }
        dto = json.dumps(dto_template)
        res = conn.request('topologydefinitions', method='POST', dto=dto)
        umsg.log(f'Successfully created app {self.name}. Details: {res}')

        return True


def read_csv(filename):
    """Read in CSV file to dict
    Parameters:
        filename - str - Path to CSV file

    Returns:
        List of dicts, where each dict is a row in the input CSV
    """
    data = []
    with open(filename, 'r', encoding='utf-8-sig') as fp:
        try:
            csv_data = csv.DictReader(fp)
            for row in csv_data:
                data.append(row)

        except Exception as e:
            umsg.log(f'Error reading input CSV: {e}', level='error')
            raise e

    return data


def read_config_file(config_file):
    """Read JSON config file"""
    with open(config_file, 'r') as fp:
        try:
            return json.loads(fp.read())

        except TypeError:
            umsg.log(f'{config_file} must be JSON format', level='error')


def parse_csv_into_apps(csv_data, prefix,
                        headers={'app_name': 'app_name',
                                 'entity_name': 'vm_name',
                                 'entity_ip': 'vm_ip'}):
    """Parse input CSV into dictionary of UserDefinedApps
    Parameters:
        csv_data - list - List of dicts from read_csv
        headers - dict - Optional mapping for user-defined CSV column names
    """
    app_dict = {}
    row_count = 1

    umsg.log('Looking for apps and associated VMs...')

    for row in csv_data:
        row_count += 1
        if not row[headers['app_name']]:
            umsg.log(f'No application defined on row {row_count} of input CSV, skipping',
                     level='warn')
            continue

        app_name = f"{prefix}{row[headers['app_name']]}"

        if app_name in app_dict.keys():
            app = app_dict[app_name]

        else:
            app = UserDefinedApp(app_name)
            app_dict[app_name] = app

        try:
            app.add_member(member_name=row[headers['entity_name']],
                           member_ip=row[headers['entity_ip']])

        except NoIpAddressFound:
            umsg.log(f'No IP address defined on row {row_count} of input CSV, skipping',
                     level='warn')

    return app_dict


def get_vm_info(vm_details, conn):
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
            vm_details = get_vm_info(single_vm_results, conn)

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
                vm_details = get_vm_info(vm, conn)
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
                    if (match_ip and len(set(member['ip_address']) & set(vm['ip_address'])) > 0):
                        member['ip_address'] = vm['ip_address']
                        member['turbo_oid'] = vm['uuid']
                        app.member_uuids.add(vm['uuid'])
                        break

                if not match_ip:
                    if vm['name'] == member['name']:
                        member['ip_address'] = vm['ip_address']
                        member['turbo_oid'] = vm['uuid']
                        app.member_uuids.add(vm['uuid'])
                        break

    return apps


def make_apps_thru_atm(conn, apps):
    current_apps = {app['displayName']
                    for app in conn.request('topologydefinitions')}

    for app in apps.values():
        if not app.member_uuids:
            umsg.log(f'No matching VMs found for app named: {app.name}, skipping')

        elif app.name in current_apps:
            umsg.log(f'Application named {app.name} already exists in {conn.host}, skipping')

        else:
            app.remove_members_without_matches()
            app.send_to_appl_topo(conn)

    return True


def make_apps_thru_dif():
    pass


def main(config_file, username, password):
    args = read_config_file(config_file)

    requests.packages.urllib3.disable_warnings(
        requests.packages.urllib3.exceptions.InsecureRequestWarning)
    umsg.init(level='debug')
    log_file = os.path.join(args['LOG_DIR'], args['LOG_FILE'])

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
    csv_file = os.path.join(args['INPUT_CSV_DIR'], args['INPUT_CSV_NAME'])
    csv = read_csv(csv_file)
    apps = parse_csv_into_apps(csv, args['APP_PREFIX'],
                               headers=args['INPUT_CSV_FIELD_MAP'])

    vmt_conn = vc.Connection(args['TURBO_TARGET'], username, password)

    turbo_vms = get_turbo_vms(vmt_conn, start=0, end=500, step=500)
    apps = match_apps_to_turbo_vms(apps, turbo_vms, args['MATCH_IP'])

    if args['APP_DEFINITION_METHOD'].upper() not in ('ATM', 'DIF'):
        umsg.log('APP_DEFINITION_METHOD must be either "ATM" or "DIF"',
                 level='error')
        raise UnknownAppDefinitionMethod()

    if args['APP_DEFINITION_METHOD'].upper() == 'ATM':
        make_apps_thru_atm(vmt_conn, apps)

    if args['APP_DEFINITION_METHOD'].upper() == 'DIF':
        make_apps_thru_dif(vmt_conn, apps)

    umsg.log('Finished script')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3])
