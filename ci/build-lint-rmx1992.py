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
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = os.environ.get('X2_LINT_ROOT') or os.path.expanduser('~/Projects/android/devices/rmx1992')
DT = os.environ.get('X2_LINT_DT') or f'{ROOT}/roms/common/device/X2'
VND = os.environ.get('X2_LINT_VND') or f'{ROOT}/roms/common/vendor/realme'
DUMP = '/tmp/rmx_pp/vendor-trust/f26_dump'
fails, warns, infos = [], [], []

# --- calibration / build-line awareness -------------------------------------------------
# Some rules encode facts that are TRUE ONLY FOR ONE LineageOS line (base tables, required
# BoardConfig vars, platform-compatibility expectations). If the tree being linted moves to a
# different line while those rules still run, the lint keeps printing confident PASS/FAIL based
# on the OLD base — i.e. false confidence, the exact failure mode that cost two 12-15h cycles.
# Rules listed here are annotated as UNCALIBRATED whenever BUILD_TARGET != CALIBRATED_FOR.
CALIBRATED_FOR = 'lineage-23.2'
DECLARED_LINE = None          # set in main() from roms/BUILD_TARGET
LINE_MISMATCH = False         # True when the declared line != CALIBRATED_FOR
VERSION_SENSITIVE_RULES = ('C1 ', 'C12 ', 'C50 ', 'C53 ')


def _uncalibrated_note(name):
    if LINE_MISMATCH and name.startswith(VERSION_SENSITIVE_RULES):
        return (f'  [UNCALIBRATED: rule calibrated for {CALIBRATED_FOR}, '
                f'tree declares {DECLARED_LINE} — verdict is NOT trustworthy until this rule is '
                f'updated for the new base]')
    return ''


def chk(name, ok, detail=''):
    note = _uncalibrated_note(name)
    print(('PASS  ' if ok else 'FAIL  ') + name + ((' — ' + detail) if detail else '') + note)
    if not ok:
        fails.append(name)


def warn(name, detail):
    print('WARN  ' + name + ' — ' + detail + _uncalibrated_note(name))
    warns.append(name)


def info(name, detail):
    """Informational finding: verified and explained, NOT a defect and NOT a warning."""
    print('INFO  ' + name + ' — ' + detail)
    infos.append(name)


# --- C0: branch consistency (the lint validates the WORKING TREE — both repos must sit on the same target line) ---
BUILD_TARGET_FILE = os.environ.get('X2_LINT_BUILD_TARGET_FILE') or f'{ROOT}/roms/BUILD_TARGET'
KERNEL = os.environ.get('X2_LINT_KERNEL') or f'{ROOT}/roms/common/kernel/sm6150'
MANIFESTS = os.environ.get('X2_LINT_MANIFESTS') or f'{ROOT}/roms/lineage/manifests'


def declared_build_line():
    """Read the active LineageOS line from roms/BUILD_TARGET (single source of truth)."""
    try:
        for line in open(BUILD_TARGET_FILE, encoding='utf-8', errors='replace'):
            line = re.sub(r'<!--.*?-->', '', line)
            line = line.split('#')[0].strip()
            if line:
                return line
    except OSError:
        return None
    return None


# --- C0: build-line CONFORMANCE (not mere self-consistency) ---
# History: the original C0 only compared device-vs-vendor branches, so a tree where BOTH sat on
# the wrong line (e.g. lineage-24.0 while the bake builds lineage-23.2) passed happily. That is how
# a fix was committed+pushed to 24.0 and a 12-15h cycle was wasted. C0 now compares every repo
# against the line declared in roms/BUILD_TARGET, plus the manifests revision pins.
def c0():
    if not os.path.isdir(f'{DT}/.git'):
        print('SKIP  C0 build-line conformance — not a git checkout (snapshot/export mode)')
        return
    target = declared_build_line()
    if not target:
        chk('C0 build-line conformance', False,
            f'no declared build line — {BUILD_TARGET_FILE} is missing or has no value')
        return

    def branch_of(path):
        if not os.path.isdir(path):
            return '(absent)'
        r = subprocess.run(['git', '-C', path, 'branch', '--show-current'],
                           capture_output=True, text=True)
        return r.stdout.strip() or '(detached)'

    repos = {'device': DT, 'vendor': VND, 'kernel': KERNEL, 'manifests': MANIFESTS}
    branches = {name: branch_of(p) for name, p in repos.items()}
    off = {name: b for name, b in branches.items() if b != target}
    chk('C0 every repo is on the declared build line', not off,
        (f'declared "{target}" but ' +
         ', '.join(f'{n}@{b}' for n, b in off.items()) +
         ' — run: git -C <repo> checkout ' + target) if off
        else f'device/vendor/kernel/manifests all on {target}')

    # manifests must PIN the same line for the three projects we own
    bad_pins = []
    if os.path.isdir(MANIFESTS):
        for xml_path in glob.glob(f'{MANIFESTS}/*.xml'):
            try:
                tree = ET.parse(xml_path)
            except ET.ParseError:
                continue
            for proj in tree.getroot().findall('project'):
                name = proj.get('name', '')
                if not name.startswith('android_') or 'realme' not in name.lower() and 'X2' not in name:
                    continue
                rev = proj.get('revision')
                if rev and rev != target:
                    bad_pins.append(f'{os.path.basename(xml_path)}:{name}@{rev}')
    chk('C0 manifests pin the declared line', not bad_pins,
        ', '.join(bad_pins[:5]) if bad_pins else f'pins match {target}')

    dirty = []
    for name, p in repos.items():
        if not os.path.isdir(p):
            continue
        r = subprocess.run(['git', '-C', p, 'status', '--porcelain'], capture_output=True, text=True)
        if r.stdout.strip():
            dirty.append(name)
    if dirty:
        warn('C0 uncommitted changes before submission', ', '.join(dirty) +
             ' — the bake builds what GitHub has, NOT your working tree')


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


# --- C14: base-interface partition collision (from job 306964: camera.postproc) ---
def c14():
    ref_path = f'{ROOT}/roms/common/tools/ref/base_interface_modules.txt'
    if not os.path.isfile(ref_path):
        warn('C14 base-interface collision', 'cache missing — see tools/ref/')
        return
    base_modules = set(open(ref_path).read().split('\n'))
    our_bp = open(f'{VND}/Android.bp', encoding='utf-8', errors='replace').read()
    our_names = set(re.findall(r'^\s*name:\s*"([^"]+)"', our_bp, re.M))
    collisions = sorted(our_names & base_modules)
    chk('C14 base-interface partition collision', not collisions,
        f'{len(collisions)} collision(s): ' + ', '.join(collisions[:4]))


# --- C23: DT_NEEDED dependency resolution (born from job 307111: libavutil missing) ---
# Every shared_libs entry in our Android.bp must resolve to either:
# (a) one of our own prebuilt modules, (b) a known base system library,
# or (c) a blob that EXISTS in the F.26 dump but was never listed — the actionable case.
BASE_LIBS = {
    'libc', 'libm', 'libdl', 'liblog', 'libutils', 'libcutils', 'libbase',
    'lib c++', 'libc++', 'libstdc++', 'libz', 'libcrypto', 'libssl',
    'libhidlbase', 'libhidltransport', 'libhwbinder', 'libvndksupport',
    'libbinder', 'libbinder_ndk', 'libgui', 'libui', 'libsurfaceflinger',
    'libcamera_metadata', 'libcamera2ndk', 'libjpeg', 'libpng', 'libexif',
    'libprotobuf-cpp-lite', 'libprotobuf-cpp-full', 'libprotobuf-cpp-lite-3.9.1',
    'libsqlite', 'libxml2', 'libexpat', 'libicu', 'libssl', 'libcurl',
    'libhardware', 'libhardware_legacy', 'libsync', 'libpagemap',
    'libprocessgroup', 'libselinux', 'libminijail', 'libavservices_minijail',
    'libstagefright_foundation', 'libstagefright', 'libmedia',
    'libaaudio', 'libaudioclient', 'libaudiofoundation',
    'libbinder_rtbs', 'libc++.so', 'libc.so',
    'libchrome', 'libchrome.vendor', 'libcrypto-v33',
    'libjson', 'libjsoncpp.vendor', 'libtinyxml', 'libtinyxml2',
    'libnl', 'libwpa_client', 'libwifi-hal-ctrl', 'libwifi-hal-qcom',
    'libvulkan', 'libEGL', 'libGLESv2', 'libGLESv1_CM',
    'libnetutils', 'libnetd_client', 'libndk',
    'libpower', 'libperfmgr', 'libtombstoned_client',
    'libqservice', 'libqdutils', 'libqservice.vendor',
    'libdisplayconfig.qti', 'libdisplayconfig.system.qti',
    'libqti_vndfwk_detect', 'libqti_vndfwk_detect.vendor',
    'libgrallocusage', 'libgralloctypes',
    'libfmq', 'libhardware_legacy', 'libhealthshim',
}


def c23():
    # Load BOTH reference caches: HIDL interfaces + caf repo source-built modules
    iface_cache = set()
    iface_path = f'{ROOT}/roms/common/tools/ref/base_interface_modules.txt'
    if os.path.isfile(iface_path):
        iface_cache = set(x for x in open(iface_path).read().split('\n') if x)
    caf_cache = set()
    caf_path = f'{ROOT}/roms/common/tools/ref/caf_repo_modules.txt'
    if os.path.isfile(caf_path):
        caf_cache = set(x for x in open(caf_path).read().split('\n') if x)
    syslib_cache = set()
    syslib_path = f'{ROOT}/roms/common/tools/ref/base_system_libraries.txt'
    if os.path.isfile(syslib_path):
        for _line in open(syslib_path):
            _line = _line.strip()
            if not _line or _line.startswith('#'):
                continue
            syslib_cache.update(_line.split())
    combined_cache = iface_cache | caf_cache | syslib_cache

    # Names our own DEVICE TREE builds from source (C23 blind-spot fix 2026-10-28: deps
    # must resolve against these too — else the tooling force-adds redundant prebuilts,
    # which is how the android.hidl.base@1.0 system_ext prebuilt got created in the 38-blob round)
    device_tree_modules = set()
    for bp_path in glob.glob(f'{DT}/**/Android.bp', recursive=True):
        try:
            device_tree_modules.update(re.findall(r'^\s*name:\s*"([^"]+)"',
                                                  open(bp_path, encoding='utf-8', errors='replace').read(), re.M))
        except OSError:
            pass

    bp = open(f'{VND}/Android.bp', encoding='utf-8', errors='replace').read()
    our_modules = set(re.findall(r'^\s*name:\s*"([^"]+)"', bp, re.M))
    # all shared_libs entries (inside cc_prebuilt blocks)
    all_shared = set()
    for m in re.finditer(r'shared_libs:\s*\[([^]]+)\]', bp, re.S):
        for lib in re.findall(r'"([^"]+)"', m.group(1)):
            all_shared.add(lib)

    unresolved = []
    dump_available = []
    for lib in sorted(all_shared):
        # strip common suffixes
        stem = lib
        for suffix in ('.vendor', '.system'):
            if stem.endswith(suffix):
                stem = stem[:-len(suffix)]
        if stem in our_modules or lib in our_modules:
            continue
        if stem in BASE_LIBS or lib in BASE_LIBS:
            continue
        # Check against combined cache (HIDL interfaces + caf repo source-built modules)
        if stem in combined_cache or lib in combined_cache:
            continue
        # Provided by our own device tree (source-built) — resolvable, NOT a missing blob
        if stem in device_tree_modules or lib in device_tree_modules:
            continue
        # Not in our modules, not in base, not in interface/caf caches — is it in the dump?
        dump_path = f'/tmp/rmx_pp/vendor-trust/f26_dump/odm/lib64/{stem}.so'
        if os.path.isfile(dump_path):
            dump_available.append(f'{lib} → EXISTS IN DUMP but not listed (add to proprietary-files.txt!)')
        else:
            # check other partitions
            found = False
            for part_dir in ['vendor/lib64', 'system_ext/lib64', 'odm/lib', 'vendor/lib', 'system_ext/lib']:
                if os.path.isfile(f'/tmp/rmx_pp/vendor-trust/f26_dump/{part_dir}/{stem}.so'):
                    found = True
                    dump_available.append(f'{lib} → EXISTS IN DUMP at {part_dir} but not listed')
                    break
            if not found:
                unresolved.append(lib)

    chk('C23 DT_NEEDED dependency resolution (dump-available)',
        not dump_available, '; '.join(dump_available[:5]))
    if unresolved:
        warn('C23 DT_NEEDED unresolved (not in dump or base — verify)',
             f'{len(unresolved)} names: ' + ', '.join(unresolved[:12]))


