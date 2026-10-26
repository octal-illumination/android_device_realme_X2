#
# Copyright (C) 2022 The LineageOS Project
#
# SPDX-License-Identifier: Apache-2.0
#

# Inherit from those products. Most specific first.
$(call inherit-product, $(SRC_TARGET_DIR)/product/core_64_bit.mk)
$(call inherit-product, $(SRC_TARGET_DIR)/product/full_base_telephony.mk)
$(call inherit-product, $(SRC_TARGET_DIR)/product/product_launched_with_p.mk)
$(call inherit-product, $(SRC_TARGET_DIR)/product/non_ab_device.mk)

# Inherit some common LineageOS stuff.
$(call inherit-product, vendor/lineage/config/common_full_phone.mk)

# Inherit from X2 device
$(call inherit-product, device/realme/X2/device.mk)

# LineageOS stuff
TARGET_BOOT_ANIMATION_RES := 1080
SYSTEM_OPTIMIZE_JAVA := true
SYSTEMUI_OPTIMIZE_JAVA := true
TARGET_HAS_UDFPS := true
TARGET_DISABLE_EPPE := true

# Device identifier. This must come after all inclusions.
PRODUCT_NAME := lineage_X2
PRODUCT_DEVICE := X2
PRODUCT_BRAND := realme
PRODUCT_MODEL := realme X2
PRODUCT_MANUFACTURER := realme

PRODUCT_BUILD_PROP_OVERRIDES += \
    BuildDesc="RMX1993L1-user 11 RKQ1.201112.002 1639416071279 release-keys" \
    BuildFingerprint=realme/RMX1993/RMX1993L1:11/RKQ1.201112.002/1639416071279:user/release-keys \
    DeviceProduct=X2 \
    SystemDevice=X2 \
    SystemName=X2

PRODUCT_GMS_CLIENTID_BASE := android-oppo
