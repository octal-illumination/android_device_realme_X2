#!/usr/bin/env -S PYTHONPATH=../../../tools/extract-utils python3
#
# SPDX-FileCopyrightText: 2024 The LineageOS Project
# SPDX-License-Identifier: Apache-2.0
#

from extract_utils.file import File
from extract_utils.fixups_blob import (
    BlobFixupCtx,
    blob_fixup,
    blob_fixups_user_type,
)
from extract_utils.fixups_lib import (
    lib_fixup_remove,
    lib_fixups,
    lib_fixups_user_type,
)
from extract_utils.main import (
    ExtractUtils,
    ExtractUtilsModule,
)
from extract_utils.tools import (
    llvm_objdump_path,
)
from extract_utils.utils import (
    run_cmd,
)

namespace_imports = [
    'device/realme/X2',
    'hardware/qcom-caf/sm8150',
    'hardware/qcom-caf/wlan',
    'vendor/qcom/opensource/commonsys/display',
    'vendor/qcom/opensource/commonsys-intf/display',
    'vendor/qcom/opensource/dataservices',
    'vendor/qcom/opensource/data-ipa-cfg-mgr-legacy-um',
    'vendor/qcom/opensource/display',
]


def lib_fixup_vendor_suffix(lib: str, partition: str, *args, **kwargs):
    return f'{lib}_{partition}' if partition == 'vendor' else None


lib_fixups: lib_fixups_user_type = {
    **lib_fixups,
    (
    ): lib_fixup_vendor_suffix,
    # libsigmautils is DT_NEEDED by libmiracastsystem but exists in NEITHER the F.26
    # stock images NOR any repo in the LOS 23.2 sync set (verified 2026-10-28 against
    # android_hardware_qcom_display, android_vendor_qcom_opensource_display,
    # -display-commonsys, -display-commonsys-intf, -interfaces). extract-utils emits it as
    # a shared_libs entry, which Soong rejects as an undefined module. Dropped so the
    # build dependency is not generated; the blob's own DT_NEEDED is unchanged.
    'libsigmautils': lib_fixup_remove,
}

blob_fixups: blob_fixups_user_type = {

}  # fmt: skip

module = ExtractUtilsModule(
    'X2',
    'realme',
    blob_fixups=blob_fixups,
    lib_fixups=lib_fixups,
    namespace_imports=namespace_imports,
)

if __name__ == '__main__':
    utils = ExtractUtils.device(module)
    utils.run()
