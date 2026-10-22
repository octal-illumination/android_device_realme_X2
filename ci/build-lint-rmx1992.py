#!/usr/bin/env python3
"""build-lint-rmx1992.py — pre-submission static validation for the RMX1992 ROM layer.

Note: This code is purely AI-generated.

Encodes vanilla-LOS-23.2 build rules + our layer's consistency invariants so
preventable build failures are caught BEFORE burning a crave queue cycle.
Run with the repos checked out on the branch line you are about to build
(e.g. lineage-23.2). Exit 0 = all critical checks PASS; 1 = any FAIL; WARNs
never fail the run but must be reviewed.

Usage: python3 build-lint-rmx1992.py
"""
import glob
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = os.environ.get('X2_LINT_ROOT') or os.path.expanduser('~/Projects/android/devices/rmx1992')
DT = os.environ.get('X2_LINT_DT') or f'{ROOT}/roms/common/device/X2'
VND = os.environ.get('X2_LINT_VND') or f'{ROOT}/roms/common/vendor/realme'
fails, warns = [], []


def chk(name, ok, detail=''):
    print(('PASS  ' if ok else 'FAIL  ') + name + ((' — ' + detail) if detail else ''))
    if not ok:
        fails.append(name)


def warn(name, detail):
    print('WARN  ' + name + ' — ' + detail)
    warns.append(name)


# --- C0: branch consistency (the lint validates the WORKING TREE — both repos must sit on the same target line) ---
def c0():
    def branch_of(path):
        r = subprocess.run(['git', '-C', path, 'branch', '--show-current'], capture_output=True, text=True)
        return r.stdout.strip() or '(detached)'
    bd, bv = branch_of(DT), branch_of(VND)
    chk('C0 branch consistency', bd == bv and bd != '(detached)',
        f'device@{bd} vs vendor@{bv} — checkout the TARGET line in both before linting/submission')


# --- C1: BoardConfig 2ND-arch rule (verbatim base table, combo/TARGET_linux-arm.mk @lineage-23.2) ---
KNOWN_ARMv8_CORES = ['cortex-a53', 'cortex-a53.a57', 'cortex-a55', 'cortex-a73',
                     'cortex-a75', 'cortex-a76', 'kryo', 'kryo385', 'exynos-m1', 'exynos-m2']
KNOWN_ARMv82a_CORES = ['cortex-a55', 'cortex-a75', 'kryo385']


def board_var(name):
    src = open(f'{DT}/BoardConfig.mk').read()
    m = re.search(rf'^\s*{name}\s*:=\s*(\S+)\s*$', src, re.M)
    return m.group(1) if m else None


def c1():
    v2 = board_var('TARGET_2ND_ARCH_VARIANT')
    cv2 = board_var('TARGET_2ND_CPU_VARIANT') or 'generic'
    if cv2 in KNOWN_ARMv82a_CORES:
        chk('C1 BoardConfig 2ND-arch rule', v2 in (None, 'armv8-2a'),
            f'cpu={cv2} requires armv8-2a (got {v2})')
    elif cv2 in KNOWN_ARMv8_CORES:
        chk('C1 BoardConfig 2ND-arch rule', v2 in (None, 'armv8-a'),
            f'cpu={cv2} requires armv8-a (got {v2})')
    else:
        warn('C1 BoardConfig 2ND-arch rule', f'TARGET_2ND_CPU_VARIANT={cv2} outside base lists')
    chk('C1 primary TARGET_ARCH_VARIANT set', board_var('TARGET_ARCH_VARIANT') is not None)


# --- C10: make continuation integrity (born from job 306821: comment lines inside backslash blocks) ---
def c10():
    bad = []
    for mk in (f'{DT}/device.mk', f'{DT}/lineage_X2.mk'):
        lines = open(mk, encoding='utf-8', errors='replace').read().split('\n')
        for i, ln in enumerate(lines):
            if ln.rstrip().endswith('\\'):
                nxt = lines[i + 1] if i + 1 < len(lines) else ''
                if nxt.lstrip().startswith('#'):
                    # Only comments are proven-fatal (job 306821); blank continuation
                    # lines are legal GNU make (build-proven by job 306665's full parse).
                    bad.append(f'{os.path.relpath(mk, ROOT)}:{i + 2} comment inside continuation block')
    chk('C10 make continuation integrity', not bad, '; '.join(bad[:5]))


# --- C2: duplicate soong module names within each of our Android.bp files ---
def bp_names(path):
    return re.findall(r'^\s*name:\s*"([^"]+)"', open(path, encoding='utf-8', errors='replace').read(), re.M)


