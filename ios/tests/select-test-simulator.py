#!/usr/bin/env python3
"""Choose and boot one available iPhone Simulator for synthetic CI tests."""
import json
import os
import re
import subprocess


def select_device(catalog):
    candidates = []
    for runtime, devices in catalog.get('devices', {}).items():
        if '.iOS-' not in runtime:
            continue
        version = tuple(int(part) for part in re.findall(r'\d+', runtime))
        for device in devices:
            if device.get('isAvailable') and device.get('name', '').startswith('iPhone'):
                candidates.append((version, device.get('state') == 'Booted', device.get('name', ''), device['udid']))
    if not candidates:
        raise RuntimeError('No available iPhone Simulator runtime is installed')
    _, booted, _, identifier = max(candidates)
    if not re.fullmatch(r'[A-Fa-f0-9-]{36}', identifier):
        raise RuntimeError('Unexpected simulator identifier')
    return identifier, booted


def main():
    catalog = json.loads(subprocess.check_output(['xcrun', 'simctl', 'list', 'devices', 'available', '--json']))
    identifier, booted = select_device(catalog)
    if not booted:
        subprocess.run(['xcrun', 'simctl', 'boot', identifier], check=True)
    subprocess.run(['xcrun', 'simctl', 'bootstatus', identifier, '-b'], check=True)
    output = os.environ.get('GITHUB_OUTPUT')
    if output:
        with open(output, 'a') as stream:
            stream.write('simulator_id=' + identifier + '\n')
    print('Synthetic runtime tests will use iPhone Simulator ' + identifier)


if __name__ == '__main__':
    main()