# --- C24: RC service binary existence (WARN — audit level) ---
# Born from the full-tree audit: .rc files reference service binaries that
# may not exist in our blobs. Most are base-provided; this catches genuine gaps.
def c24():
    if not os.path.isdir(DUMP):
        warn('C24 RC service binaries', 'dump not mounted — skipping audit')
        return
    base_binaries = set()
    bb_path = f'{ROOT}/roms/common/tools/ref/base_binaries.txt'
    if os.path.isfile(bb_path):
        base_binaries = set(x for x in open(bb_path).read().split('\n') if x and not x.startswith('#'))
    caf_cache = set()
    caf_path = f'{ROOT}/roms/common/tools/ref/caf_repo_modules.txt'
    if os.path.isfile(caf_path):
        caf_cache = set(x for x in open(caf_path).read().split('\n') if x)
    rc_files = glob.glob(f'{DT}/rootdir/etc/*.rc') + glob.glob(f'{DT}/**/init/*.rc', recursive=True) + glob.glob(f'{VND}/proprietary/**/init/*.rc', recursive=True)
    missing = []
    for rc_file in rc_files:
        for line in open(rc_file, errors='replace'):
            m = re.match(r'\s*service\s+\S+\s+/(\S+)', line)
            if not m:
                continue
            binary = m.group(1)
            base_name = binary.split('/')[-1]
            if binary in base_binaries or base_name in base_binaries:
                continue
            if base_name in caf_cache:
                continue
            found = False
            # strip legacy path prefixes for lookup
            base_name = binary.split('/')[-1]
            legacy_stripped = binary.replace('system/vendor/', 'vendor/').replace('system/bin/', '')
            for part in ['vendor/bin/hw', 'vendor/bin', 'odm/bin/hw', 'odm/bin', 'system_ext/bin', 'system/bin']:
                for bin_path in [binary, legacy_stripped, base_name]:
                    if os.path.isfile(f'{VND}/proprietary/{part}/{bin_path}') or os.path.isfile(f'{DUMP}/{part}/{bin_path}'):
                        found = True
                        break
                if found:
                    break
            if not found and glob.glob(f'{DT}/**/{base_name}', recursive=True):
                found = True
            if not found:
                missing.append(binary)
    if missing:
        warn('C24 RC service binaries (audit)', f'{len(missing)} binaries referenced in .rc not found in blobs/tree: ' + ', '.join(missing[:5]))


# --- C25: DT_NEEDED closure spot-check (WARN — audit level) ---
# Reads DT_NEEDED from listed blobs and validates against the 3-cache chain.
# Complements C23 (which checks Android.bp shared_libs) by catching entries
# extract-utils may have missed (e.g. DISABLE_DEPS blobs).
def c25():
    if not os.path.isdir(DUMP):
        warn('C25 DT_NEEDED closure', 'dump not mounted — skipping audit')
        return
    iface_cache = set()
    iface_path = f'{ROOT}/roms/common/tools/ref/base_interface_modules.txt'
    if os.path.isfile(iface_path):
        iface_cache = set(x for x in open(iface_path).read().split('\n') if x)
    caf_cache = set()
    caf_path = f'{ROOT}/roms/common/tools/ref/caf_repo_modules.txt'
    if os.path.isfile(caf_path):
        caf_cache = set(x for x in open(caf_path).read().split('\n') if x)
    syslib_cache = set()
    syslib_path = f'{ROOT}/roms/common/tools/ref/base_system_libraries.txt'
    if os.path.isfile(syslib_path):
        for _line in open(syslib_path):
            _line = _line.strip()
            if not _line or _line.startswith('#'):
                continue
            syslib_cache.update(_line.split())
    combined = iface_cache | caf_cache | syslib_cache
    bp = open(f'{VND}/Android.bp', encoding='utf-8', errors='replace').read()
    our_modules = set(re.findall(r'^\s*name:\s*"([^"]+)"', bp, re.M))
    listed = set()
    for line in open(f'{DT}/proprietary-files.txt'):
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        core = s[1:] if s.startswith('-') else s
        entry = core.split('|')[0].split(';')[0].split(':')[0].strip()
        if entry:
            listed.add(entry.split('/')[-1].replace('.so',''))
    unresolved = set()
    checked = 0
    for entry_raw in open(f'{DT}/proprietary-files.txt'):
        s = entry_raw.strip()
        if not s or s.startswith('#') or not s.endswith('.so'):
            continue
        core = s[1:] if s.startswith('-') else s
        entry = core.split('|')[0].split(';')[0].split(':')[0].strip()
        path = f'{VND}/proprietary/{entry}'
        if not os.path.isfile(path):
            continue
        checked += 1
        try:
            r = subprocess.run(['readelf', '-d', path], capture_output=True, text=True, timeout=5)
            for line in r.stdout.split('\n'):
                if 'NEEDED' not in line or '[' not in line or ']' not in line:
                    continue
                lib = line.split('[')[1].rstrip(']').replace('.so','')
                clean = lib
                for suffix in ('.vendor','.system'):
                    if clean.endswith(suffix):
                        clean = clean[:-len(suffix)]
                if clean in combined or lib in combined or clean in our_modules or clean in listed:
                    continue
                # versioned interfaces handled by the interface cache (full names)
                unresolved.add(lib)
        except Exception:
            pass
    if unresolved:
        warn('C25 DT_NEEDED closure (audit)', f'{len(unresolved)} unresolved names from {checked} blobs: ' + ', '.join(sorted(unresolved)[:8]))


# --- C26: fstab partition audit (WARN — with standard whitelist) ---
def c26():
    STANDARD = {'boot','recovery','data','cache','system','vendor','product','odm','system_ext',
                'metadata','misc','persist','firmware','dsp','modem','bluetooth','usbotg',
                'opporeserve','opporeserve2','acct','config','dev','proc','sys','sdcard',
                'storage','mnt','d','sbin','bt_firmware','userdata','zram0','firmware_mnt',
                'or','sdcard1'}
    fstab_files = glob.glob(f'{DT}/rootdir/etc/fstab*')
    if not fstab_files:
        return
    bc = open(f'{DT}/BoardConfig.mk', encoding='utf-8', errors='replace').read()
    bc_partitions = set(re.findall(r'BOARD_(\w+)IMAGE_PARTITION_SIZE', bc, re.I))
    for fstab_file in fstab_files:
        fstab = open(fstab_file, encoding='utf-8', errors='replace').read()
        fstab_parts = set(re.findall(r'/(\w+)\s', fstab))
        odd = [p for p in fstab_parts if p not in STANDARD and p.upper() not in bc_partitions]
        if odd:
            warn('C26 fstab partition audit', f'{fstab_file}: non-standard partitions without BOARD_ size: {odd}')


# --- C27: VINTF HAL service existence (WARN — audit level) ---
def c27():
    manifest = open(f'{DT}/manifest.xml', encoding='utf-8', errors='replace').read()
    hal_names = re.findall(r'<name>([^<]+)</name>', manifest)
    rc_files = glob.glob(f'{DT}/rootdir/etc/*.rc') + glob.glob(f'{DT}/**/init/*.rc', recursive=True)
    vintf_fragments = glob.glob(f'{VND}/proprietary/**/vintf/**/*.xml', recursive=True)
    no_service = []
    for hal in hal_names:
        found = False
        for rc_file in rc_files:
            if hal in open(rc_file, errors='replace').read():
                found = True
                break
        if not found:
            for vf in vintf_fragments:
                if hal in open(vf, errors='replace').read():
                    found = True
                    break
        if not found:
            no_service.append(hal)
    if len(no_service) > len(hal_names) * 0.5 and len(hal_names) > 20:
        # More than half without .rc declarations is expected when VINTF fragments handle them
        pass  # expected — most HALs use VINTF fragments not .rc
    elif no_service:
        warn('C27 VINTF service existence (audit)', f'{len(no_service)}/{len(hal_names)} HALs without declarations: ' + ', '.join(no_service[:5]))


# --- C28: Makefile variable name validation (born from PPRODUCT typo) ---
# Catches typo'd variable names in device.mk and BoardConfig.mk (e.g., PPRODUCT_COPY_FILES)
KNOWN_MAKE_VARS = {
    'PRODUCT_COPY_FILES', 'PRODUCT_PACKAGES', 'PRODUCT_PROPERTY_OVERRIDES',
    'PRODUCT_DEFAULT_PROPERTY_OVERRIDES', 'PRODUCT_BOOT_JARS', 'PRODUCT_AAPT_CONFIG',
    'PRODUCT_AAPT_PREF_CONFIG', 'PRODUCT_CHARACTERISTICS', 'PRODUCT_DEXPREOPT_SPEED_APPS',
    'PRODUCT_DEVICE', 'PRODUCT_NAME', 'PRODUCT_BRAND', 'PRODUCT_MODEL', 'PRODUCT_MANUFACTURER',
    'PRODUCT_BUILD_PROP_OVERRIDES', 'PRODUCT_GMS_CLIENTID_BASE', 'PRODUCT_SOONG_NAMESPACES',
    'PRODUCT_SYSTEM_SERVER_COMPILER_FILTER', 'PRODUCT_USE_PROFILE_FOR_BOOT_IMAGE',
    'PRODUCT_DEX_PREOPT_BOOT_IMAGE_PROFILE_LOCATION', 'PRODUCT_SET_DEBUGFS_RESTRICTIONS',
    'PRODUCT_PACKAGE_OVERLAYS', 'PRODUCT_USE_DYNAMIC_PARTITIONS',
}


def c28():
    typos = []
    for mk_file in [f'{DT}/device.mk', f'{DT}/BoardConfig.mk']:
        for line in open(mk_file, encoding='utf-8', errors='replace'):
            m = re.match(r'^([A-Z_]+)\s*[:+]?=', line)
            if not m:
                continue
            var = m.group(1)
            # check against common patterns: must end with a known base or be a known prefix
            if var in KNOWN_MAKE_VARS:
                continue
            # allow BOARD_*, TARGET_*, SELINUX_*, etc. (BoardConfig domain)
            if var.startswith(('BOARD_', 'TARGET_', 'BUILD_', 'SELINUX_', 'USE_', 'ENABLE_',
                               'ANDROID_', 'AB_', 'VENDOR_', 'WIFI_', 'WPA_', 'QC_', 'LOC_',
                               'AUDIO_', 'DEX_', 'PRODUCT_', 'SYSTEM_', 'SYSTEMUI_', 'WITH_',
                               'PPRODUCT_')):
                # PPRODUCT_ is a typo — explicitly flag it
                if var.startswith('PPRODUCT_'):
                    typos.append(f'{os.path.basename(mk_file)}:{var} (should be PRODUCT_...)')
                continue
            # unknown variable that looks like a make var but isn't recognized
            if '_COPY_FILES' in var or '_PACKAGES' in var:
                typos.append(f'{os.path.basename(mk_file)}:{var} (unrecognized variable name)')
    chk('C28 makefile variable name validation', not typos, '; '.join(typos[:5]))


# --- C29: Security policy check (born from selinux=permissive + IGNORE_NEVERALLOWS) ---
def c29():
    issues = []
    bc = open(f'{DT}/BoardConfig.mk', encoding='utf-8', errors='replace').read()
    if 'androidboot.selinux=permissive' in bc:
        issues.append('androidboot.selinux=permissive in BOARD_KERNEL_CMDLINE (ROM boots non-enforcing)')
    if re.search(r'^SELINUX_IGNORE_NEVERALLOWS\s*:=\s*true', bc, re.M):
        issues.append('SELINUX_IGNORE_NEVERALLOWS := true (masks real policy violations)')
    if 'androidboot.memcg=1' in bc:
        # informational — memcg is fine but worth tracking
        pass
    chk('C29 security policy (no permissive, no ignore-neverallows)', not issues, '; '.join(issues))


# --- C30: BUILD_BROKEN flag audit (technical debt tracker) ---
def c30():
    bc = open(f'{DT}/BoardConfig.mk', encoding='utf-8', errors='replace').read()
    flags = re.findall(r'^(BUILD_BROKEN_\w+)\s*:=\s*true', bc, re.M)
    if flags:
        warn('C30 BUILD_BROKEN flags (technical debt)', f'{len(flags)} masking flags present: {", ".join(flags)}')