def c2():
    for bp in [f'{VND}/Android.bp'] + sorted(glob.glob(f'{DT}/**/*.bp', recursive=True)):
        names = bp_names(bp)
        dupes = sorted({n for n in names if names.count(n) > 1})
        chk(f'C2 dup modules [{os.path.relpath(bp, ROOT)}]', not dupes, ', '.join(dupes[:10]))


# --- C3: XML well-formedness ---
def c3():
    # Build-parsed XMLs only: device-tree configs/manifests + vendor VINTF fragments.
    # Stock data blobs (e.g. vendor/etc/data/dsi_config.xml — non-leading XML declaration)
    # are copied verbatim, never parsed by soong/make — QC stock quirk, not a build risk.
    xmls = sorted(glob.glob(f'{DT}/**/*.xml', recursive=True)
                  + glob.glob(f'{VND}/proprietary/**/vintf/**/*.xml', recursive=True))
    bad = []
    for x in xmls:
        try:
            ET.parse(x)
        except ET.ParseError as e:
            bad.append(f'{os.path.relpath(x, ROOT)}: {e}')
    chk('C3 XML well-formed', not bad, '; '.join(bad[:5]))


# --- C4: bash syntax on our scripts ---
def c4():
    bad = []
    for sh in sorted(glob.glob(f'{ROOT}/roms/common/tools/*.sh') + glob.glob(f'{DT}/**/*.sh', recursive=True)):
        r = subprocess.run(['bash', '-n', sh], capture_output=True, text=True)
        if r.returncode:
            bad.append(f'{os.path.relpath(sh, ROOT)}: {r.stderr.strip()[:80]}')
    chk('C4 bash -n', not bad, '; '.join(bad[:5]))


# --- C5: Android.bp syntax — AOSP bpfmt full parser (falls back to brace balance) ---
BPFMT = os.environ.get('X2_LINT_BPFMT') or f'{ROOT}/roms/common/tools/bin/bpfmt'


def c5():
    bad = []
    use_bpfmt = os.access(BPFMT, os.X_OK)
    for bp in [f'{VND}/Android.bp'] + sorted(glob.glob(f'{DT}/**/*.bp', recursive=True)):
        rel = os.path.relpath(bp, ROOT)
        if use_bpfmt:
            r = subprocess.run([BPFMT, '-d', bp], capture_output=True, text=True)
            if r.returncode:
                bad.append(f'{rel}: {(r.stderr or r.stdout).strip()[:60] or "bpfmt parse error"}')
        else:
            s = open(bp, encoding='utf-8', errors='replace').read()
            if s.count('{') != s.count('}'):
                bad.append(rel)
    chk(f'C5 Android.bp syntax ({"bpfmt full parse" if use_bpfmt else "brace fallback"})', not bad, '; '.join(bad[:4]))


# --- C12: BoardConfig required vars + value domains (from base build/make/core/board_config.mk @lineage-23.2) ---
def c12():
    src = open(f'{DT}/BoardConfig.mk').read()

    def val(name):
        m = re.search(rf'^\s*{name}\s*:=\s*(\S*)\s*$', src, re.M)
        return m.group(1) if m else None

    problems = []
    for req in ('TARGET_ARCH', 'TARGET_CPU_ABI'):
        if not val(req):
            problems.append(f'{req} not set (base board_config.mk error-rule)')
    if val('TARGET_ARCH_SUITE') is not None and val('TARGET_ARCH') is not None:
        problems.append('sets both TARGET_ARCH and TARGET_ARCH_SUITE (base forbids)')
    for m in re.finditer(r'^\s*(MALLOC_[A-Z0-9_]*)\s*:=\s*(\S*)\s*$', src, re.M):
        if m.group(2) not in ('true', 'false', ''):
            problems.append(f'{m.group(1)} must be true/false/empty, got {m.group(2)}')
    if val('TARGET_2ND_ARCH') and not val('TARGET_2ND_CPU_ABI'):
        problems.append('TARGET_2ND_ARCH set without TARGET_2ND_CPU_ABI')
    if not val('BOARD_BOOTIMAGE_PARTITION_SIZE'):
        problems.append('BOARD_BOOTIMAGE_PARTITION_SIZE not set (non-A/B dedicated boot device)')
    chk('C12 BoardConfig required vars (base rules)', not problems, '; '.join(problems[:4]))


