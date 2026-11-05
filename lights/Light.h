/*
 * Copyright (C) 2018 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <aidl/android/hardware/light/BnLights.h>
#include <aidl/android/hardware/light/HwLight.h>
#include <aidl/android/hardware/light/HwLightState.h>
#include <aidl/android/hardware/light/LightType.h>
#include <array>
#include <functional>
#include <mutex>
#include <unordered_map>

namespace aidl {
namespace android {
namespace hardware {
namespace light {

using ::aidl::android::hardware::light::HwLight;
using ::aidl::android::hardware::light::HwLightState;
using ::aidl::android::hardware::light::LightType;

class Lights : public BnLights {
  public:
    Lights();

    ndk::ScopedAStatus setLightState(int32_t id, const HwLightState& state) override;
    ndk::ScopedAStatus getLights(std::vector<HwLight>* _aidl_return) override;
    ndk::ScopedAStatus setLightEffects(
            const std::vector<::aidl::android::hardware::light::HwLightEffect>& /* effects */)
            override;

  private:
    void handleBacklight(const HwLightState& state);
    void handleNotification(const HwLightState& state, size_t index);

    std::mutex mLock;
    std::unordered_map<int32_t, std::function<void(const HwLightState&)>> mLights;
    std::array<HwLightState, 3> mLightStates;
};

}  // namespace light
}  // namespace hardware
}  // namespace android
}  // namespace aidl