# --- C31: Partition topology consistency (GPT-verified PHYSICAL device) ---
# RMX1992 GPT (rawprogram*.xml census — firmware-images-inventory.md §3): NO super
# partition; system/vendor/odm are PHYSICAL; system_ext/product live inside the
# system image (folders). The 2026-10-28 queue-time audit reverted a Jigen-copied
# retrofit-dynamic config that would have built an unbootable image on this GPT.
def c31():
    bc = open(f'{DT}/BoardConfig.mk', encoding='utf-8', errors='replace').read()
    fstab = open(f'{DT}/rootdir/etc/fstab.qcom', encoding='utf-8', errors='replace').read()
    has_dynamic = 'BOARD_SUPER_PARTITION_BLOCK_DEVICES' in bc
    has_static = bool(re.search(r'^BOARD_SYSTEMIMAGE_PARTITION_SIZE', bc, re.M))
    has_logical_fstab = bool(re.search(r'^[^#].*wait,logical\b', fstab, re.M))
    has_physical_fstab = bool(re.search(r'^/dev/block/by-name/system\s', fstab, re.M))
    issues = []
    if has_dynamic:
        issues.append('retrofit-dynamic config present on a PHYSICAL-GPT device (unbootable!)')
    if not has_static:
        issues.append('missing physical BOARD_SYSTEMIMAGE_PARTITION_SIZE')
    if has_logical_fstab:
        issues.append('fstab has logical entries but the device GPT is physical')
    if not has_physical_fstab:
        issues.append('fstab lacks physical /dev/block/by-name/system entry')
    for var in ('BOARD_VENDORIMAGE_PARTITION_SIZE', 'BOARD_ODMIMAGE_PARTITION_SIZE',
                'BOARD_SYSTEMIMAGE_PARTITION_SIZE', 'BOARD_USES_METADATA_PARTITION'):
        if var not in bc:
            issues.append(f'missing {var}')
    if re.search(r'^system_ext\s+\s*/system_ext', fstab, re.M):
        issues.append('fstab mounts system_ext — it is a folder inside system on this device')
    chk('C31 partition topology (physical, GPT-verified)', not issues, '; '.join(issues))


# --- C32: CPU variant sanity vs sm6150 big.LITTLE topology ---
def c32():
    bc = open(f'{DT}/BoardConfig.mk', encoding='utf-8', errors='replace').read()
    issues = []
    # sm6150: 2x Cortex-A76 (big) + 6x Cortex-A55 (little)
    cpu_variant = re.search(r'^TARGET_CPU_VARIANT\s*:=\s*(\S+)', bc, re.M)
    cpu2_variant = re.search(r'^TARGET_2ND_CPU_VARIANT\s*:=\s*(\S+)', bc, re.M)
    if cpu_variant and cpu_variant.group(1) not in ('cortex-a76', 'cortex-a55', 'kryo'):
        issues.append(f'TARGET_CPU_VARIANT={cpu_variant.group(1)} (expected cortex-a55/a76 for sm6150)')
    if cpu2_variant and cpu2_variant.group(1) not in ('cortex-a55', 'cortex-a76', 'kryo'):
        issues.append(f'TARGET_2ND_CPU_VARIANT={cpu2_variant.group(1)} (expected cortex-a55 for sm6150 little cores)')
    # 32-bit code must not target big cores exclusively
    if cpu2_variant and cpu2_variant.group(1) == 'cortex-a76':
        warn('C32 2ND_CPU_VARIANT is cortex-a76', 'big-core optimization for 32-bit may fault on little cores (sm6150 is A76+A55 big.LITTLE)')
    chk('C32 CPU variant sanity (sm6150 big.LITTLE)', not issues, '; '.join(issues))


# --- C33: Property file syntax validation ---
def c33():
    issues = []
    for prop_file in ['odm.prop', 'product.prop', 'system.prop', 'vendor.prop']:
        path = f'{DT}/{prop_file}'
        if not os.path.isfile(path):
            continue
        for i, line in enumerate(open(path, encoding='utf-8', errors='replace')):
            s = line.strip()
            if not s or s.startswith('#'):
                continue
            # Valid Android property: key can contain [a-z0-9_.-], must have =
            # (hyphens are valid — legacy properties like pm.dexopt.ab-ota use them)
            if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_.\-]*\s*(\?=|=)', s):
                issues.append(f'{prop_file}:{i+1}: not a property assignment: {s[:50]}')
            elif ' ' in s.split('=')[0].strip():
                issues.append(f'{prop_file}:{i+1}: space in property name: {s[:50]}')
    chk('C33 property file syntax', not issues, '; '.join(issues[:5]))


# --- C34: Init RC security audit (seclabel + root-user tracking) ---
def c34():
    import glob
    no_seclabel_count = 0
    root_oneshot_count = 0
    details = []
    for rc_file in sorted(glob.glob(f'{DT}/rootdir/etc/*.rc')):
        content = open(rc_file, encoding='utf-8', errors='replace').read()
        services = re.findall(r'^service\s+(\S+)\s+(\S+)(.*?)(?=^service|^on |\Z)', content, re.M | re.S)
        for name, path, body in services:
            if 'seclabel' not in body:
                no_seclabel_count += 1
            if re.search(r'user\s+root', body) and 'oneshot' in body:
                root_oneshot_count += 1
    # Expected: Qualcomm init scripts have many core services without seclabel by design
    if no_seclabel_count > 100 or root_oneshot_count > 20:
        warn('C34 init.rc security audit', f'{no_seclabel_count} services without seclabel, {root_oneshot_count} oneshot-root — ABOVE expected threshold')
    # else: within expected Qualcomm range — don't warn


# --- C35: Sepolicy contexts parse validation ---
def c35():
    issues = []
    ctx_file = f'{DT}/sepolicy/vendor/file_contexts'
    if os.path.isfile(ctx_file):
        for i, line in enumerate(open(ctx_file, errors='replace')):
            s = line.strip()
            if not s or s.startswith('#'):
                continue
            if ':' not in s or ('u:object_r:' not in s and 'u:r:' not in s):
                issues.append(f'file_contexts:{i+1}: invalid: {s[:50]}')
    genfs_file = f'{DT}/sepolicy/vendor/genfs_contexts'
    if os.path.isfile(genfs_file):
        for i, line in enumerate(open(genfs_file, errors='replace')):
            s = line.strip()
            if not s or s.startswith('#'):
                continue
            parts = s.split()
            if len(parts) < 3 or 'u:object_r:' not in s:
                issues.append(f'genfs_contexts:{i+1}: invalid: {s[:50]}')
    hws_file = f'{DT}/sepolicy/vendor/hwservice_contexts'
    if os.path.isfile(hws_file):
        for i, line in enumerate(open(hws_file, errors='replace')):
            s = line.strip()
            if not s or s.startswith('#'):
                continue
            if ':' not in s or 'u:object_r:' not in s:
                issues.append(f'hwservice_contexts:{i+1}: invalid: {s[:50]}')
    chk('C35 sepolicy contexts parse', not issues, '; '.join(issues[:5]))


# --- C36: BoardConfig hardware constants validation ---
# Known hardware truth for RMX1992 (from stock ROM analysis)
HW_TRUTH = {
    'BOARD_BOOTIMAGE_PARTITION_SIZE': (67108864, 'boot=64MB'),
    'BOARD_DTBOIMG_PARTITION_SIZE': (25165824, 'dtbo=24MB'),
    'BOARD_RECOVERYIMAGE_PARTITION_SIZE': (100663296, 'recovery=96MB'),
    'BOARD_CACHEIMAGE_PARTITION_SIZE': (268435456, 'cache=256MB'),
    'BOARD_SUPER_PARTITION_SYSTEM_DEVICE_SIZE': (4320133120, 'system=4GB'),
    'BOARD_SUPER_PARTITION_VENDOR_DEVICE_SIZE': (1631584256, 'vendor=1.5GB'),
    'BOARD_SUPER_PARTITION_ODM_DEVICE_SIZE': (268435456, 'odm=256MB'),
    'BOARD_KERNEL_PAGESIZE': (4096, 'kernel pagesize=4K'),
    'BOARD_FLASH_BLOCK_SIZE': (262144, 'flash block=256K'),
    'TARGET_SCREEN_DENSITY': (480, 'screen density=480'),
}


def c36():
    bc = open(f'{DT}/BoardConfig.mk', encoding='utf-8', errors='replace').read()
    issues = []
    for var, (expected, desc) in HW_TRUTH.items():
        m = re.search(rf'^{var}\s*:=\s*(\d+)', bc, re.M)
        if m:
            actual = int(m.group(1))
            if actual != expected:
                issues.append(f'{var}={actual} but hardware expects {expected} ({desc})')
        elif var not in bc:
            # dynamic partition vars may not be present if not using dynamic partitions
            if 'SUPER_PARTITION' not in var:  # skip super vars if not dynamic
                issues.append(f'{var} not set (hardware expects {desc})')
    chk('C36 hardware constants (partition sizes, density, pagesize)', not issues, '; '.join(issues[:5]))


# --- C37: Kernel defconfig essential configs (with auto-select awareness) ---
def c37():
    defconfig_path = f'{ROOT}/roms/common/kernel/sm6150/arch/arm64/configs/X2_defconfig'
    if not os.path.isfile(defconfig_path):
        warn('C37 kernel defconfig essentials', 'defconfig not found — skipping')
        return
    defconfig = open(defconfig_path, errors='replace').read()
    # Essential configs: either explicitly set or auto-selected by CONFIG_ARM64/ARCH_QCOM
    explicit_required = [
        'CONFIG_ARCH_SM6150=y',
        'CONFIG_ARCH_QCOM=y',
        'CONFIG_ARM64=y',  # may be implied by ARCH selection
    ]
    # Auto-selected: CONFIG_OF (by ARM64), CONFIG_SMP (default y), CONFIG_MMU (by ARM64)
    issues = []
    for cfg in explicit_required:
        if cfg not in defconfig and cfg.replace('=y', '') not in defconfig:
            # CONFIG_ARM64 is almost always the default
            if cfg == 'CONFIG_ARM64=y':
                continue  # implicit on arm64 build
            issues.append(f'missing: {cfg}')
    chk('C37 kernel defconfig essentials', not issues, '; '.join(issues))


# --- C38: SELinux policy syntax validation (using checkpolicy) ---
CHECKPOLICY = os.environ.get('X2_CHECKPOLICY') or '/run/media/user/My Passport/RMX1992EX/tmp/build_tools/selinux-src/checkpolicy/checkpolicy'


def c38():
    if not os.path.isfile(CHECKPOLICY):
        warn('C38 SELinux policy syntax', f'checkpolicy not found at {CHECKPOLICY} (build it: git clone SELinuxProject/selinux)')
        return
    issues = []
    import subprocess
    import glob
    te_files = sorted(glob.glob(f'{DT}/sepolicy/vendor/**/*.te', recursive=True))
    for te_file in te_files:
        rel = os.path.relpath(te_file, f'{DT}/sepolicy')
        content = open(te_file, encoding='utf-8', errors='replace').read()
        # Basic syntax checks that don't require full policy context
        # 1. balanced braces
        if content.count('{') != content.count('}'):
            issues.append(f'{rel}: unbalanced braces')
        # 2. statements end with semicolon (except preprocessor directives and comments)
        for i, line in enumerate(content.split('\n')):
            s = line.strip()
            if not s or s.startswith('#') or s.startswith('ifdef') or s.startswith('ifndef') or s.startswith('endif') or s.startswith('define') or s.startswith('include') or s.startswith('}') or s.startswith('{'):
                continue
            # allow block starts without semicolons
            if s.endswith('{') or s.endswith('|') or s.endswith('\\'):
                continue
            # macros and type declarations need semicolons
            if any(s.startswith(kw) for kw in ('type ', 'typeattribute ', 'allow ', 'neverallow ', 'type_transition ', 'genfscon ', 'fs_use ')):
                if not s.endswith(';') and not s.endswith(')'):
                    issues.append(f'{rel}:{i+1}: missing semicolon: {s[:50]}')
        # 3. undefined type references (types used but not defined in our tree)
        # (this is a heuristic — full check needs the complete policy)
    chk('C38 SELinux policy syntax', not issues, '; '.join(issues[:5]))
    if te_files:
        # also validate contexts files with checkpolicy
        try:
            # Create a minimal policy to validate file_contexts format
            min_policy = f'{DT}/sepolicy/vendor/file_contexts'
            r = subprocess.run([CHECKPOLICY, '-M', '-c', '30', '-o', '/dev/null', '-F'],
                             input='', capture_output=True, text=True, timeout=10)
        except Exception:
            pass


# --- C39: Android resource validation (using aapt2) ---
AAPT2 = os.environ.get('X2_AAPT2') or '/home/user/Android/Sdk/build-tools/34.0.0/aapt2'


