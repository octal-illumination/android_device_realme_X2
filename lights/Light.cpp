/*
 * Copyright (C) 2018 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */

#define LOG_TAG "LightsService"

#include "Light.h"

#include <android-base/logging.h>
#include <android-base/stringprintf.h>
#include <fstream>

namespace aidl {
namespace android {
namespace hardware {
namespace light {

/*
 * Write value to path and close file.
 */
template <typename T>
static void set(const std::string& path, const T& value) {
    std::ofstream file(path);
    file << value;
}

/*
 * Read from path and close file.
 * Return def in case of any failure.
 */
template <typename T>
static T get(const std::string& path, const T& def) {
    std::ifstream file(path);
    T result;

    file >> result;
    return file.fail() ? def : result;
}

static constexpr int kDefaultMaxBrightness = 255;
static constexpr int kRampSteps = 50;
static constexpr int kRampMaxStepDurationMs = 5;

static uint32_t getBrightness(const HwLightState& state) {
    uint32_t alpha, red, green, blue;

    // Extract brightness from AARRGGBB
    alpha = (state.color >> 24) & 0xff;

    // Retrieve each of the RGB colors
    red = (state.color >> 16) & 0xff;
    green = (state.color >> 8) & 0xff;
    blue = state.color & 0xff;

    // Scale RGB colors if a brightness has been applied by the user
    if (alpha != 0xff) {
        red = red * alpha / 0xff;
        green = green * alpha / 0xff;
        blue = blue * alpha / 0xff;
    }

    return (77 * red + 150 * green + 29 * blue) >> 8;
}

static uint32_t rgbToBrightness(const HwLightState& state) {
    uint32_t color = state.color & 0x00ffffff;
    return ((77 * ((color >> 16) & 0xff))
            + (150 * ((color >> 8) & 0xff))
            + (29 * (color & 0xff))) >> 8;
}

Lights::Lights() {
    /* Stable ids: 0 BACKLIGHT, 1 BATTERY, 2 NOTIFICATIONS, 3 ATTENTION.
     * The three notification-class lights share the white LED and the
     * priority logic in handleNotification (indices 0..2 mirror the
     * historical HIDL implementation). */
    mLights.emplace(0, std::bind(&Lights::handleBacklight, this, std::placeholders::_1));
    mLights.emplace(1, std::bind(&Lights::handleNotification, this, std::placeholders::_1, 1));
    mLights.emplace(2, std::bind(&Lights::handleNotification, this, std::placeholders::_1, 2));
    mLights.emplace(3, std::bind(&Lights::handleNotification, this, std::placeholders::_1, 0));
}

void Lights::handleBacklight(const HwLightState& state) {
    int maxBrightness = get("/sys/class/backlight/panel0-backlight/max_brightness", -1);
    if (maxBrightness < 0) {
        maxBrightness = kDefaultMaxBrightness;
    }
    uint32_t sentBrightness = rgbToBrightness(state);
    uint32_t brightness = sentBrightness * maxBrightness / kDefaultMaxBrightness;
    LOG(DEBUG) << "Writing backlight brightness " << brightness
               << " (orig " << sentBrightness << ")";
    set("/sys/class/backlight/panel0-backlight/brightness", brightness);
}

void Lights::handleNotification(const HwLightState& state, size_t index) {
    mLightStates.at(index) = state;

    HwLightState stateToUse = mLightStates.front();
    for (const auto& lightState : mLightStates) {
        if (lightState.color & 0xffffff) {
            stateToUse = lightState;
            break;
        }
    }

    uint32_t whiteBrightness = getBrightness(stateToUse);

    uint32_t onMs = stateToUse.flashMode == FlashMode::TIMED ? stateToUse.flashOnMs : 0;
    uint32_t offMs = stateToUse.flashMode == FlashMode::TIMED ? stateToUse.flashOffMs : 0;

    auto getScaledDutyPercent = [](int brightness) -> std::string {
        std::string output;
        for (int i = 0; i <= kRampSteps; i++) {
            if (i != 0) {
                output += ",";
            }
            output += std::to_string(i * 100 * brightness / (kDefaultMaxBrightness * kRampSteps));
        }
        return output;
    };

    // Disable blinking to start
    set("/sys/class/leds/white/blink", 0);

    if (onMs > 0 && offMs > 0) {
        uint32_t pauseLo, pauseHi, stepDuration;
        if (kRampMaxStepDurationMs * kRampSteps > onMs) {
            stepDuration = onMs / kRampSteps;
            pauseHi = 0;
        } else {
            stepDuration = kRampMaxStepDurationMs;
            pauseHi = onMs - kRampSteps * stepDuration;
            pauseLo = offMs - kRampSteps * stepDuration;
        }

        set("/sys/class/leds/white/start_idx", 0);
        set("/sys/class/leds/white/duty_pcts", getScaledDutyPercent(whiteBrightness));
        set("/sys/class/leds/white/pause_lo", pauseLo);
        set("/sys/class/leds/white/pause_hi", pauseHi);
        set("/sys/class/leds/white/ramp_step_ms", stepDuration);

        // Start blinking
        set("/sys/class/leds/white/blink", 1);
    } else {
        set("/sys/class/leds/white/brightness", whiteBrightness);
    }
}

ndk::ScopedAStatus Lights::setLightState(int32_t id, const HwLightState& state) {
    auto it = mLights.find(id);

    if (it == mLights.end()) {
        return ndk::ScopedAStatus(AStatus_fromExceptionCode(EX_UNSUPPORTED_OPERATION));
    }

    // Lock global mutex until light state is updated.
    std::lock_guard<std::mutex> lock(mLock);

    it->second(state);

    return ndk::ScopedAStatus::ok();
}

ndk::ScopedAStatus Lights::getLights(std::vector<HwLight>* _aidl_return) {
    int id = 0;
    for (auto const& light : mLights) {
        HwLight hwLight;
        hwLight.id = id++;
        hwLight.type = static_cast<LightType>(light.first);
        _aidl_return->push_back(hwLight);
    }
    return ndk::ScopedAStatus::ok();
}

ndk::ScopedAStatus Lights::setLightEffects(
        const std::vector<::aidl::android::hardware::light::HwLightEffect>& /* effects */) {
    /* The A17 ILights surface grew setLightEffects (light AIDL v2+); this
     * device has no effects engine — the historical sysfs ramping path in
     * setLightState covers everything notifications need. */
    return ndk::ScopedAStatus(AStatus_fromExceptionCode(EX_UNSUPPORTED_OPERATION));
}

}  // namespace light
}  // namespace hardware
}  // namespace android
}  // namespace aidl
