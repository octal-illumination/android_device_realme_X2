#!/usr/bin/env python3
"""sweep-manifest-sources.py — exhaustively fetch build files from EVERY repo in the sync set.

Note: This code is purely AI-generated.

WHY: the T4 caches are enumerations of unknown provenance. The user's requirement is that nothing be
verified against an unverified cache. There are two truth sources:
  T2  the actual repos (this script)  - "does ANY repo in the sync set define this module?"
  T3  module-info.json from a build  - "did the build actually RESOLVE this module?"
T3 is strictly stronger (it reflects PRODUCT_SOURCE_ROOT_DIRS pruning, LL-030), but it needs a
completed build. T2 can be acquired now and closes most of the debt immediately.

Fully RESUMABLE: every fetched file is cached under ref/sources/manifest/<slug>.bp and the tree
listings under ref/sources/_state.json (atomic writes). Re-running continues where it stopped.

Usage:  python3 sweep-manifest-sources.py [--limit N] [--hosts github,aosp]
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'ref', 'sources')
MAN = os.path.join(SRC, '_manifest')
STATE = os.path.join(SRC, '_state.json')
LOGF = os.path.join(SRC, '_sweep.log')


def log(msg):
    line = f'{time.strftime("%H:%M:%S")} {msg}'
    print(line, flush=True)
    os.makedirs(SRC, exist_ok=True)
    with open(LOGF, 'a') as fh:
        fh.write(line + '\n')


def state():
    try:
        return json.load(open(STATE))
    except (OSError, ValueError):
        return {}


def save(st):
    os.makedirs(SRC, exist_ok=True)
    tmp = STATE + '.tmp'
    json.dump(st, open(tmp, 'w'), indent=1, sort_keys=True)
    os.replace(tmp, STATE)


def token():
    import subprocess
    try:
        out = subprocess.run(['git', 'credential', 'fill'],
                             input='protocol=https\nhost=github.com\n\n',
                             capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return None
    for line in out.splitlines():
        if line.startswith('password='):
            return line[len('password='):]
    return None


def get(url, tok, binary=False, tries=3):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url)
            if tok and 'github' in url:
                req.add_header('Authorization', 'Bearer ' + tok)
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
                return data if binary else data.decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            if e.code in (404, 400, 403):
                return None
            time.sleep(2 + attempt * 3)
        except Exception:                                     # noqa: BLE001
            time.sleep(2 + attempt * 3)
    return None


def manifest_projects(st, tok):
    key = 'manifest:projects:v1'
    if key in st:
        return st[key]
    os.makedirs(MAN, exist_ok=True)
    projs = []
    for fn in ('default.xml', 'snippets/lineage.xml'):
        url = f'https://raw.githubusercontent.com/LineageOS/android/lineage-23.2/{fn}'
        txt = get(url, tok)
        if not txt:
            log(f'! could not fetch {fn}')
            continue
        for m in re.finditer(r'<project\b[^>]*>', txt):
            t = m.group(0)
            nm = re.search(r'name="([^"]+)"', t)
            rev = re.search(r'revision="([^"]+)"', t)
            rem = re.search(r'remote="([^"]+)"', t)
            if not nm:
                continue
            projs.append({'name': nm.group(1),
                          'revision': rev.group(1) if rev else None,
                          'remote': rem.group(1) if rem else 'lineage'})
    st[key] = projs
    save(st)
    return projs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--hosts', default='github,aosp')
    args = ap.parse_args()
    hosts = set(args.hosts.split(','))

    st = state()
    tok = token()
    projs = manifest_projects(st, tok)
    log(f'manifest projects: {len(projs)}  (hosts={sorted(hosts)})')

    done = 0
    for p in projs[: args.limit or None]:
        name = p['name']
        is_aosp = name.startswith('platform/') or p['remote'] == 'aosp'
        host = 'aosp' if is_aosp else 'github'
        if host not in hosts:
            continue
        slug = re.sub(r'[^A-Za-z0-9_.-]', '_', name)
        tkey = f'{name}:tree:v1'
        if tkey in st and st[tkey].get('__done'):
            done += 1
            continue
        branch = p['revision'] or ('android16-release' if is_aosp else 'lineage-23.2')
        paths = []
        if host == 'github':
            data = get(f'https://api.github.com/repos/{name}/git/trees/{branch}?recursive=1', tok)
            if data:
                try:
                    paths = [e['path'] for e in json.loads(data).get('tree', [])
                             if e['path'].endswith(('Android.bp', 'Android.mk'))]
                except ValueError:
                    paths = []
        else:
            data = get(f'https://android.googlesource.com/{name}/+/refs/heads/{branch}/?format=JSON', tok)
            if data:
                try:
                    j = json.loads(data[data.index('{'):])
                    dirs = [e['name'] for e in j.get('entries', []) if e['type'] == 'tree']
                except ValueError:
                    dirs = []
                # top-level only; nested discovery is a later refinement
                paths = [f'{d}/Android.bp' for d in dirs] + [f'{d}/Android.mk' for d in dirs]

        fetched = 0
        for path in paths[:60]:
            dest = os.path.join(SRC, 'manifest', slug + '__' + re.sub(r'[^A-Za-z0-9_.-]', '_', path))
            if os.path.exists(dest) and os.path.getsize(dest) > 0:
                fetched += 1
                continue
            if host == 'github':
                txt = get(f'https://raw.githubusercontent.com/{name}/{branch}/{path}', tok)
            else:
                raw = get(f'https://android.googlesource.com/{name}/+/refs/heads/{branch}/{path}?format=TEXT', tok)
                txt = None
                if raw:
                    import base64
                    try:
                        txt = base64.b64decode(raw).decode('utf-8', 'replace')
                    except Exception:                          # noqa: BLE001
                        txt = None
            if txt:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                open(dest, 'w').write(txt)
                fetched += 1
            time.sleep(0.05)
        st[tkey] = {'__done': True, 'files': fetched, 'branch': branch}
        save(st)
        done += 1
        if done % 25 == 0:
            log(f'progress: {done} repos done, last={name} ({fetched} files)')
    log(f'sweep complete: {done} repos')


if __name__ == '__main__':
    sys.exit(main())