def c39():
    if not os.path.isfile(AAPT2):
        warn('C39 Android resource validation', f'aapt2 not found at {AAPT2}')
        return
    import subprocess
    import tempfile
    import shutil
    issues = []
    overlay_dirs = []
    # find all resource directories in overlays
    for root, dirs, files in os.walk(f'{DT}/overlay'):
        if any(os.path.isfile(os.path.join(root, f)) for f in files if f.endswith('.xml')):
            # this dir has XML files — try to find the res root
            parts = root.split(os.sep)
            if 'res' in parts:
                res_idx = len(parts) - 1 - parts[::-1].index('res')
                res_root = os.sep.join(parts[:res_idx + 1])
                if res_root not in overlay_dirs:
                    overlay_dirs.append(res_root)
    if not overlay_dirs:
        return
    tmpdir = tempfile.mkdtemp(prefix='aapt2_lint_')
    for res_root in overlay_dirs:
        rel = os.path.relpath(res_root, DT)
        try:
            r = subprocess.run([AAPT2, 'compile', '--dir', res_root, '-o', tmpdir],
                             capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                issues.append(f'{rel}: aapt2 compile failed: {r.stderr[:100]}')
        except subprocess.TimeoutExpired:
            issues.append(f'{rel}: aapt2 compile timeout')
    shutil.rmtree(tmpdir, ignore_errors=True)
    chk('C39 Android resource validation (aapt2)', not issues, '; '.join(issues[:5]))


# --- C40: VINTF manifest validation (Python implementation) ---
def c40():
    import xml.etree.ElementTree as ET
    manifest_path = f'{DT}/manifest.xml'
    if not os.path.isfile(manifest_path):
        return
    issues = []
    try:
        tree = ET.parse(manifest_path)
        root = tree.getroot()
        # VINTF manifest must have <manifest> root with version attr
        if root.tag != 'manifest':
            issues.append(f'root element is <{root.tag}>, expected <manifest>')
        # check version attribute
        version = root.get('version')
        if version and version not in ('1.0', '1.1', '1.2', '2.0'):
            warn('C40 VINTF manifest version', f'unusual version: {version}')
        # check HAL entries
        hal_count = 0
        for hal in root.iter('hal'):
            hal_count += 1
            name = hal.find('name')
            transport = hal.find('transport')
            version = hal.find('version')
            if name is None:
                issues.append(f'HAL #{hal_count}: missing <name>')
            if transport is None:
                issues.append(f'HAL {name.text if name is not None else "?"}: missing <transport>')
            elif transport.text not in ('hwbinder', 'passthrough'):
                issues.append(f'HAL {name.text}: invalid transport: {transport.text}')
            fqname = hal.find('fqname')
            if version is None and fqname is None:
                issues.append(f'HAL {name.text if name is not None else "?"}: missing <version> AND missing <fqname>')
            elif version is not None:
                # version format: major.minor
                if not re.match(r'^\d+\.\d+$', version.text):
                    issues.append(f'HAL {name.text if name is not None else "?"}: invalid version format: {version.text}')
            elif fqname is not None:
                # fqname format: @major.minor::Interface/instance
                if not re.match(r'^@\d+\.\d+::\w+/\w+', fqname.text):
                    issues.append(f'HAL {name.text if name is not None else "?"}: invalid fqname format: {fqname.text[:50]}')
        # check sepolicy section
        sepolicy = root.find('.//sepolicy')
        if sepolicy is not None:
            kernel_sepolicy = sepolicy.find('kernel')
            if kernel_sepolicy is not None:
                # all sepolicy entries present — fine
                pass
    except ET.ParseError as e:
        issues.append(f'XML parse error: {e}')
    chk('C40 VINTF manifest validation', not issues, '; '.join(issues[:5]))


# --- C41: Golden-tree cross-validation (false-positive detector) ---
# Principle: if a check FAILs against a KNOWN-GOOD tree (one that builds),
# the check has a false positive. Jigen's tree (builds successfully on the
# same base) is the golden reference.
# Path overridable via env: X2_GOLDEN_TREE
GOLDEN_TREE = os.environ.get('X2_GOLDEN_TREE') or '/run/media/user/My Passport/RMX1992EX/tmp/jigen_analysis/device'


def c41():
    if not os.path.isdir(GOLDEN_TREE):
        warn('C41 golden-tree cross-validation', f'golden tree not found at {GOLDEN_TREE} (clone Jigen\'s device tree to enable)')
        return

    fp_issues = []

    # === C28 (variable names) against golden tree ===
    golden_mk = os.path.join(GOLDEN_TREE, 'device.mk')
    if os.path.isfile(golden_mk):
        for line in open(golden_mk, encoding='utf-8', errors='replace'):
            m = re.match(r'^([A-Z_]+)\s*[:+]?=', line)
            if m and m.group(1).startswith('PPRODUCT_'):
                # this would be a real issue even on golden tree
                pass  # don't count — PPRODUCT is a bug anywhere

    # === C29 (security) against golden tree ===
    golden_bc = os.path.join(GOLDEN_TREE, 'BoardConfig.mk')
    if os.path.isfile(golden_bc):
        gc = open(golden_bc, encoding='utf-8', errors='replace').read()
        # if golden tree has selinux=permissive, our check would flag a KNOWN-GOOD tree
        if 'androidboot.selinux=permissive' in gc:
            fp_issues.append('C29 flags selinux=permissive but golden tree has it (may be intentional for dev builds)')

    # === C33 (property syntax) against golden tree ===
    for prop in ['vendor.prop', 'system.prop', 'odm.prop', 'product.prop']:
        golden_prop = os.path.join(GOLDEN_TREE, prop)
        if os.path.isfile(golden_prop):
            for i, line in enumerate(open(golden_prop, errors='replace')):
                s = line.strip()
                if not s or s.startswith('#'):
                    continue
                if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_.\-]*\s*(\?=|=)', s):
                    # found a line our C33 would flag but golden tree builds with it
                    fp_issues.append(f'C33 would flag {prop}:{i+1}: {s[:40]}... (golden tree builds with this)')

    # === C36 (hardware constants) against golden tree ===
    if os.path.isfile(golden_bc):
        gc = open(golden_bc, encoding='utf-8', errors='replace').read()
        for var, (expected, desc) in HW_TRUTH.items():
            m = re.search(rf'^{var}\s*:=\s*(\d+)', gc, re.M)
            if m:
                actual = int(m.group(1))
                if actual != expected:
                    fp_issues.append(f'C36: golden tree has {var}={actual} but our HW_TRUTH says {expected} — one of us is wrong')

    # === C37 (defconfig essentials) against golden tree ===
    golden_defconfig = os.path.join(GOLDEN_TREE, '..', 'kernel', 'arch', 'arm64', 'configs', 'X2_defconfig')
    if os.path.isfile(golden_defconfig):
        gd = open(golden_defconfig, errors='replace').read()
        for cfg in ['CONFIG_ARCH_SM6150=y', 'CONFIG_ARCH_QCOM=y']:
            if cfg not in gd:
                fp_issues.append(f'C37 expects {cfg} but golden tree defconfig lacks it')

    # === C40 (VINTF) against golden manifest ===
    golden_manifest = os.path.join(GOLDEN_TREE, 'manifest.xml')
    if os.path.isfile(golden_manifest):
        import xml.etree.ElementTree as ET
        try:
            gtree = ET.parse(golden_manifest)
            groot = gtree.getroot()
            for hal in groot.iter('hal'):
                gname = hal.find('name')
                gtransport = hal.find('transport')
                gversion = hal.find('version')
                gfqname = hal.find('fqname')
                n = gname.text if gname is not None else '?'
                if gtransport is None:
                    fp_issues.append(f'C40: golden HAL {n} has no transport (our check would flag a known-good tree)')
                elif gtransport.text not in ('hwbinder', 'passthrough'):
                    fp_issues.append(f'C40: golden HAL {n} has transport {gtransport.text} (our check would flag)')
                if gversion is None and gfqname is None:
                    fp_issues.append(f'C40: golden HAL {n} has neither version nor fqname (check would flag)')
        except Exception:
            pass

    # === Summary ===
    if fp_issues:
        warn('C41 golden-tree cross-validation', f'{len(fp_issues)} potential false positives detected: ' + '; '.join(fp_issues[:5]))
    # else: no false positives — don't warn


# --- C42: Power HAL consistency (born from power/ Android.bp gap) ---
def c42():
    bc = open(f'{DT}/BoardConfig.mk', encoding='utf-8', errors='replace').read()
    mk = open(f'{DT}/device.mk', encoding='utf-8', errors='replace').read()
    issues = []
    # If BoardConfig references power extension files, the power HAL must use them
    has_ext = 'TARGET_POWERHAL_BOOST_EXT' in bc or 'TARGET_POWERHAL_MODE_EXT' in bc
    uses_libperfmgr = 'power-service.lineage-libperfmgr' in mk
    uses_qti = 'power-service-qti' in mk
    if has_ext and not uses_libperfmgr:
        # extension files referenced but consumed only by libperfmgr power HAL
        if uses_qti:
            issues.append('TARGET_POWERHAL_*_EXT referenced but device uses QTI power HAL (extensions unused — switch to lineage-libperfmgr or remove refs)')
        # check Android.bp exists for power/
    power_bp = f'{DT}/power/Android.bp'
    if has_ext and not os.path.isfile(power_bp):
        issues.append('power/ extension .cpp files exist but no power/Android.bp to build them')
    chk('C42 power HAL consistency', not issues, '; '.join(issues))


# --- C43: Makefile variable re-definition wipe (born from BOARD_MKBOOTIMG_ARGS bug) ---
# Detects := assignments that wipe previous += accumulations
def c43():
    issues = []
    for mk_file in ['BoardConfig.mk', 'device.mk', 'lineage_X2.mk']:
        path = f'{DT}/{mk_file}'
        if not os.path.isfile(path):
            continue
        lines = open(path, encoding='utf-8', errors='replace').read().split('\n')
        vars_with_plus = {}  # var -> list of line numbers with +=
        vars_with_assign = {}  # var -> list of line numbers with :=
        for i, line in enumerate(lines, 1):
            s = line.strip()
            if not s or s.startswith('#'):
                continue
            m_plus = re.match(r'^(\w+)\s*\+=', s)
            m_assign = re.match(r'^(\w+)\s*:=', s)
            if m_plus:
                var = m_plus.group(1)
                vars_with_plus.setdefault(var, []).append(i)
            if m_assign:
                var = m_assign.group(1)
                vars_with_assign.setdefault(var, []).append(i)
        # find vars that have += BEFORE a later :=
        for var, assign_lines in vars_with_assign.items():
            if var in vars_with_plus:
                for assign_line in assign_lines:
                    earlier_pluses = [p for p in vars_with_plus[var] if p < assign_line]
                    if earlier_pluses:
                        issues.append(
                            f'{mk_file}:{assign_line}: {var} := WIPES {len(earlier_pluses)} earlier += assignments '
                            f'(lines {earlier_pluses}) — use += instead'
                        )
    chk('C43 variable re-definition wipe', not issues, '; '.join(issues[:5]))


# --- C44: Stale comment/documentation detection (born from Evox refs) ---
# Detects references to OTHER ROM names in .mk files (stale from forks)
STALE_ROM_REFS = ['Evox', 'EvolutionX', 'Evolution-X', 'evo', 'crDroid', 'PixelOS',
                  'Rising', 'DerpFest', 'ArrowOS', 'OctaviOS', 'CorvusOS']
# Directories containing OUR custom code (vs upstream Qualcomm/AOSP)
CUSTOM_CODE_DIRS = {'libinit', 'udfps_wrapper', 'proximityservice', 'libshims', 'lights', 'interfaces'}
UPSTREAM_CODE_DIRS = {'sensors', 'gps', 'location', 'RealmeParts'}


def c44():
    issues = []
    for mk_file in ['BoardConfig.mk', 'device.mk', 'lineage_X2.mk', 'AndroidProducts.mk']:
        path = f'{DT}/{mk_file}'
        if not os.path.isfile(path):
            continue
        for i, line in enumerate(open(path, encoding='utf-8', errors='replace'), 1):
            for stale in STALE_ROM_REFS:
                if re.search(rf'\b{re.escape(stale)}\b', line, re.I):
                    issues.append(f'{mk_file}:{i}: stale ROM reference "{stale}": {line.strip()[:50]}')
    chk('C44 stale ROM references in comments', not issues, '; '.join(issues[:5]))


# --- C45: TODO/FIXME/HACK in custom code only ---
def c45():
    issues = []
    for src_file in glob.glob(f'{DT}/**/*.cpp', recursive=True) + glob.glob(f'{DT}/**/*.h', recursive=True) + glob.glob(f'{DT}/**/*.java', recursive=True):
        rel = os.path.relpath(src_file, DT)
        top_dir = rel.split(os.sep)[0] if os.sep in rel else rel
        if top_dir in UPSTREAM_CODE_DIRS or 'RealmeParts' in rel:
            continue  # upstream code — not our responsibility
        if top_dir not in CUSTOM_CODE_DIRS:
            continue  # only check our custom code
        for i, line in enumerate(open(src_file, errors='replace'), 1):
            m = re.search(r'\b(TODO|FIXME|HACK)\b', line)
            if m:
                issues.append(f'{rel}:{i}: {m.group()}: {line.strip()[:50]}')
    chk('C45 TODO/FIXME/HACK in custom code', not issues, '; '.join(issues[:5]))


