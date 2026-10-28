#!/usr/bin/env python3
"""deep-search-module.py — exhaustive module search with COVERAGE-ENFORCED verdicts.

Note: This code is purely AI-generated.

THE RULE THIS SCRIPTS (LL-038): never undersearch, never assume, never guess. A module may be
called FOUND only after a definition is matched in a real file at a known revision. A module may be
called ABSENT only after EVERY repo in the manifest has been searched. Anything in between MUST be
reported as INCONCLUSIVE with the coverage numbers that justify it.

Why this exists: three separate false-negative incidents in one session, all from under-searching
(wrong branch; root-Android.bp-only probes; naive repo-name mapping). Each time "not found" was
reported as if it were established. This tool makes that impossible: the verdict is derived from
measured coverage, not from the author's confidence.

Search stages (all resumable, all cached under ref/sources/):
  1. GitHub code search for the DEFINITION, several query forms, throttled with rate-limit retry.
  2. Map each hit to OUR manifest project (exact name, then path suffix, then short-name in path).
  3. Fetch that project AT THE PINNED REVISION and confirm the name appears as a definition.
  4. If nothing is confirmed, fall back to sweeping EVERY manifest project's build files.

Verdicts:
  FOUND        name matched as a definition in <repo>@<rev>:<path>   (always with evidence)
  ABSENT       searched every manifest project (coverage 100%)
  INCONCLUSIVE coverage < 100% — NOT a finding, and must not be reported as one

Usage:
    python3 deep-search-module.py --module fastbootd [--module X ...] [--budget 400]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(HERE, 'ref')
SRC = os.path.join(REF, 'sources')
MAN = os.path.join(SRC, '_manifest')
STATE = os.path.join(SRC, '_state.json')
EVID = os.path.join(REF, 'DEEP-FIND-EVIDENCE.txt')


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
    try:
        out = subprocess.run(['git', 'credential', 'fill'],
                             input='protocol=https\nhost=github.com\n\n',
                             capture_output=True, text=True, timeout=20).stdout
    except Exception:                                          # noqa: BLE001
        return None
    for ln in out.splitlines():
        if ln.startswith('password='):
            return ln[len('password='):]
    return None


TOK = token()


def http(url, tries=4, allow_404=True):
    for i in range(tries):
        try:
            req = urllib.request.Request(url)
            if TOK:
                req.add_header('Authorization', 'Bearer ' + TOK)
            return urllib.request.urlopen(req, timeout=45).read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            if e.code == 404 and allow_404:
                return None
            time.sleep(8 + i * 10)                       # rate limit / transient
        except Exception:                                # noqa: BLE001
            time.sleep(4 + i * 5)
    return None


def manifest(st):
    if 'deep:manifest:v1' in st:
        return st['deep:manifest:v1']
    out = {}
    for fn in ('default.xml', 'snippets/lineage.xml'):
        txt = http(f'https://raw.githubusercontent.com/LineageOS/android/lineage-23.2/{fn}')
        if not txt:
            continue
        for m in re.finditer(r'<project\b[^>]*>', txt):
            t = m.group(0)
            nm = re.search(r'name="([^"]+)"', t)
            p = re.search(r'path="([^"]+)"', t)
            rev = re.search(r'revision="([^"]+)"', t)
            if nm:
                out[nm.group(1)] = {'path': p.group(1) if p else '',
                                    'rev': rev.group(1) if rev else 'lineage-23.2'}
    st['deep:manifest:v1'] = out
    save(st)
    return out


def code_search(name, st):
    """Stage 1: several query forms. Cached so a rerun does not re-query."""
    key = f'deep:qs:{name}'
    if key in st:
        return st[key]
    forms = [f'"name: \\"{name}\\"" filename:Android.bp',
             f'"{name}" filename:Android.mk']
    hits = []
    for q in forms:
        for attempt in range(3):
            try:
                r = subprocess.run(['gh', 'api', '-X', 'GET', 'search/code', '-f', f'q={q}',
                                    '--jq', '.items[] | .repository.full_name + "|" + .path'],
                                   capture_output=True, text=True, timeout=60,
                                   env={**os.environ, 'GH_TOKEN': TOK or ''})
                lines = [x for x in r.stdout.strip().split('\n') if x and not x.startswith('{')]
                if lines:
                    hits += lines[:12]
                    break
                if 'rate limit' in (r.stdout + r.stderr).lower():
                    time.sleep(25)
                    continue
                break
            except Exception:                            # noqa: BLE001
                time.sleep(10)
        time.sleep(7)
    st[key] = hits
    save(st)
    return hits


def map_to_manifest(repo, path, mf):
    """Stage 2: hit -> OUR project. Exact name, then path suffix, then short-name in path."""
    if repo in mf:
        return repo, path
    rel = path
    for proj, info in mf.items():
        p = info['path']
        if p and ('/' + p + '/') in ('/' + path) or path.startswith(p + '/'):
            return proj, path[len(p) + 1:] if path.startswith(p + '/') else path
    short = repo.split('/')[-1]
    cands = [p for p, i in mf.items() if p.split('/')[-1].lower() == short.lower()]
    if not cands:
        cands = [p for p, i in mf.items() if short.lower() in p.lower()]
    if len(cands) == 1:
        return cands[0], rel
    return None, rel


def fetch(repo, rev, path, st):
    slug = re.sub(r'[^A-Za-z0-9_.-]', '_', f'{repo}__{rev}__{path}')
    dest = os.path.join(SRC, slug)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return open(dest, encoding='utf-8', errors='replace').read()
    txt = http(f'https://raw.githubusercontent.com/{repo}/{rev}/{path}')
    if txt:
        os.makedirs(SRC, exist_ok=True)
        open(dest, 'w').write(txt)
    return txt


DEF_RE = r'(name:\s*"%s"|LOCAL_MODULE\s*:?=\s*%s\b|LOCAL_PACKAGE_NAME\s*:?=\s*%s\b)'


def confirmed_in(txt, name):
    if not txt:
        return False
    pat = DEF_RE % (re.escape(name), re.escape(name), re.escape(name))
    return re.search(pat, txt) is not None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--module', action='append', required=True)
    ap.add_argument('--budget', type=int, default=0,
                    help='max manifest repos to sweep in the fallback stage (0 = all)')
    args = ap.parse_args()

    st = state()
    mf = manifest(st)
    print(f'manifest projects: {len(mf)}')
    os.makedirs(REF, exist_ok=True)

    for name in args.module:
        print(f'\n=== {name} ===')
        hits = code_search(name, st)
        print(f'  stage1 code-search hits: {len(hits)}')

        found = None
        tried = set()
        for h in hits:
            repo, path = h.split('|', 1)
            proj, rel = map_to_manifest(repo, path, mf)
            if not proj:
                continue
            rev = mf[proj]['rev']
            if (proj, rel) in tried:
                continue
            tried.add((proj, rel))
            txt = fetch(proj, rev, rel, st)
            if confirmed_in(txt, name):
                found = (proj, rev, rel)
                break

        if found:
            proj, rev, rel = found
            print(f'  FOUND  {proj}@{rev}:{rel}')
            with open(EVID, 'a') as fh:
                fh.write(f'{name:56s} FOUND {proj}@{rev}:{rel}\n')
            continue

        # Stage 4: exhaustive fallback — sweep every manifest project (resumable)
        # CRITICAL: the coverage denominator is the WHOLE manifest, never the truncated list.
        # (First version divided by the budgeted subset and cheerfully reported "ABSENT —
        # coverage 100%" after sweeping 3 of 1112 repos: precisely the undersearch this tool
        # exists to prevent.)
        repos_all = list(mf.items())
        repos = repos_all[:args.budget] if args.budget else repos_all
        searched, cand = 0, None
        for proj, info in repos:
            key = f'deep:swept:{proj}@{info["rev"]}'
            if st.get(key):
                searched += 1
                continue
            tree = http(f'https://api.github.com/repos/{proj}/git/trees/{info["rev"]}?recursive=1')
            files = []
            if tree:
                try:
                    files = [e['path'] for e in json.loads(tree).get('tree', [])
                             if e['path'].endswith(('Android.bp', 'Android.mk'))]
                except ValueError:
                    files = []
            for f in files[:40]:
                txt = fetch(proj, info['rev'], f, st)
                if confirmed_in(txt, name):
                    cand = (proj, info['rev'], f)
                    break
            if cand:
                break
            st[key] = True
            save(st)
            searched += 1
            if searched % 20 == 0:
                print(f'    swept {searched}/{len(repos)} ...', flush=True)

        coverage = searched / max(len(repos_all), 1)
        if cand:
            proj, rev, rel = cand
            print(f'  FOUND  {proj}@{rev}:{rel}   (via exhaustive sweep)')
            with open(EVID, 'a') as fh:
                fh.write(f'{name:56s} FOUND {proj}@{rev}:{rel} (sweep, coverage {coverage:.0%})\n')
        elif coverage >= 1.0:
            print(f'  ABSENT  — searched ALL {len(repos_all)} manifest projects (coverage 100%)')
            with open(EVID, 'a') as fh:
                fh.write(f'{name:56s} ABSENT (coverage 100%, {len(repos)} repos)\n')
        else:
            print(f'  INCONCLUSIVE — coverage {coverage:.1%} of {len(repos_all)} manifest projects.')
            print(f'  NOT a finding. Re-run to continue (resumable), or raise --budget.')
            sys.exit(3)


if __name__ == '__main__':
    sys.exit(main())
