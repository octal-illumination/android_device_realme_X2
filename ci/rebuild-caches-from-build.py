#!/usr/bin/env python3
"""rebuild-caches-from-build.py — regenerate the T4 module caches from BUILT TRUTH.

Note: This code is purely AI-generated.

WHY: base_module_universe.txt / base_interface_modules.txt / base_provided_packages.txt are
enumerations with unknown provenance. They have been demonstrated to be BOTH incomplete (the
universe lacks libbase/libc++/libcutils) AND to contain fiction (base_provided_packages listed
android.hardware.thermal-service.qti, which hid a real defect). Verifying against them is circular.

TRUTH SOURCE: the build itself. `out/target/product/<device>/module-info.json` is produced by
soong/kati and lists EVERY module the build actually resolved, with its installed files and
partition. That is ground truth for "does this module exist in this tree" — no enumeration guess.

USAGE (after a crave run completes):
    crave pull                       # or fetch module-info.json from the job workspace
    python3 rebuild-caches-from-build.py /path/to/module-info.json --out-dir ref

It writes, with provenance headers:
    base_module_universe.txt.new      every module name
    base_interface_modules.txt.new    modules with a hidl/aidl interface signature
    base_provided_packages.txt.new    modules that install at least one file
Review, then rename over the originals (nothing is overwritten automatically).
"""
import argparse
import json
import os
import re
import sys

HDR = ('# Note: This code is purely AI-generated.\n'
       '# REBUILT FROM BUILD TRUTH ({src}) on {when}\n'
       '# Source artifact: module-info.json produced by soong/kati for this exact tree.\n'
       '# This replaces a previous UNVERIFIED enumeration — see ref/VERIFICATION-STATUS.txt.\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('module_info')
    ap.add_argument('--out-dir', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ref'))
    args = ap.parse_args()

    with open(args.module_info, encoding='utf-8', errors='replace') as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        print('ERROR: module-info.json is not a JSON object', file=sys.stderr)
        return 1

    all_names, iface, provided = set(), set(), set()
    for name, info in data.items():
        if not isinstance(info, dict):
            continue
        all_names.add(name)
        # interfaces: soong records the module's "type"/class; aidl/hidl interfaces carry these
        blob = json.dumps(info)[:4000].lower()
        if ('hidl_interface' in blob or 'aidl_interface' in blob
                or re.search(r'@\d+\.\d+', name) or '::' in name):
            iface.add(name)
        installed = info.get('installed') or []
        if installed:
            provided.add(name)

    import datetime
    when = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
    src = os.path.basename(args.module_info)
    os.makedirs(args.out_dir, exist_ok=True)
    for fn, names in (('base_module_universe.txt.new', all_names),
                      ('base_interface_modules.txt.new', iface),
                      ('base_provided_packages.txt.new', provided)):
        path = os.path.join(args.out_dir, fn)
        with open(path, 'w') as fh:
            fh.write(HDR.format(src=src, when=when))
            for n in sorted(names):
                fh.write(n + '\n')
        print(f'  {fn}: {len(names)} entries')

    print('\nNothing was overwritten. Review, then move the .new files over the originals.')
    print('Expected effect: C63\'s "cache-only" INFO count drops, because these lists now match the'
          '\ntree the build actually resolved rather than an enumeration guess.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