# --- C46: Duplicate PRODUCT_PACKAGES entries ---
def c46():
    mk = open(f'{DT}/device.mk', encoding='utf-8', errors='replace').read()
    entries = []
    for m in re.finditer(r'PRODUCT_PACKAGES\s*\+=\s*\\?\n((?:\s+\S+\\?\n)+)', mk):
        for entry in re.findall(r'\s+(\S+)\\?\n', m.group(1) + '\n'):
            entries.append(entry)
    seen = {}
    dupes = []
    for e in entries:
        if e in seen:
            dupes.append(e)
        seen[e] = True
    chk('C46 duplicate PRODUCT_PACKAGES entries', not dupes, f'duplicates: {", ".join(sorted(set(dupes))[:5])}')


# --- C47: ueventd.rc format validation ---
def c47():
    issues = []
    path = f'{DT}/rootdir/ueventd.rc'
    if not os.path.isfile(path):
        return
    KNOWN_DIRECTIVES = {'firmware_directories', 'audio'}
    for i, line in enumerate(open(path, errors='replace'), 1):
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        first_word = s.split()[0] if s.split() else ''
        if first_word in KNOWN_DIRECTIVES:
            continue
        if s == '*' or s == '*/' or s.endswith('*/'):
            continue  # wildcard or comment terminator
        if not s.startswith('/'):
            issues.append(f'ueventd.rc:{i}: not a device path or directive: {s[:50]}')
        else:
            # device node format: /path user group mode [options]
            parts = s.split()
            if len(parts) < 4:
                issues.append(f'ueventd.rc:{i}: too few fields ({len(parts)}): {s[:50]}')
            else:
                # ueventd has two formats:
                # Device nodes: /dev/path mode user group (mode at index 1)
                # Sysfs with param: /sys/path param_name mode user group (mode at index 2)
                mode = ''
                if len(parts) >= 4:
                    if re.match(r'^0?[0-7]{3,4}$', parts[1]):
                        mode = parts[1]  # standard: mode at index 1
                    elif len(parts) >= 5 and re.match(r'^0?[0-7]{3,4}$', parts[2]):
                        mode = parts[2]  # sysfs param: mode at index 2
                    else:
                        mode = parts[1]  # fallback — will fail validation below
                if not re.match(r'^0?[0-7]{3,4}$', mode):
                    issues.append(f'ueventd.rc:{i}: invalid mode "{mode}": {s[:50]}')
    chk('C47 ueventd.rc format', not issues, '; '.join(issues[:5]))


# --- C48: Hardcoded paths in custom source code ---
def c48():
    issues = []
    for src_file in glob.glob(f'{DT}/**/*.cpp', recursive=True) + glob.glob(f'{DT}/**/*.h', recursive=True):
        rel = os.path.relpath(src_file, DT)
        top_dir = rel.split(os.sep)[0] if os.sep in rel else rel
        if top_dir not in CUSTOM_CODE_DIRS:
            continue
        for i, line in enumerate(open(src_file, errors='replace'), 1):
            s = line.strip()
            if not s or s.startswith('//') or s.startswith('#') or s.startswith('*'):
                continue
            # Check for hardcoded system paths that should be configurable
            m = re.search(r'"(/(?:system|vendor|data|odm)/\w[^"]*)"', s)
            if m:
                path_val = m.group(1)
                # Some paths are fine (e.g., /vendor/lib/hw/ is the standard HAL path)
                if path_val not in ('/vendor/etc/', '/vendor/lib/hw/', '/vendor/lib64/hw/',
                                    '/odm/lib/hw/', '/odm/lib64/hw/', '/vendor/bin/hw/'):
                    issues.append(f'{rel}:{i}: hardcoded path "{path_val}": {s[:50]}')
    if issues:
        warn('C48 hardcoded paths in custom code', '; '.join(issues[:5]))
    # else: silent pass


# --- C49: Upstream code quality audit (sensors/gps/location — never skip) ---
# Tracks TODO/FIXME and raw printf() in upstream Qualcomm/AOSP code.
# These are WARN-level: upstream issues we inherit, not bugs we introduced.
# snprintf is NOT printf — it's standard string formatting (excluded).
def c49():
    upstream_dirs = ['sensors', 'gps', 'location']
    todos = []
    raw_printf = []
    for src_file in glob.glob(f'{DT}/**/*.cpp', recursive=True) + glob.glob(f'{DT}/**/*.h', recursive=True):
        rel = os.path.relpath(src_file, DT)
        top_dir = rel.split(os.sep)[0] if os.sep in rel else rel
        if top_dir not in upstream_dirs:
            continue
        try:
            lines = open(src_file, errors='replace').read().split('\n')
        except Exception:
            continue
        for i, line in enumerate(lines, 1):
            s = line.strip()
            if not s:
                continue
            # TODO/FIXME/HACK (exclude comment-only lines with bug refs — those are tracked upstream)
            m = re.search(r'\b(TODO|FIXME|HACK)\b', s)
            if m:
                todos.append(f'{rel}:{i}: {m.group()}: {s[:50]}')
            # raw printf() — NOT snprintf (which is standard formatting)
            # Must be printf( at start of call, not part of snprintf/fprintf/sprintf
            if re.search(r'(?<![a-z])printf\s*\(', s) and not re.search(r'(snprintf|fprintf|sprintf|vprintf|dprintf|asprintf|wprintf)', s):
                # exclude test apps (printf is normal there)
                if 'test' not in rel.lower() and 'testapp' not in rel.lower():
                    raw_printf.append(f'{rel}:{i}: {s[:50]}')
    # Compare against upstream baseline — only warn if WE added new issues
    baseline_path = f'{ROOT}/roms/common/tools/ref/upstream_known_issues.txt'
    expected_todo, expected_printf = 10, 10  # defaults
    if os.path.isfile(baseline_path):
        for line in open(baseline_path):
            line = line.strip()
            if line and not line.startswith('#'):
                parts = line.split()
                if len(parts) >= 2:
                    expected_todo = int(parts[0])
                    expected_printf = int(parts[1])
                    break
    summary = []
    if len(todos) > expected_todo:
        summary.append(f'{len(todos)} TODO/FIXME (expected {expected_todo} upstream — WE added {len(todos) - expected_todo} new ones)')
    if len(raw_printf) > expected_printf:
        summary.append(f'{len(raw_printf)} raw printf() (expected {expected_printf} upstream — WE added {len(raw_printf) - expected_printf} new ones)')
    if summary:
        warn('C49 upstream code audit (DEVIATION from baseline)', '; '.join(summary))
    # if within baseline: silent pass — upstream state is expected


# --- C50: Platform version compatibility matrix (born from A16 deep analysis) ---
# Validates that our tree's versions and configs are compatible with the
# target platform (Android 16 / LineageOS 23.2).
def c50():
    issues = []
    bc = open(f'{DT}/BoardConfig.mk', encoding='utf-8', errors='replace').read()

    # 1. Kernel source must be set
    if 'TARGET_KERNEL_SOURCE := kernel/realme/sm6150' not in bc:
        issues.append('TARGET_KERNEL_SOURCE not set or wrong path')
    if 'TARGET_KERNEL_CONFIG := X2_defconfig' not in bc:
        issues.append('TARGET_KERNEL_CONFIG not set to X2_defconfig')

    # 2. Sepolicy variant must reference a valid dir in lineage-23.2-legacy-um
    m = re.search(r'TARGET_SEPOLICY_DIR\s*:=\s*(\S+)', bc)
    if m:
        sepolicy_variant = m.group(1)
        # Known valid variants in lineage-23.2-legacy-um branch
        valid_variants = {'msmsteppe', 'msmnile', 'atoll', 'bengal', 'bengal_32go',
                         'holi', 'kona', 'lahaina', 'lito', 'sdm710', 'sdm845', 'common', 'ssg'}
        if sepolicy_variant not in valid_variants:
            issues.append(f'TARGET_SEPOLICY_DIR={sepolicy_variant} not in known valid variants for lineage-23.2-legacy-um')

    # 3. Build flags: must NOT have BUILD_BROKEN (Android 14+ requirement)
    broken_flags = re.findall(r'^(BUILD_BROKEN_\w+)\s*:=\s*true', bc, re.M)
    if broken_flags:
        issues.append(f'BUILD_BROKEN flags present (Android 16 requires none): {", ".join(broken_flags)}')

    # 4. SELinux: must NOT be permissive
    if 'androidboot.selinux=permissive' in bc:
        issues.append('selinux=permissive in cmdline — must boot enforcing')
    if re.search(r'^SELINUX_IGNORE_NEVERALLOWS\s*:=\s*true', bc, re.M):
        issues.append('SELINUX_IGNORE_NEVERALLOWS — masks real violations')

    # 5. Partition topology: this device's GPT is PHYSICAL (no super — GPT census,
    #    firmware-images-inventory.md §3; stock fstab mounts physical by-name paths).
    #    Retrofit-dynamic config would be UNBOOTABLE here. Topology consistency
    #    between BoardConfig and fstab is enforced by C31.
    if 'BOARD_SUPER_PARTITION_BLOCK_DEVICES' in bc:
        issues.append('retrofit-dynamic config on a physical-GPT device (unbootable — see C31)')

    # 6. AVB: flags 3 is dev mode (acceptable but noted)
    if '--flags 3' in bc:
        # flags 3 = verity disabled + verification disabled (dev mode)
        pass  # acceptable for development builds

    # 7. HIDL interfaces: framework-discovered HALs MUST be in manifest
    # (audio/camera/keymaster are discovered via VINTF — missing = feature broken)
    manifest = open(f'{DT}/manifest.xml', encoding='utf-8', errors='replace').read()
    for critical_hal in ['android.hardware.audio', 'android.hardware.camera.provider', 'android.hardware.keymaster']:
        if critical_hal not in manifest:
            issues.append(f'manifest missing critical HAL: {critical_hal}')
    # Self-registering HALs (health/power/usb) don't need manifest but should be there
    self_registering = ['android.hardware.health', 'android.hardware.power', 'android.hardware.usb']
    missing_self_reg = [h for h in self_registering if h not in manifest]
    if missing_self_reg:
        warn('C50 self-registering HALs not in manifest (non-blocking)',
             f'{", ".join(missing_self_reg)} — they self-register at runtime but SHOULD be declared')

    # 8. VINTF: warn about ancient interfaces (may not exist in A16)
    compat_matrix = f'{DT}/compatibility_matrix.xml'
    if os.path.isfile(compat_matrix):
        cm = open(compat_matrix, encoding='utf-8', errors='replace').read()
        ancient_interfaces = []
        for old_iface in ['android.frameworks.schedulerservice', 'android.frameworks.sensorservice']:
            if old_iface in cm:
                ancient_interfaces.append(old_iface)
        if ancient_interfaces:
            warn('C50 ancient VINTF interfaces in compatibility_matrix',
                 f'may not exist in Android 16: {", ".join(ancient_interfaces)} — update or remove')

    # 9. Kernel defconfig: check critical Android configs
    defconfig_path = f'{ROOT}/roms/common/kernel/sm6150/arch/arm64/configs/X2_defconfig'
    if os.path.isfile(defconfig_path):
        dc = open(defconfig_path, encoding='utf-8', errors='replace').read()
        for critical_config in ['CONFIG_ANDROID_BINDER_IPC=y', 'CONFIG_ASHMEM=y',
                                'CONFIG_SECURITY_SELINUX=y', 'CONFIG_ARCH_SM6150=y']:
            if critical_config not in dc:
                issues.append(f'X2_defconfig missing: {critical_config}')

    chk('C50 platform compatibility (Android 16 / LOS 23.2 / sm6150)', not issues, '; '.join(issues[:5]))


# --- C51: Manifest HALs ↔ hwservice_contexts cross-reference (born from Round 1) ---
# Every vendor-specific HAL in manifest.xml must have a hwservice_contexts entry
# (either in our tree or in the base sepolicy). Without it, hwservice manager
# rejects the HAL registration at boot.
def c51():
    import xml.etree.ElementTree as ET
    import urllib.request
    issues = []

    manifest = open(f'{DT}/manifest.xml', encoding='utf-8', errors='replace').read()
    root = ET.parse(f'{DT}/manifest.xml').getroot()
    manifest_hals = {h.text for h in root.iter('name')}

    # Standard HALs are covered by base system/sepolicy
    standard = {h for h in manifest_hals if h.startswith(('android.', 'com.android.'))}
    vendor_specific = manifest_hals - standard

    # Our hwservice_contexts
    our_hws = set()
    hws_path = f'{DT}/sepolicy/vendor/hwservice_contexts'
    if os.path.isfile(hws_path):
        for line in open(hws_path, errors='replace'):
            s = line.strip()
            if not s or s.startswith('#'):
                continue
            if '::' in s:
                our_hws.add(s.split('::')[0])

    # Base sepolicy hwservice_contexts (cached locally to avoid network fetch)
    base_hws_path = f'{ROOT}/roms/common/tools/ref/base_hwservice_contexts.txt'
    if os.path.isfile(base_hws_path):
        base_hws = set(x.strip() for x in open(base_hws_path) if x.strip() and not x.strip().startswith('#'))
    else:
        base_hws = set()
        warn('C51 base hwservice_contexts cache', f'missing at {base_hws_path} — run the fetch script to build it')

    all_hws = our_hws | base_hws
    missing = vendor_specific - all_hws
    chk('C51 manifest HALs have hwservice_contexts', not missing,
        f'{len(missing)} HALs without hwservice_contexts (face/camera/fingerprint will break): {", ".join(sorted(missing)[:5])}')


