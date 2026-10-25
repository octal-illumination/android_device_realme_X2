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
    warn('C23 DT_NEEDED unresolved (not in dump or base — verify)',
         f'{len(unresolved)} names: ' + ', '.join(unresolved[:12]) if unresolved else 'none')


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
            for part in ['vendor/bin/hw', 'vendor/bin', 'odm/bin/hw', 'odm/bin']:
                if os.path.isfile(f'{VND}/proprietary/{part}/{binary}') or os.path.isfile(f'{DUMP}/{part}/{binary}'):
                    found = True
                    break
            if not found and glob.glob(f'{DT}/**/{base_name}', recursive=True):
                found = True
            if not found:
                missing.append(binary)
    warn('C24 RC service binaries (audit)', f'{len(missing)} binaries referenced in .rc not found in blobs/tree: ' + ', '.join(missing[:5]) if missing else 'all service binaries resolve')


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
    warn('C25 DT_NEEDED closure (audit)', f'{len(unresolved)} unresolved names from {checked} blobs: ' + ', '.join(sorted(unresolved)[:8]) if unresolved else f'all {checked} blob DT_NEEDED entries resolve')


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
    warn('C27 VINTF service existence (audit)', f'{len(no_service)}/{len(hal_names)} HALs without .rc service declaration: ' + ', '.join(no_service[:5]) if no_service else 'all HALs have service declarations')


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
    warn('C30 BUILD_BROKEN flags (technical debt)', f'{len(flags)} masking flags present: {", ".join(flags)}' if flags else 'none')


# --- C31: Partition layout consistency (born from dynamic partitions gap) ---
def c31():
    bc = open(f'{DT}/BoardConfig.mk', encoding='utf-8', errors='replace').read()
    has_dynamic = 'BOARD_SUPER_PARTITION_BLOCK_DEVICES' in bc
    has_static = bool(re.search(r'^BOARD_SYSTEMIMAGE_PARTITION_SIZE', bc, re.M))
    fstab = open(f'{DT}/rootdir/etc/fstab.qcom', encoding='utf-8', errors='replace').read()
    has_logical_fstab = 'logical' in fstab
    issues = []
    if has_dynamic and not has_logical_fstab:
        issues.append('BoardConfig has dynamic partitions but fstab lacks logical entries')
    if not has_dynamic and has_logical_fstab:
        issues.append('fstab has logical entries but BoardConfig lacks dynamic partition config')
    if not has_dynamic:
        issues.append('no dynamic partition config (hardware may require super partition — verify)')
    chk('C31 partition layout consistency', not issues, '; '.join(issues))


# --- C32: CPU variant sanity vs sm6150 big.LITTLE topology ---
def c32():
    bc = open(f'{DT}/BoardConfig.mk', encoding='utf-8', errors='replace').read()
    issues = []
    # sm6150: 2x Cortex-A76 (big) + 6x Cortex-A55 (little)
    cpu_variant = re.search(r'^TARGET_CPU_VARIANT\s*:=\s*(\S+)', bc, re.M)
    cpu2_variant = re.search(r'^TARGET_2ND_CPU_VARIANT\s*:=\s*(\S+)', bc, re.M)
    if cpu_variant and cpu_variant.group(1) not in ('cortex-a76', 'kryo'):
        issues.append(f'TARGET_CPU_VARIANT={cpu_variant.group(1)} (expected cortex-a76 for sm6150 big cores)')
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
            if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_.\-]*\s*=', s):
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
    warn('C34 init.rc security audit', f'{no_seclabel_count} services without seclabel, {root_oneshot_count} oneshot-root (Qualcomm core services often lack seclabel by design — review for non-core services)')


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
    for fn in (c0, c1, c12, c23, c24, c25, c26, c27, c28, c29, c30, c31, c32, c33, c34, c35, c36, c37, c17, c18, c19, c20, c2, c3, c4, c5, c6, c7, c8, c9, c10, c14, c21, c22, c13):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            chk(f'{fn.__name__} (internal)', False, f'{type(e).__name__}: {e}')
    print('-' * 60)
    print(f'RESULT: {len(fails)} FAIL, {len(warns)} WARN')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
