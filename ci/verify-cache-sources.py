#!/usr/bin/env python3
"""verify-cache-sources.py — resumable verification of the ref/ caches against real sources.

Note: This code is purely AI-generated.

WHY: a cache entry that claims "the base provides X" is a MASK if it is wrong — it hides a real
missing module. Verifying such a claim needs many HTTP fetches, which is slow and can die midway.
This tool therefore caches every fetched Android.bp to disk under ref/sources/<key>.bp and skips
anything already cached, so an interrupted run RESUMES instead of restarting.

Usage:
    python3 verify-cache-sources.py --project caf      # verify caf_repo_modules.txt
    python3 verify-cache-sources.py --project all
    python3 verify-cache-sources.py --project caf --report   # only print the last report

Exit 0 when every cached entry is corroborated, 1 when any entry is unsupported.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(HERE, 'ref')
SRC = os.path.join(REF, 'sources')
STATE = os.path.join(SRC, '_state.json')

# Project -> list of (repo, branch). Branches are taken from the LOS 23.2 manifest, NOT guessed
# (sm8150 projects are pinned to lineage-23.2-caf-sm8150, not lineage-23.2 — using the wrong
# branch produces false "not found" results, which has already happened once).
PROJECTS = {
    'caf': [
        ('LineageOS/android_hardware_qcom_audio', 'lineage-23.2-caf-sm8150'),
        ('LineageOS/android_hardware_qcom_media', 'lineage-23.2-caf-sm8150'),
        ('LineageOS/android_hardware_qcom_display', 'lineage-23.2-caf-sm8150'),
    ],
    'qti_display': [
        ('LineageOS/android_vendor_qcom_opensource_display', 'lineage-23.2'),
        ('LineageOS/android_vendor_qcom_opensource_display-commonsys', 'lineage-23.2'),
        ('LineageOS/android_vendor_qcom_opensource_display-commonsys-intf', 'lineage-23.2'),
    ],
}


def token():
    """Reuse the existing git keyring credential in-process. Never printed, never stored."""
    import subprocess
    try:
        out = subprocess.run(['git', 'credential', 'fill'], input='protocol=https\nhost=github.com\n\n',
                             capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return None
    for line in out.splitlines():
        if line.startswith('password='):
            return line[len('password='):]
    return None


def load_state():
    try:
        return json.load(open(STATE))
    except (OSError, ValueError):
        return {}


def save_state(st):
    os.makedirs(SRC, exist_ok=True)
    tmp = STATE + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(st, fh, indent=1, sort_keys=True)
    os.replace(tmp, STATE)          # atomic: a killed run never leaves a corrupt state file


def gh(url, tok):
    req = urllib.request.Request(url)
    if tok:
        req.add_header('Authorization', 'Bearer ' + tok)
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read().decode('utf-8', 'replace')


def tree(repo, branch, tok, st):
    key = f'{repo}@{branch}:tree:v2'   # v2 = includes Android.mk; bump invalidates old caches
    if key in st:
        return st[key]
    data = json.loads(gh(f'https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1', tok))
    # Android.mk matters as much as Android.bp: many caf modules are LOCAL_MODULE definitions.
    paths = [e['path'] for e in data.get('tree', [])
             if e['path'].endswith(('Android.bp', 'Android.mk'))]
    st[key] = paths
    save_state(st)
    return paths


def fetch_bp(repo, branch, path, tok):
    safe = re.sub(r'[^A-Za-z0-9_.-]', '_', f'{repo}__{branch}__{path}')
    dest = os.path.join(SRC, safe)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return open(dest, encoding='utf-8', errors='replace').read(), True
    txt = gh(f'https://raw.githubusercontent.com/{repo}/{branch}/{path}', tok)
    os.makedirs(SRC, exist_ok=True)
    with open(dest, 'w') as fh:
        fh.write(txt)
    return txt, False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--project', default='caf', choices=sorted(PROJECTS) + ['all'])
    ap.add_argument('--cache', default='caf_repo_modules.txt')
    ap.add_argument('--report', action='store_true')
    args = ap.parse_args()

    projects = sorted(PROJECTS) if args.project == 'all' else [args.project]
    st = load_state()
    tok = token()
    if not tok:
        print('WARN: no github token available; unauthenticated requests are rate-limited', file=sys.stderr)

    blobs, fetched, cached = [], 0, 0
    for proj in projects:
        for repo, branch in PROJECTS[proj]:
            try:
                paths = tree(repo, branch, tok, st)
            except Exception as e:                                   # noqa: BLE001
                print(f'  ! tree {repo}@{branch}: {type(e).__name__} {e}', file=sys.stderr)
                continue
            for p in paths:
                try:
                    txt, was_cached = fetch_bp(repo, branch, p, tok)
                except Exception as e:                               # noqa: BLE001
                    print(f'  ! fetch {repo}/{p}: {type(e).__name__}', file=sys.stderr)
                    continue
                blobs.append(txt)
                if was_cached:
                    cached += 1
                else:
                    fetched += 1
                    time.sleep(0.15)          # be polite; keeps the whole sweep resumable
    print(f'sources: {cached} from cache, {fetched} fetched this run, {len(blobs)} total')

    joined = '\n'.join(blobs)
    defined = set(re.findall(r'name:\s*"([^"]+)"', joined))            # Android.bp modules
    defined |= set(re.findall(r'LOCAL_MODULE\s*:?=\s*(\S+)', joined))  # Android.mk modules
    cache_path = os.path.join(REF, args.cache)
    entries = {l.split()[0] for l in open(cache_path) if l.strip() and not l.startswith('#')}
    ok = sorted(entries & defined)
    bad = sorted(entries - defined)
    print(f'{args.cache}: {len(entries)} entries -> {len(ok)} corroborated, {len(bad)} NOT FOUND')
    for b in bad:
        print(f'   UNSUPPORTED: {b}')
    report = {'cache': args.cache, 'entries': len(entries), 'corroborated': len(ok), 'unsupported': bad}
    json.dump(report, open(os.path.join(SRC, f'_report_{args.cache}.json'), 'w'), indent=1)
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