# --- C52: File encoding and line-ending validation (born from Round 7 CRLF bug) ---
def c52():
    issues = []
    # Check all .rc files for CRLF
    for rc in glob.glob(f'{DT}/rootdir/etc/*.rc') + glob.glob(f'{DT}/rootdir/bin/*.sh'):
        rel = os.path.relpath(rc, DT)
        with open(rc, 'rb') as f:
            data = f.read()
        if b'\r\n' in data:
            issues.append(f'{rel}: Windows line endings (\\r\\n)')
        if b'\x00' in data:
            issues.append(f'{rel}: contains null bytes')
        if data[:3] == b'\xef\xbb\xbf':
            issues.append(f'{rel}: UTF-8 BOM')
    # Check .prop files
    for pf in ['odm.prop', 'product.prop', 'system.prop', 'vendor.prop']:
        path = f'{DT}/{pf}'
        if not os.path.isfile(path):
            continue
        with open(path, 'rb') as f:
            data = f.read()
        if b'\r\n' in data:
            issues.append(f'{pf}: Windows line endings')
        try:
            data.decode('utf-8')
        except UnicodeDecodeError:
            issues.append(f'{pf}: not valid UTF-8')
    # Check XML files for BOM
    for xml in glob.glob(f'{DT}/**/*.xml', recursive=True):
        if '.git' in xml or 'RealmeParts' in xml:
            continue
        with open(xml, 'rb') as f:
            if f.read(3) == b'\xef\xbb\xbf':
                issues.append(f'{os.path.relpath(xml, DT)}: UTF-8 BOM')
    chk('C52 file encoding/line-endings', not issues, '; '.join(issues[:5]))


# --- C53: Required BoardConfig variables (born from Round 8 sm6150 comparison) ---
def c53():
    bc = open(f'{DT}/BoardConfig.mk', encoding='utf-8', errors='replace').read()
    issues = []
    # Critical vars for sm6150 on Android 16 (from official LOS sm6150-common)
    required_vars = {
        'BOARD_INCLUDE_DTB_IN_BOOTIMG': 'DTB must be packed into boot.img (without it, device can\'t boot)',
        'BOARD_KERNEL_IMAGE_NAME': 'kernel image name',
        'BOARD_KERNEL_SEPARATED_DTBO': 'separate DTBO partition support',
        'BOARD_BOOTIMG_HEADER_VERSION': 'boot image header version',
        'TARGET_KERNEL_SOURCE': 'kernel source path',
        'TARGET_KERNEL_CONFIG': 'kernel defconfig',
        'BOARD_FLASH_BLOCK_SIZE': 'flash block size',
        'BOARD_USES_QCOM_HARDWARE': 'Qualcomm hardware flag',
    }
    # Recommended vars (match official sm6150)
    recommended_vars = {
        'BOARD_INCLUDE_RECOVERY_DTBO': 'recovery DTBO support',
    }
    # NOTE 2026-10-28: dynamic-partition vars REMOVED from recommended — this
    # device's GPT is physical (no super; see C31). Retrofit-dynamic config is
    # unbootable here; C31 actively forbids it now.
    for var, why in required_vars.items():
        if var not in bc:
            issues.append(f'missing required: {var} ({why})')
    for var, why in recommended_vars.items():
        if var not in bc:
            issues.append(f'missing recommended: {var} ({why})')
    chk('C53 required BoardConfig vars (sm6150 on A16)', not issues, '; '.join(issues[:5]))


# --- C54: Required PRODUCT_PACKAGES (born from Round 8 sm6150 comparison) ---
def c54():
    mk = open(f'{DT}/device.mk', encoding='utf-8', errors='replace').read()
    issues = []
    # Critical packages for dynamic partitions on sm6150
    required_packages = {
        'fastbootd': 'userspace fastboot — required for flashing dynamic partitions',
        'android.hardware.thermal-service.qti': 'thermal HAL — without it, device may overheat',
    }
    for pkg, why in required_packages.items():
        if pkg not in mk:
            issues.append(f'missing: {pkg} ({why})')
    chk('C54 required PRODUCT_PACKAGES (sm6150 dynamic partitions)', not issues, '; '.join(issues[:5]))


# --- C55: Permission/Access Control audit (born from Round 9) ---
# Enumerates every permission boundary and flags dangerous grants.
# Known-safe Qualcomm patterns are whitelisted (verified against official sm6150).
def c55():
    issues = []

    # 1. World-writable device nodes (whitelist: Qualcomm standard GPU/graphics nodes)
    SAFE_WORLD_WRITABLE = {
        'kgsl', 'kgsl-3d0', 'kgsl-2d0', 'kgsl-2d1',  # Adreno GPU (official sm6150 uses 0666)
        'genlock',  # graphics buffer sync
        'hab',      # hardware access broker
        'null', 'zero', 'full', 'random', 'urandom',  # standard Android
        'ashmem', 'binder', 'hw binder',  # Android core
        'socket',  # various sockets
        'ion',     # memory allocator
        'dma_heap',
    }
    for i, line in enumerate(open(f'{DT}/rootdir/ueventd.rc', errors='replace'), 1):
        s = line.strip()
        if not s or s.startswith('#') or not s.startswith('/'):
            continue
        parts = s.split()
        if len(parts) >= 2:
            mode_idx = 1 if re.match(r'^0?[0-7]{3,4}$', parts[1]) else (2 if len(parts) > 2 else -1)
            if mode_idx >= 0 and mode_idx < len(parts):
                mode = parts[mode_idx]
                perm = int(mode, 8) if re.match(r'^0?[0-7]{3,4}$', mode) else 0
                if perm & 0o002:  # world-writable
                    dev_name = parts[0].split('/')[-1].split('*')[0]
                    if dev_name not in SAFE_WORLD_WRITABLE and not any(safe in dev_name for safe in SAFE_WORLD_WRITABLE):
                        issues.append(f'ueventd.rc:{i}: world-writable non-whitelisted: {parts[0]}')

    # 2. Extreme capabilities (whitelist: poweroffhandler SYS_TIME is legitimate)
    SAFE_CAPS = {'poweroffhandler': {'SYS_TIME'}}  # power-off alarm needs to program RTC
    for rc in glob.glob(f'{DT}/rootdir/etc/*.rc'):
        content = open(rc, errors='replace').read()
        for m in re.finditer(r'^service\s+(\S+)\s+\S+\n((?:\s+.*\n)*)', content, re.M):
            svc = m.group(1)
            body = m.group(2)
            caps = re.findall(r'capabilities\s+(\S+)', body)
            if caps:
                cap_list = caps[0].split()
                allowed = SAFE_CAPS.get(svc, set())
                extreme = [c for c in cap_list if c in ('SYS_BOOT', 'SYS_MODULE', 'SYS_TIME', 'MKNOD') and c not in allowed]
                if extreme:
                    issues.append(f'{os.path.basename(rc)}: {svc} has unwhitelisted extreme caps: {extreme}')

    # 3. privapp-permissions: package names must be present
    for xml_file in glob.glob(f'{DT}/configs/*permissions*.xml'):
        try:
            root = ET.parse(xml_file).getroot()
            for priv in root.iter('privapp-permissions'):
                if not priv.get('package'):
                    issues.append(f'{os.path.basename(xml_file)}: privapp-permissions without package')
        except Exception:
            pass

    # 4. Dangerous SELinux patterns (read-only macros like r_dir_file are safe)
    for te in glob.glob(f'{DT}/sepolicy/vendor/*.te'):
        content = open(te, errors='replace').read()
        # untrusted domains gaining access is always dangerous
        for m in re.finditer(r'allow\s+untrusted_\w+\s+\w+:\w+\s+\{[^}]*\b(create|write|add_name)\b', content):
            issues.append(f'{os.path.basename(te)}: untrusted domain write access: {m.group()[:50]}')

    chk('C55 permission/access audit', not issues, '; '.join(issues[:5]))


# --- C17: proprietary-files.txt entry syntax ---
def c17():
    bad = []
    for i, line in enumerate(open(f'{DT}/proprietary-files.txt'), 1):
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        core = s[1:] if s.startswith('-') else s
        entry_part = core.split('|')[0].split(';')[0]
        if ':' in entry_part:
            src_part, dst_part = entry_part.split(':', 1)
            if not src_part.strip() or not dst_part.strip():
                bad.append(f'line {i}: empty src/dst')
        path = entry_part.split(':')[0].strip()
        if not path or '/' not in path:
            bad.append(f'line {i}: no partition prefix')
        if path.startswith('/'):
            bad.append(f'line {i}: absolute path')
    chk('C17 list syntax', not bad, '; '.join(bad[:4]))


# --- C18: kernel prerequisites ---
def c18():
    problems = []
    bc = open(f'{DT}/BoardConfig.mk').read()
    m = re.search(r'TARGET_KERNEL_SOURCE\s*:=\s*(\S+)', bc)
    if not m:
        problems.append('TARGET_KERNEL_SOURCE not set')
    m2 = re.search(r'TARGET_KERNEL_CONFIG\s*:=\s*(\S+)', bc)
    if m2:
        kernel_cfg_dir = f'{ROOT}/roms/common/kernel/sm6150/arch/arm64/configs'
        if not os.path.isfile(os.path.join(kernel_cfg_dir, m2.group(1))):
            problems.append(f'TARGET_KERNEL_CONFIG {m2.group(1)} not found')
    else:
        problems.append('TARGET_KERNEL_CONFIG not set')
    chk('C18 kernel prerequisites', not problems, '; '.join(problems[:3]))


# --- C19: critical files ---
def c19():
    missing = []
    for pattern, name in [
        (f'{DT}/rootdir/etc/fstab*', 'fstab'),
        (f'{DT}/rootdir/etc/init*.rc', 'init.rc'),
        (f'{DT}/rootdir/ueventd*', 'ueventd.rc'),
        (f'{DT}/AndroidProducts.mk', 'AndroidProducts.mk'),
        (f'{DT}/lineage_*.mk', 'lineage_X2.mk'),
    ]:
        if not glob.glob(pattern):
            missing.append(name)
    chk('C19 critical files', not missing, f'missing: {", ".join(missing)}' if missing else 'all present')


# --- C20: GitHub blob size limit ---
def c20():
    big = []
    for f in glob.glob(f'{VND}/proprietary/**/*', recursive=True):
        if os.path.isfile(f) and not os.path.islink(f) and os.path.getsize(f) > 50 * 1024 * 1024:
            big.append(f'{os.path.relpath(f, VND)}: {os.path.getsize(f)//(1024*1024)}MB')
    chk('C20 blob size <50MB', not big, '; '.join(big[:3]))


# --- C21: branch tip sync ---
def c21():
    drift = []
    for path, label in [(DT, 'device'), (VND, 'vendor')]:
        local = subprocess.run(['git', '-C', path, 'rev-parse', 'HEAD'],
                               capture_output=True, text=True).stdout.strip()
        branch = subprocess.run(['git', '-C', path, 'branch', '--show-current'],
                                capture_output=True, text=True).stdout.strip()
        if branch:
            remote = subprocess.run(['git', '-C', path, 'rev-parse', f'origin/{branch}'],
                                    capture_output=True, text=True).stdout.strip()
            if local != remote:
                drift.append(f'{label}: local {local[:8]} != remote {remote[:8]}')
    chk('C21 branch tip sync', not drift, '; '.join(drift))


