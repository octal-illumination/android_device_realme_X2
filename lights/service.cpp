/*
 * Copyright (C) 2018 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */

#define LOG_TAG "LightsService"

#include <android-base/logging.h>
#include <android/binder_manager.h>
#include <android/binder_process.h>

#include "Light.h"

using ::aidl::android::hardware::light::Lights;

int main() {
    ABinderProcess_setThreadPoolMaxThreadCount(0);

    auto lights = ::ndk::SharedRefBase::make<Lights>();
    const std::string instance = std::string(Lights::descriptor) + "/default";
    binder_status_t status = AServiceManager_addService(lights->asBinder().get(), instance.c_str());
    CHECK_EQ(status, STATUS_OK) << "Failed to register ILights default instance";

    ABinderProcess_joinThreadPool();
    return EXIT_FAILURE; /* unreachable */
}
