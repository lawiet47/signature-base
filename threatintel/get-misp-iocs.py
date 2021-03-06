#!/usr/bin/env python
# -*- coding: iso-8859-1 -*-
# -*- coding: utf-8 -*-
#
# Get-MISP-IOCs
# Retrieves IOCs from MISP and stores them in appropriate format

MISP_KEY = '--- YOUR API KEY ---'
MISP_URL = 'https://misppriv.circl.lu'


import sys
import json
import argparse
import os
import re
import io
from pymisp import PyMISP

class MISPReceiver():

    hash_iocs = {}
    filename_iocs = {}
    c2_iocs = {}
    yara_rules = {}

    debugon = False

    # Output
    siem_mode = False
    separator = ";"
    use_headers = False
    use_filename_regex = True

    def __init__(self, misp_key, misp_url, misp_verify_cert, siem_mode=False, debugon=False):
        self.misp = PyMISP(misp_url, misp_key, misp_verify_cert, 'json')
        self.debugon = debugon
        if siem_mode:
            self.siem_mode = True
            self.separator = ","
            self.use_headers = True
            self.use_filename_regex = False

    def get_iocs_last(self, last):

        # Retrieve events from MISP
        result = self.misp.download_last(last)
        self.events = result['response']

        # Process each element (without related eevents)
        for event_element in self.events:
            event = event_element["Event"]

            # Info for Comment
            info = event['info']
            uuid = event['uuid']
            comment = "{0} - UUID: {1}".format(info.encode('unicode_escape'), uuid)

            # Event data
            for attribute in event['Attribute']:

                # Skip iocs that are not meant for ioc detection
                if attribute['to_ids'] == False:
                    continue

                # Value
                value = attribute['value']

                # Non split type
                if '|' not in attribute['type']:
                    self.add_ioc(attribute['type'], value, comment, uuid, info)
                # Split type
                else:
                    # Prepare values
                    type1, type2 = attribute['type'].split('|')
                    value1, value2 = value.split('|')
                    # self.add_ioc(type1, value1, comment)
                    self.add_ioc(type2, value2, comment, uuid, info)

    def add_ioc(self, ioc_type, value, comment, uuid, info):
        # Cleanup value
        value = value.encode('unicode_escape')
        # Debug
        if self.debugon:
            print("{0} = {1}".format(ioc_type, value))
        # C2s
        if ioc_type in ('hostname', 'ip-dst', 'domain'):
            if value == '127.0.0.1':
                return
            self.c2_iocs[value] = comment
        # Hash
        if ioc_type in ('md5', 'sha1', 'sha256'):
            # No empty files
            if value == 'd41d8cd98f00b204e9800998ecf8427e' or \
                            value == 'da39a3ee5e6b4b0d3255bfef95601890afd80709' or \
                            value == 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855':
                return
            self.hash_iocs[value] = comment
        # Filenames
        if ioc_type in ('filename', 'filepath'):
            # Add prefix to filenames
            if not re.search(r'^([a-zA-Z]:|%)', value):
                if not self.siem_mode:
                    value = "\\\\{0}".format(value)
            if self.use_filename_regex:
                self.filename_iocs[my_escape(value)] = comment
            else:
                self.filename_iocs[value.decode('string_escape')] = comment
        # Yara
        if ioc_type in ('yara'):
            self.add_yara_rule(value, uuid, info)

    def add_yara_rule(self, yara_rule, uuid, info):
        identifier = generate_identifier(info)
        self.yara_rules[identifier] = r'%s' % repair_yara_rule(yara_rule.decode('string_escape'), uuid)

    def write_iocs(self, output_path, output_path_yara):
        # Write C2 IOCs
        self.write_file(os.path.join(output_path, "misp-c2-iocs.txt"), self.c2_iocs, "c2")
        # Write Filename IOCs
        self.write_file(os.path.join(output_path, "misp-filename-iocs.txt"), self.filename_iocs, "filename")
        # Write Hash IOCs
        self.write_file(os.path.join(output_path, "misp-hash-iocs.txt"), self.hash_iocs, "hash")
        # Yara
        if len(self.yara_rules) > 0:
            # Create dir if not exists
            if not os.path.exists(output_path_yara):
                os.makedirs(output_path_yara)
            # Loop through rules (keys are identifiers used for file names)
            for yara_rule in self.yara_rules:
                output_rule_filename = os.path.join(output_path_yara, "%s.yar" % yara_rule)
                self.write_yara_rule(output_rule_filename, self.yara_rules[yara_rule])
            print("{0} YARA rules written to directory {1}".format(len(self.yara_rules), output_path_yara))

    def write_file(self, ioc_file, iocs, ioc_type):
        with open(ioc_file, 'w') as file:
            if self.use_headers:
                file.write("{0}{1}description\n".format(ioc_type, self.separator))
            for ioc in iocs:
                file.write("{0}{2}{1}\n".format(ioc,iocs[ioc],self.separator))
        print("{0} IOCs written to file {1}".format(len(iocs), ioc_file))

    def write_yara_rule(self, yara_file, yara_rule):
        # Write the YARA rule
        with io.open(yara_file, 'wb') as fh:
            fh.write(r'%s' % yara_rule)


def generate_identifier(string):
    valid_chars = '-_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
    return ''.join(char for char in string if char in valid_chars)


def repair_yara_rule(yara_rule, uuid):
    # Wrong upper ticks when copied & pasted from a PDF
    yara_rule = yara_rule.replace('\u201c', r'"')
    yara_rule = yara_rule.replace('\u201d', r'"')
    # Missing rule name
    name = uuid.replace('-', '_')
    yara_rule = re.sub(r'^[\W]*\{', 'rule rule_%s {' % name, yara_rule)
    return yara_rule


def my_escape(string):
    # Escaping
    string = re.sub(r'([\-\(\)\.\[\]\{\}\\\+])',r'\\\1',string)
    # Fix the cases in which the value has already been escaped
    string = re.sub(r'\\\\\\\\',r'\\\\',string)
    return string


if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='MISP IOC Receiver')
    parser.add_argument('-u', help='MISP URL', metavar='URL', default=MISP_URL)
    parser.add_argument('-k', help='MISP API key', metavar='APIKEY', default=MISP_KEY)
    parser.add_argument('-l', help='Time frame (e.g. 2d, 12h - default=30d)', metavar='tframe', default='30d')
    parser.add_argument('-o', help='Output directory', metavar='dir', default='../iocs')
    parser.add_argument('-y', help='YARA rule output directory', metavar='yara-dir', default='../iocs/yara')
    parser.add_argument('--siem', action='store_true', help='CSV Output for use in SIEM systems (Splunk)', default=False)
    parser.add_argument('--verifycert', action='store_true', help='Verify the server certificate', default=False)
    parser.add_argument('--debug', action='store_true', default=False, help='Debug output')

    args = parser.parse_args()

    if len(args.k) != 40:
        print("Set an API key in script or via -k APIKEY.")
        sys.exit(0)

    # Create a receiver
    misp_receiver = MISPReceiver(misp_key=args.k, misp_url=args.u, misp_verify_cert=args.verifycert,
                                 siem_mode=args.siem, debugon=args.debug)

    # Retrieve the events and store the IOCs
    misp_receiver.get_iocs_last(args.l)

    # Write IOC files
    misp_receiver.write_iocs(args.o, args.y)