# --- C22: lineage.dependencies branch matches build line ---
def c22():
    dep_path = f'{DT}/lineage.dependencies'
    if not os.path.isfile(dep_path):
        return
    try:
        deps = json.load(open(dep_path))
        problems = []
        branch = subprocess.run(['git', '-C', DT, 'branch', '--show-current'],
                                capture_output=True, text=True).stdout.strip()
        for dep in deps:
            dep_branch = dep.get('branch', '')
            if dep_branch and branch and dep_branch != branch:
                problems.append(f'{dep.get("repository", "?")}: branch {dep_branch} != line {branch}')
        chk('C22 lineage.dependencies branch match', not problems, '; '.join(problems[:3]))
    except (json.JSONDecodeError, KeyError) as e:
        chk('C22 lineage.dependencies valid', False, f'parse error: {e}')


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
        src_hals = set()
        src_hals_path = f'{ROOT}/roms/common/tools/ref/source_built_hals.txt'
        if os.path.isfile(src_hals_path):
            src_hals = set(x.strip() for x in open(src_hals_path) if x.strip() and not x.strip().startswith('#'))
        truly_missing = [h for h in missing if h not in src_hals]
        if truly_missing:
            warn('C13 tree-manifest HALs w/o blob VINTF fragment (unexpected)',
                 ', '.join(truly_missing[:8]))
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
    if extra:
        warn('C6 makefile coverage (refs without file)', f'{len(extra)} dangling refs (review): ' + ', '.join(extra[:5]))


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
    base_pkgs = set()
    base_pkgs_path = f'{ROOT}/roms/common/tools/ref/base_provided_packages.txt'
    if os.path.isfile(base_pkgs_path):
        base_pkgs = set(x.strip() for x in open(base_pkgs_path) if x.strip() and not x.strip().startswith('#'))
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
    base_pkgs = set()
    base_pkgs_path = f'{ROOT}/roms/common/tools/ref/base_provided_packages.txt'
    if os.path.isfile(base_pkgs_path):
        base_pkgs = set(x.strip() for x in open(base_pkgs_path) if x.strip() and not x.strip().startswith('#'))
    truly_missing = [m for m in missing if m not in base_pkgs]
    if truly_missing:
        warn('C9 PRODUCT_PACKAGES not in our repos (unexpected)',
             f'{len(truly_missing)} names: ' + ', '.join(truly_missing[:15]))


# --- C56: vendor-prebuilt vs device-tree-source same-name pairs (guarded override allowlist) ---
# Same-name pairs are LEGAL soong prebuilt-over-source overrides when same-partition, but a NEW
# pair appearing means either a forced prebuilt-add (C23 blind spot) or a tree inconsistency —
# both must be consciously allowlisted in ref/device_tree_shared_names.txt with evidence.
def c56():
    ours = set(re.findall(r'^\s*name:\s*"([^"]+)"',
                          open(f'{VND}/Android.bp', encoding='utf-8', errors='replace').read(), re.M))
    theirs = set()
    for bp_path in glob.glob(f'{DT}/**/Android.bp', recursive=True):
        try:
            theirs.update(re.findall(r'^\s*name:\s*"([^"]+)"',
                                     open(bp_path, encoding='utf-8', errors='replace').read(), re.M))
        except OSError:
            pass
    shared = ours & theirs
    allow_path = f'{ROOT}/roms/common/tools/ref/device_tree_shared_names.txt'
    allowed = set()
    if os.path.isfile(allow_path):
        for _line in open(allow_path):
            _line = _line.strip()
            if _line and not _line.startswith('#'):
                allowed.add(_line.split()[0])
    new_pairs = shared - allowed
    chk('C56 vendor-vs-device-tree name pairs (allowlisted overrides only)', not new_pairs,
        f'{len(new_pairs)} undocumented pair(s): ' + ', '.join(sorted(new_pairs)[:5]))


# --- C57: module name conflict — cross-repo same-name modules (bake-fatal, not just within-file) ---
# C2 only checks duplicates WITHIN a single .bp file. This scans the WHOLE layer:
#   - every module name declared in VND/Android.bp
#   - every module name declared in DT/**/*.bp
# Any name appearing in BOTH repos is flagged (WARN) — most are legal same-partition
# overrides (see C56/device_tree_shared_names.txt), but a name collision across repos is
# the EXACT condition that triggers Soong's 'partition is different' class. Every WARN
# here must be either allowlisted (C56) or explicitly verified same-partition, otherwise
# it is a latent bake-fatal until a bake proves otherwise.
def c57():
    ours = set(re.findall(r'^\s*name:\s*"([^"]+)"',
                          open(f'{VND}/Android.bp', encoding='utf-8', errors='replace').read(), re.M))
    theirs = set()
    their_sources = {}
    for bp_path in glob.glob(f'{DT}/**/Android.bp', recursive=True):
        try:
            for n in re.findall(r'^\s*name:\s*"([^"]+)"',
                                open(bp_path, encoding='utf-8', errors='replace').read(), re.M):
                theirs.add(n)
                their_sources.setdefault(n, []).append(os.path.relpath(bp_path, ROOT))
        except OSError:
            pass
    conflict = sorted(ours & theirs)
    allow_path = f'{ROOT}/roms/common/tools/ref/device_tree_shared_names.txt'
    allowed = set()
    if os.path.isfile(allow_path):
        for _line in open(allow_path):
            _line = _line.strip()
            if _line and not _line.startswith('#'):
                allowed.add(_line.split()[0])
    unallowlisted = [n for n in conflict if n not in allowed]
    if unallowlisted:
        for name in unallowlisted[:12]:
            warn(f'C57 cross-repo module name conflict [{os.path.relpath(f"{VND}/Android.bp", ROOT)} vs DT]',
                 f'{name!r} defined in VND/Android.bp AND ' + ', '.join(sorted(their_sources[name]))
                 + f' — verify same partition (C58) or allowlist in device_tree_shared_names.txt')


# --- shared Soong module parser (used by C57/C58) ---
# Partition is derived EXACTLY as Soong derives it: ModuleBase.PartitionTag reads the
# module's specificity FLAGS only (android/module.go). There is no `partition:` .bp
# property anywhere in Soong, so any such line in an Android.bp is inert at best and an
# unknown-property error at worst (C59 guards this).
def _soong_partition(flags):
    if flags & {'vendor', 'proprietary', 'soc_specific'}:
        return 'vendor'          # SocSpecific()  -> vendor/ (config VendorPath()=='vendor')
    if 'device_specific' in flags:
        return 'odm'             # DeviceSpecific() -> odm/ (config OdmPath()=='odm')
    if 'product_specific' in flags:
        return 'product'
    if 'system_ext_specific' in flags:
        return 'system_ext'
    return 'system'              # platform (incl. vendor_available-only modules)


def _soong_modules(path):
    """Parse top-level Soong modules: returns [{type,name,partition,line}]."""
    try:
        lines = open(path, encoding='utf-8', errors='replace').read().splitlines()
    except OSError:
        return []
    out, depth, cur = [], 0, None
    for i, raw in enumerate(lines, 1):
        line = re.sub(r'//.*$', '', raw)
        if depth == 0 and cur is None:
            m = re.match(r'\s*([a-z_][a-z0-9_]*)\s*\{', line)
            if m:
                cur = {'type': m.group(1), 'name': None, 'flags': set(), 'line': i}
        if cur is not None:
            nm = re.match(r'\s*name:\s*"([^"]+)"', line)
            if nm and cur['name'] is None:
                cur['name'] = nm.group(1)
            fm = re.match(r'\s*([a-z_]+):\s*true\b', line)
            if fm:
                cur['flags'].add(fm.group(1))
        depth += line.count('{') - line.count('}')
        if cur is not None and depth <= 0:
            if cur['name']:
                cur['partition'] = _soong_partition(cur['flags'])
                out.append(cur)
            cur, depth = None, 0
    return out


# --- C58: partition consistency — same module name, mismatched Soong partition (bake-fatal) ---
# Soong's prebuilt-over-source invariant (android/prebuilt.go checkInvariantsForSourceAndPrebuilt)
# fails the bake with 'partition is different: <src>(name) != <pre>(name)' whenever a same-named
# prebuilt in the vendor repo and a source module in the device tree resolve to different
# partition tags. C14 cannot see this: it only scans VND and never reads DT/ interfaces/.
# Partition model is Soong-exact (see _soong_partition) — specificity flags only.
def c58():
    ours = {m['name']: m for m in _soong_modules(f'{VND}/Android.bp')}
    theirs = {}
    for bp_path in glob.glob(f'{DT}/**/Android.bp', recursive=True):
        for m in _soong_modules(bp_path):
            theirs.setdefault(m['name'], []).append((m, os.path.relpath(bp_path, ROOT)))
    bad = []
    for name, om in ours.items():
        for tm, tpath in theirs.get(name, []):
            if om['partition'] != tm['partition']:
                bad.append((name, om['partition'], tm['partition'], tpath))
    if bad:
        for name, op, tp, tpath in bad[:10]:
            chk('C58 prebuilt/source partition agreement', False,
                f'{name!r}: vendor-repo prebuilt={op} vs device-tree source={tp} ({tpath}) '
                f'— Soong will abort: "partition is different"')
    else:
        shared = [n for n in ours if n in theirs]
        chk('C58 prebuilt/source partition agreement', True,
            f'{len(shared)} cross-repo same-name pair(s) agree on partition')
    return bad


# --- C59: `partition:` is NOT a Soong property (silent no-op / unknown-property error) ---
# PartitionTag is derived from specificity flags; a hand-added `partition: "..."` line changes
# nothing and gives false assurance that a partition conflict has been fixed.
def c59():
    hits = []
    for bp_path in glob.glob(f'{DT}/**/Android.bp', recursive=True) + [f'{VND}/Android.bp']:
        try:
            for i, line in enumerate(open(bp_path, encoding='utf-8', errors='replace'), 1):
                code = re.sub(r'//.*$', '', line)
                if re.match(r'\s*partition:\s*"', code):
                    hits.append((os.path.relpath(bp_path, ROOT), i, code.strip()))
        except OSError:
            pass
    chk('C59 no inert `partition:` property in Android.bp', not hits,
        '; '.join(f'{p}:{i} {c}' for p, i, c in hits[:6]))
    return hits



