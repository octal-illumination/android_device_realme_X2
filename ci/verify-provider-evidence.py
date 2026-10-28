#!/usr/bin/env python3
"""verify-provider-evidence.py — turn code-search HITS into T2 truth for our sync set.

Note: This code is purely AI-generated.

The evidence file records where each cache-only PRODUCT_PACKAGES entry was FOUND (any upstream
repo). That proves existence, not availability to US. This closes the gap WITHOUT waiting for a
build: for every hit it finds the matching project in OUR manifest, checks out the SAME revision we
build, fetches that exact Android.bp/Android.mk, and confirms the module name is really defined
there. Confirmed files land in ref/sources/ so the lint counts them as T2 (fetched-source) truth.

Resumable: files already in ref/sources/ are not re-fetched.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(HERE, 'ref')
SRC = os.path.join(REF, 'sources')
EVID = os.path.join(REF, 'PRODUCT_PACKAGES-provider-evidence.txt')


def token():
    try:
        out = subprocess.run(['git', 'credential', 'fill'],
                             input='protocol=https\nhost=github.com\n\n',
                             capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return None
    for ln in out.splitlines():
        if ln.startswith('password='):
            return ln[len('password='):]
    return None


def manifest_map(tok):
    """project name -> (path, revision) for every project in the LOS 23.2 manifest."""
    key = {}
    for fn in ('default.xml', 'snippets/lineage.xml'):
        url = f'https://raw.githubusercontent.com/LineageOS/android/lineage-23.2/{fn}'
        try:
            req = urllib.request.Request(url)
            req.add_header('Authorization', 'Bearer ' + tok)
            txt = urllib.request.urlopen(req, timeout=45).read().decode('utf-8', 'replace')
        except Exception:                                      # noqa: BLE001
            continue
        for m in re.finditer(r'<project\b[^>]*>', txt):
            t = m.group(0)
            nm = re.search(r'name="([^"]+)"', t)
            rev = re.search(r'revision="([^"]+)"', t)
            if nm:
                key[nm.group(1)] = rev.group(1) if rev else None
    return key


def fetch(repo, rev, path, tok):
    slug = re.sub(r'[^A-Za-z0-9_.-]', '_', f'{repo}__{rev or "default"}__{path}')
    dest = os.path.join(SRC, slug)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return open(dest, encoding='utf-8', errors='replace').read()
    url = f'https://raw.githubusercontent.com/{repo}/{rev or "lineage-23.2"}/{path}'
    for _ in range(3):
        try:
            req = urllib.request.Request(url)
            req.add_header('Authorization', 'Bearer ' + tok)
            txt = urllib.request.urlopen(req, timeout=45).read().decode('utf-8', 'replace')
            open(dest, 'w').write(txt)
            return txt
        except Exception:                                      # noqa: BLE001
            time.sleep(3)
    return None


def main():
    tok = token()
    mmap = manifest_map(tok)
    print(f'manifest projects: {len(mmap)}')
    rows = []
    for ln in open(EVID, encoding='utf-8', errors='replace'):
        if ln.startswith('#') or not ln.strip():
            continue
        parts = ln.split(None, 1)
        if len(parts) != 2:
            continue
        mod, loc = parts[0], parts[1].strip()
        if '|' not in loc:
            continue
        repo, path = loc.split('|', 1)
        rows.append((mod, repo, path))

    confirmed, unresolved = [], []
    for mod, repo, path in rows:
        target = repo if repo in mmap else None
        if target is None:                       # try the LineageOS equivalent by short name
            short = repo.split('/')[-1]
            for cand in (f'LineageOS/{short}', f'platform/{short}'):
                if cand in mmap:
                    target = cand
                    break
        if target is None:
            unresolved.append((mod, repo, 'repo not in our manifest'))
            continue
        rev = mmap[target] or 'lineage-23.2'
        txt = fetch(target, rev, path, tok)
        if not txt:
            unresolved.append((mod, target, f'fetch failed @{rev}:{path}'))
            continue
        if re.search(rf'name:\s*"{re.escape(mod)}"', txt) or \
                re.search(rf'LOCAL_MODULE\s*:?=\s*{re.escape(mod)}\b', txt):
            confirmed.append((mod, target, rev, path))
        else:
            unresolved.append((mod, target, f'name not in {path}'))
        time.sleep(0.2)

    print(f'\nCONFIRMED against OUR pinned revision: {len(confirmed)}/{len(rows)}')
    for c in confirmed:
        print(f'  {c[0]:52s} {c[1]}@{c[2]}')
    if unresolved:
        print(f'\nSTILL UNRESOLVED: {len(unresolved)}')
        for u in unresolved:
            print(f'  {u[0]:52s} {u[1]} — {u[2]}')
    json.dump({'confirmed': confirmed, 'unresolved': unresolved},
              open(os.path.join(REF, '_provider_confirmation.json'), 'w'), indent=1)
    return 0


if __name__ == '__main__':
    sys.exit(main())
