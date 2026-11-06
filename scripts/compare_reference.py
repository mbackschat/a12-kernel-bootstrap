#!/usr/bin/env python3
"""Compare the built A12 jars with the copies inside an official Spring Boot distribution.

Usage: compare_reference.py <boot.jar> <state>/maven

Every kernel and metamodel jar nested in BOOT-INF/lib that this build also
produced is compared by entry names (classes and resources, not META-INF).
Matching names are evidence that a source build is complete, e.g. against a jar
from the A12 Tools bundle of the same release. Byte equality is not expected:
compilers, timestamps and gzip headers differ.
"""
import io
from pathlib import Path
import re
import sys
import zipfile

A12_JAR = re.compile(r'BOOT-INF/lib/((?:kernel|mm(?:typings|dmjsons|validators))-[^/]+\.jar)')


def entries(archive):
    return {name for name in archive.namelist() if not name.endswith('/') and not name.startswith('META-INF/')}


def compare(boot_jar, maven):
    built = {path.name: path for path in Path(maven).rglob('*.jar')}
    report = {}
    with zipfile.ZipFile(boot_jar) as boot:
        for name in boot.namelist():
            match = A12_JAR.fullmatch(name)
            if match and match[1] in built:
                with zipfile.ZipFile(io.BytesIO(boot.read(name))) as reference, zipfile.ZipFile(built[match[1]]) as ours:
                    expected, actual = entries(reference), entries(ours)
                report[match[1]] = {'missing': sorted(expected - actual), 'extra': sorted(actual - expected)}
    return report


if __name__ == '__main__':
    report = compare(*sys.argv[1:3])
    for jar, difference in sorted(report.items()):
        status = 'SAME' if not difference['missing'] and not difference['extra'] else 'DIFF'
        print(f"{status} {jar}: {len(difference['missing'])} missing, {len(difference['extra'])} extra")
        for kind in ['missing', 'extra']:
            for entry in difference[kind][:20]:
                print(f'       {kind}: {entry}')
    print(f'{len(report)} shared jars compared')
    sys.exit(any(d['missing'] or d['extra'] for d in report.values()))