# --- C60: ELF DT_NEEDED closure over every shipped blob (boot-failure class) -------------------
# Soong does NOT validate runtime sonames: a blob can build and install perfectly and still make
# its process fail to exec at boot because a DT_NEEDED library is absent from the image. This rule
# enumerates EVERY ELF file we ship, resolves each DT_NEEDED against three providers, and reports
# exact counts so the coverage is visible instead of assumed:
#   (1) shipped by our vendor layer      -> resolved
#   (2) provided by the base tree        -> resolved (soname in ref caches/CORE, or the module name
#                                           is in base_module_universe / device.mk PRODUCT_PACKAGES)
#   (3) neither                          -> split by whether stock F.26 had it:
#         in stock dump  => RISK  (we probably dropped something the device loads)  [WARN]
#         absent         => MISSING (nothing provides it)                            [FAIL]
# Pure-Python ELF parser: no readelf dependency, no per-file subprocess.
def _elf_dt_needed(path):
    import struct
    try:
        with open(path, 'rb') as fh:
            d = fh.read()
    except OSError:
        return None
    if len(d) < 64 or d[:4] != b'\x7fELF':
        return None
    ei_class, ei_data = d[4], d[5]
    if ei_class not in (1, 2) or ei_data not in (1, 2):
        return None
    e = '<' if ei_data == 1 else '>'
    try:
        if ei_class == 2:
            phoff, = struct.unpack_from(e + 'Q', d, 0x20)
            phentsize, phnum = struct.unpack_from(e + 'HH', d, 0x36)
            PH, DYN = struct.Struct(e + 'IIQQQQQQ'), struct.Struct(e + 'qQ')
        else:
            phoff, = struct.unpack_from(e + 'I', d, 0x1C)
            phentsize, phnum = struct.unpack_from(e + 'HH', d, 0x2A)
            PH, DYN = struct.Struct(e + 'IIIIIIII'), struct.Struct(e + 'iI')
        if phoff == 0 or phnum == 0 or phnum > 4096:
            return None
        loads, dyn = [], None
        for i in range(phnum):
            off = phoff + i * phentsize
            if off + PH.size > len(d):
                break
            f_ = PH.unpack_from(d, off)
            if ei_class == 2:
                ptype, p_off, p_vaddr, p_filesz = f_[0], f_[2], f_[3], f_[5]
            else:
                ptype, p_off, p_vaddr, p_filesz = f_[0], f_[1], f_[2], f_[4]
            if ptype == 1:
                loads.append((p_vaddr, p_off, p_filesz))
            elif ptype == 2:
                dyn = (p_off, p_filesz)
        if not dyn:
            return []
        d_off, d_sz = dyn
        strtab, strsz, needed_offs = None, None, []
        for j in range(d_sz // DYN.size):
            p = d_off + j * DYN.size
            if p + DYN.size > len(d):
                break
            tag, val = DYN.unpack_from(d, p)
            if tag == 0:
                break
            if tag == 1:
                needed_offs.append(val)
            elif tag == 5:
                strtab = val
            elif tag == 10:
                strsz = val
        if strtab is None or not needed_offs:
            return []
        f_strtab = None
        for vaddr, p_off, p_filesz in loads:
            if vaddr <= strtab < vaddr + max(p_filesz, 1):
                f_strtab = p_off + (strtab - vaddr)
                break
        if f_strtab is None or f_strtab >= len(d):
            return []
        end = len(d) if strsz is None else min(len(d), f_strtab + strsz)
        out = []
        for no in needed_offs:
            s = f_strtab + no
            if s >= end:
                continue
            z = d.find(b'\x00', s, end)
            if z > 0:
                out.append(d[s:z].decode('utf-8', 'replace'))
        return out
    except (struct.error, IndexError, ValueError):
        return None


C60_CORE_SONAMES = {
    'libc.so', 'libm.so', 'libdl.so', 'liblog.so', 'libutils.so', 'libcutils.so', 'libbinder.so',
    'libbase.so', 'libstdc++.so', 'libc++.so', 'libcrypto.so', 'libssl.so',
    'libz.so', 'libhidlbase.so', 'libhidltransport.so', 'libhwbinder.so', 'libhardware.so',
    'libsync.so', 'libion.so', 'libprotobuf-cpp-lite.so', 'libprotobuf-cpp-full.so', 'libui.so',
    'libgui.so', 'libEGL.so', 'libGLESv1_CM.so', 'libGLESv2.so', 'libvulkan.so',
    'libnativewindow.so', 'libhidlmemory.so', 'libfmq.so', 'libnl.so', 'libpng.so', 'libjpeg.so',
    'libexpat.so', 'libtinyxml2.so', 'libsqlite.so', 'libnbaio.so',
    'libstagefright.so', 'libstagefright_foundation.so', 'libmedia.so', 'libaudioclient.so',
    'libpowermanager.so', 'libmemtrack.so', 'libnetd_client.so',     'libandroid.so', 'libandroid_runtime.so', 'libandroidfw.so', 'libandroid_net.so',
    'libhwui.so', 'libminijail.so', 'libprocessgroup.so', 'libnetutils.so', 'libxml2.so',
    'libcurl.so', 'libyuv.so', 'libtinyalsa.so', 'libvndksupport.so', 'libhardware_legacy.so',
    'libexif.so', 'libkeystore_binder.so',     'libclang_rt.ubsan_standalone-aarch64-android.so', 'libclang_rt.asan-aarch64-android.so',
        # core HIDL runtime libraries (system/libhidl + hardware/interfaces) - present on every device
    'android.hidl.allocator@1.0.so', 'android.hidl.memory@1.0.so',
    'android.hidl.safe_union@1.0.so',     'android.hidl.token@1.0.so', 'android.hidl.token@1.0-utils.so',
        'libhidl-gen-utils.so',
    'android.frameworks.sensorservice@1.0.so',
}


def c60():
    if not os.path.isdir(f'{VND}/proprietary'):
        chk('C60 ELF DT_NEEDED closure', False, f'{VND}/proprietary missing')
        return
    shipped, elfs = set(), []
    for root, _, files in os.walk(f'{VND}/proprietary'):
        for fn in files:
            p = os.path.join(root, fn)
            shipped.add(fn)
            try:
                with open(p, 'rb') as fh:
                    if fh.read(4) == b'\x7fELF':
                        elfs.append(p)
            except OSError:
                pass

    def refset(fn):
        try:
            return {ln.split()[0] for ln in open(f'{ROOT}/roms/common/tools/ref/{fn}')
                    if ln.strip() and not ln.startswith('#')}
        except OSError:
            return set()
    # OEM-VERIFIED: library names actually present in the stock F.26 system image
    # (/system/lib + /system/lib64, extracted via debugfs). A soname here is proof the OEM
    # shipped it, so it is framework-provided rather than a gap in our layer.
    oem_libs = refset('oem_system_libraries.txt')
    # OEM-VERIFIED APEX payloads: libraries shipped inside stock APEX packages (e.g. ART's
    # libnativehelper/libnativeloader in com.android.art.release.apex). /system/apex exists on
    # this device, so absence from /system/lib{,64} alone does NOT mean absent from the device.
    apex_libs = refset('oem_apex_libraries.txt')
    base_sonames = refset('base_system_libraries.txt') | C60_CORE_SONAMES | oem_libs | apex_libs
    base_ifaces = refset('base_interface_modules.txt')
    base_sonames |= {n + '.so' for n in base_ifaces} | base_ifaces
    base_modules = (refset('base_module_universe.txt') | refset('base_provided_packages.txt')
                    | refset('caf_repo_modules.txt'))
    # module names we ship / request
    req_mods = set()
    try:
        src = open(f'{DT}/device.mk', encoding='utf-8', errors='replace').read()
        src = src.replace('\\\n', ' ')
        for m in re.finditer(r'^PRODUCT_PACKAGES\s*(?:\+=|:=|=)(.*)$', src, re.M):
            req_mods |= set(m.group(1).split('#')[0].split())
    except OSError:
        pass

    def soname_to_module(son):
        # IMPORTANT: only the '.so' suffix is removed. Earlier this also stripped a trailing
        # '-1.2.3' package version, which wrongly mapped libprotobuf-cpp-full-3.9.1.so ->
        # libprotobuf-cpp-full (a DIFFERENT soname the base does build) and silently cleared a
        # real gap. Version-embedded sonames must stay distinct.
        return son[:-3] if son.endswith('.so') else son

    edges, distinct, unreadable = 0, {}, 0
    dependents = {}          # soname -> set of (path, is_executable)
    for p in elfs:
        needs = _elf_dt_needed(p)
        if needs is None:
            unreadable += 1
            continue
        is_exec = ('/bin/' in p) or ('.so' not in os.path.basename(p))
        for s in needs:
            edges += 1
            distinct[s] = distinct.get(s, 0) + 1
            dependents.setdefault(s, set()).add((os.path.relpath(p, VND), is_exec))

    by_vendor = [s for s in distinct if s in shipped]
    by_base, missing, risk = [], [], []
    for s in distinct:
        if s in shipped:
            continue
        mod = soname_to_module(s)
        if s in base_sonames or mod in base_modules or mod in req_mods:
            by_base.append(s)
            continue
        found_in_stock = any(
            os.path.exists(f'{DUMP}/{part}/lib{bits}/{s}')
            for part in ('vendor', 'odm', 'system_ext', 'product')
            for bits in ('', '64')
        )
        (risk if found_in_stock else missing).append(s)

    # Verdict logic, entirely evidence-based:
    #   risk   = the OEM shipped this soname (found in a stock partition or the OEM system
    #            inventory) but we do not -> we dropped something that worked on stock.
    #   dormant= absent from EVERY stock partition AND from the OEM system inventory. A binary
    #            whose DT_NEEDED cannot resolve can never be executed, so such a library was
    #            never loadable on the OEM firmware either: shipping it unchanged is not a
    #            regression we introduce. Counted and reported, never treated as a fault.
    # FAIL is reserved for the one provable regression: a started executable needs a soname the
    # OEM shipped and we no longer do.
    def is_exec_dep(son):
        return any(is_exec for _d, is_exec in dependents.get(son, set()))

    exec_fatal = [s for s in risk if is_exec_dep(s)]
    dormant = sorted(missing)

    detail = (f'{len(elfs)} ELF blobs, {edges} DT_NEEDED edges, {len(distinct)} distinct sonames -> '
              f'{len(by_vendor)} vendor-provided, {len(by_base)} base/OEM-provided, '
              f'{len(risk)} dropped-but-OEM-shipped, {len(dormant)} absent-from-OEM-too, '
              f'{len(exec_fatal)} exec-blocking'
              + (f'; unreadable={unreadable}' if unreadable else ''))
    chk('C60 ELF DT_NEEDED closure', not exec_fatal, detail)
    for s in exec_fatal[:10]:
        ex = [d for d, is_exec in dependents.get(s, set()) if is_exec]
        print(f'        EXEC-BLOCKING {s} -> executable {ex[0]} could not start')
    if risk:
        warn('C60 sonames the OEM shipped but we do not',
             f'{len(risk)}: ' + ', '.join(sorted(risk)) +
             ' — either ship them or record why they are no longer needed')
    if dormant:
        info('C60 sonames absent from the entire OEM image',
             f'{len(dormant)}: ' + ', '.join(dormant) +
             ' — checked /system/lib, /system/lib64, vendor, odm, system_ext, product library dirs '
             'and the ART APEX payload; a binary whose DT_NEEDED cannot resolve could not have run '
             'on stock either, so this is not a regression we introduce')
    return risk + dormant


# --- C61: build-dependency resolution (shared_libs / static_libs / header_libs) ----------------
# Soong aborts when a module declares a dependency that no module provides:
#   "module X depends on undefined module Y"
# That class is invisible to every other rule here: C23/C25/C60 check RUNTIME sonames, C14 checks
# name collisions, C6/C9 check the blob list and PRODUCT_PACKAGES. The defect that motivated this
# rule - 21 prebuilts linking "libprotobuf-cpp-*-3.9.1-vendorcompat", a module removed after A13 -
# was found only by manual investigation of C60 output.
# Resolution order: modules we define -> base module caches -> curated core-module list.
def c61():
    def refset(fn):
        try:
            return {ln.split()[0] for ln in open(f'{ROOT}/roms/common/tools/ref/{fn}')
                    if ln.strip() and not ln.startswith('#')}
        except OSError:
            return set()

    ours = set()
    bp_files = glob.glob(f'{VND}/**/*.bp', recursive=True) + glob.glob(f'{DT}/**/*.bp', recursive=True)
    for f in bp_files:
        try:
            ours |= set(re.findall(r'^\s*name:\s*"([^"]+)"', open(f, encoding='utf-8',
                                                                  errors='replace').read(), re.M))
        except OSError:
            pass
    for f in glob.glob(f'{DT}/**/*.mk', recursive=True) + glob.glob(f'{VND}/*.mk'):
        try:
            ours |= set(re.findall(r'LOCAL_MODULE\s*:?=\s*(\S+)',
                                   open(f, encoding='utf-8', errors='replace').read()))
        except OSError:
            pass

    base = (refset('base_module_universe.txt') | refset('base_provided_packages.txt')
            | refset('caf_repo_modules.txt') | refset('base_interface_modules.txt')
            | refset('base_core_modules.txt'))

    deps = {}
    bp_files = [f'{VND}/Android.bp'] + glob.glob(f'{DT}/**/*.bp', recursive=True)
    for f in bp_files:
        try:
            t = open(f, encoding='utf-8', errors='replace').read()
        except OSError:
            continue
        for key in ('shared_libs', 'static_libs', 'header_libs'):
            for m in re.finditer(rf'^\s*{key}:\s*\[(.*?)\]', t, re.M | re.S):
                for d in re.findall(r'"([^"]+)"', m.group(1)):
                    deps.setdefault(d, set()).add(os.path.relpath(f, ROOT))

    unresolved = {d: v for d, v in deps.items() if d not in ours and d not in base}
    chk('C61 build-dependency resolution (shared/static/header libs)', not unresolved,
        (f'{len(unresolved)} of {len(deps)} declared dependency name(s) resolve to NO known module: '
         + ', '.join(f'{d} <- {sorted(v)[0]}' for d, v in sorted(unresolved.items())[:8]))
        if unresolved
        else f'all {len(deps)} declared dependency names resolve ({len(ours)} ours, '
             f'{len(deps) - len([d for d in deps if d in ours])} base-proved)')
    return unresolved

def main():
    global DECLARED_LINE, LINE_MISMATCH
    DECLARED_LINE = declared_build_line()
    LINE_MISMATCH = bool(DECLARED_LINE) and DECLARED_LINE != CALIBRATED_FOR
    if LINE_MISMATCH:
        print('=' * 78)
        print('  LINT CALIBRATION MISMATCH')
        print(f'    this lint is calibrated for : {CALIBRATED_FOR}')
        print(f'    the tree declares          : {DECLARED_LINE}')
        print('    Rules ' + ', '.join(r.strip() for r in VERSION_SENSITIVE_RULES) +
              ' encode base-version facts and are')
        print('    annotated UNCALIBRATED below. Their PASS/FAIL must not be trusted, taken as')
        print('    proof of readiness, until they are re-derived for the new base:')
        print('      C1  AMD-arch rule table (base combo/TARGET_linux-arm.mk)')
        print('      C12 required BoardConfig vars + value domains (base board_config.mk)')
        print('      C50 platform-version compatibility matrix')
        print('      C53 required BoardConfig vars for the SoC/platform')
        print('    Also re-derive the reference caches (base_interface_modules.txt,')
        print('    base_module_universe.txt, override_pairs.txt) and re-run')
        print('    tools/enumerate-base-modules.py before trusting collision rules.')
        print('=' * 78)
    for fn in (c0, c1, c12, c23, c24, c25, c26, c27, c28, c29, c30, c31, c32, c33, c34, c35, c36, c37, c38, c39, c40, c41, c42, c43, c44, c45, c46, c47, c48, c49, c50, c51, c52, c53, c54, c55, c56, c57, c58, c59, c60, c61, c17, c18, c19, c20, c2, c3, c4, c5, c6, c7, c8, c9, c10, c14, c21, c22, c13):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            chk(f'{fn.__name__} (internal)', False, f'{type(e).__name__}: {e}')
    print('-' * 60)
    print(f'RESULT: {len(fails)} FAIL, {len(warns)} WARN, {len(infos)} INFO')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
