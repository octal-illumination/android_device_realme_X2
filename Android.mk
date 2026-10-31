#
# Copyright (C) 2022 The LineageOS Project
#
# SPDX-License-Identifier: Apache-2.0
#

LOCAL_PATH := $(call my-dir)

ifeq ($(TARGET_DEVICE),X2)

include $(call all-makefiles-under,$(LOCAL_PATH))
# NOTE (Kati failure, 2026-10-31): the legacy mount-point rules were REMOVED.
# A craft-time `mkdir` recipe for $(TARGET_OUT_VENDOR)/firmware_mnt, /bt_firmware and /dsp
# collided with the rules Soong now generates for product-specified directories
# (vendor/lineage/build/core/mkdir.mk -- "may only be used from Soong"), producing:
#   device/realme/X2/Android.mk:19: error: overriding commands for target
#   `out/target/product/X2/vendor/firmware_mnt', previously defined at
#   vendor/lineage/build/core/mkdir.mk:22
# In lineage-23.2 those directories are created by the build system, so the manual rules are
# obsolete. Verified none of this device's products still need them.

endif