# --- C13 (WARN): tree-manifest HALs without a blob VINTF fragment (info review) ---
def c13():
    try:
        tree_hal = set()
        for elem in ET.parse(f'{DT}/manifest.xml').getroot().iter('hal'):
            n = elem.find('name')
            if n is not None and n.text:
                tree_hal.add(n.text)
        blob_hal = set()
        for f in glob.glob(f'{VND}/proprietary/**/vintf/**/*.xml', recursive=True):
            for elem in ET.parse(f).getroot().iter('hal'):
                n = elem.find('name')
                if n is not None and n.text:
                    blob_hal.add(n.text)
        missing = sorted(tree_hal - blob_hal)
        warn('C13 tree-manifest HALs w/o blob VINTF fragment (may be source-built)',
             ', '.join(missing[:8]) if missing else 'none — full overlap with blob fragments')
    except Exception as e:  # noqa: BLE001
        warn('C13 VINTF cross-check', f'skip: {e}')


# --- C6: list ↔ harvest ↔ generated-makefile coverage ---
def active_entries():
    out = []
    for line in open(f'{DT}/proprietary-files.txt'):
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        core = s[1:] if s.startswith('-') else s
        out.append(core.split('|')[0].split(';')[0].split(':')[0])
    return out


def c6():
    files = set()
    for root, _, fs in os.walk(f'{VND}/proprietary'):
        for f in fs:
            p = os.path.join(root, f)
            if not os.path.islink(p) and os.path.isfile(p):
                files.add('proprietary/' + os.path.relpath(p, f'{VND}/proprietary'))
    refs = set()
    for gen in (f'{VND}/Android.bp', f'{VND}/X2-vendor.mk'):
        src = open(gen, encoding='utf-8', errors='replace').read()
        refs |= set(re.findall(r'proprietary/[A-Za-z0-9_./+@~-]+', src))
    miss = sorted(files - refs)
    extra = sorted(refs - {f for f in files})
    chk('C6 makefile coverage (files all referenced)', not miss, f'{len(miss)} unreferenced: ' + ', '.join(miss[:5]))
    warn('C6 makefile coverage (refs without file)', f'{len(extra)} dangling refs (review): ' + ', '.join(extra[:5]) if extra else '')


# --- C7: zero-byte blobs ---
def c7():
    empty = [f for f in glob.glob(f'{VND}/proprietary/**/*', recursive=True)
             if os.path.isfile(f) and not os.path.islink(f) and os.path.getsize(f) == 0]
    chk('C7 no empty blobs', not empty, ', '.join(os.path.relpath(f, VND) for f in empty[:5]))


# --- C8: ELF sanity (machine must be ARM32/AARCH64/HEXAGON) ---
EM_OK = {40: 'ARM32', 183: 'AARCH64', 164: 'HEXAGON'}


def c8():
    bad = []
    for f in glob.glob(f'{VND}/proprietary/**/*.so', recursive=True):
        with open(f, 'rb') as fh:
            h = fh.read(20)
        if len(h) < 20 or h[:4] != b'\x7fELF':
            continue
        machine = h[18] | (h[19] << 8)
        if machine not in EM_OK:
            bad.append(f'{os.path.relpath(f, VND)}: e_machine={machine}')
    chk('C8 ELF machine sanity', not bad, ', '.join(bad[:5]))


# --- C9 (WARN): PRODUCT_PACKAGES not defined in our repos ---
def c9():
    pkgs = set()
    for mk in (f'{DT}/device.mk', f'{DT}/lineage_X2.mk'):
        block = False
        for line in open(mk):
            if re.match(r'\s*PRODUCT_PACKAGES\s*[+]?=', line):
                block = True
                continue
            if block:
                m = re.match(r'\s*([A-Za-z0-9_.-]+)\s*(\\|$)', line)
                if m and not line.strip().startswith('#'):
                    pkgs.add(m.group(1))
                if '\\' not in line:
                    block = False
    defined = set(bp_names(f'{VND}/Android.bp'))
    for bp in glob.glob(f'{DT}/**/*.bp', recursive=True):
        defined |= set(bp_names(bp))
    for mk in glob.glob(f'{DT}/**/*.mk', recursive=True):
        defined |= set(re.findall(r'LOCAL_(?:MODULE|PACKAGE_NAME)\s*:=\s*(\S+)', open(mk, errors='replace').read()))
    missing = sorted(pkgs - defined)
    warn('C9 PRODUCT_PACKAGES not in our repos (expect base-provided)',
         f'{len(missing)} names: ' + ', '.join(missing[:15]))


def main():
    for fn in (c0, c1, c12, c2, c3, c4, c5, c6, c7, c8, c9, c10, c13):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            chk(f'{fn.__name__} (internal)', False, f'{type(e).__name__}: {e}')
    print('-' * 60)
    print(f'RESULT: {len(fails)} FAIL, {len(warns)} WARN')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
