<!-- HTML sibling: regenerate ONLY via bash ~/Projects/scripts/generate-docs-html.sh roms/docs/research/2026-10-29-manifest-sweep-report.md — Rule 18c left-aligned CSS. Never hand-roll pandoc. -->
# Manifest sweep — exhaustive build-file corpus and collision findings `[Complete]`

> **Note:** All documentation and code in this project are purely AI-generated.

**Run:** 2026-10-29 · **Tool:** `roms/common/tools/sweep-manifest-sources.py` · **Status:** SWEEP COMPLETE

## 1. What was swept

| Metric | Value |
|---|---|
| Manifest projects parsed (default.xml + snippets/lineage.xml) | **1175** |
| Repos completed | **1112 / 1175** |
| Build files cached (`Android.bp` + `Android.mk`) | **6,259** |
| Repos truncated by the 500-file cap | **4** |
| Cache location | `roms/common/tools/ref/sources/manifest/` (34 MB) |
| Revisions | the **manifest-pinned** revision per project, not the line default |

Coverage caveat, stated rather than implied: **63 repos did not complete and 4 were truncated**, so this corpus supports *FOUND* verdicts unconditionally, and *ABSENT* verdicts only for the 1108 fully-swept, untruncated repos.

## 2. Why it exists

Three build cycles were lost to defects that a complete corpus detects instantly. Every one was an
**under-search presented as a verified finding**:

| # | Incident | What the search was | What it missed |
|---|---|---|---|
| 1 | `libprotobuf-cpp-*-3.9.1` | `external/protobuf` only | `prebuilts/misc/protobuf_vendorcompat` (exists, but pruned by `PRODUCT_SOURCE_ROOT_DIRS`) |
| 2 | `vendor.display.config@1.0/@2.0` | an allowlist entry | the allowlist was the hiding place |
| 3 | `libqti_vndfwk_detect`, `libvndfwk_detect_jni.qti` | 3 caf sm8150 repos + 3 qcom display repos | **`hardware/qcom-caf/common`** — which builds both as `system_ext` modules |

Incident 3 **caused the cycle-11 build failure**: shipping vendor prebuilts of names the base already
defines produced `partition is different: system_ext(...) != vendor(prebuilt_...)`.

## 3. Findings from the corpus (20,249 distinct base module names)

### 3.1 Partition mismatch — the class that aborts the build

| Module | Ours | Base |
|---|---|---|
| `com.dsi.ant@1.0` | vendor | system |
| `librmnetctl` | vendor | system |
| `libstdc++` | odm | system |

All three match the incident-3 signature and would abort the build the same way.

### 3.2 Same-name pairs with the base (4, needs adjudication)

`android.hardware.gnss@{1.1,2.1}-impl-qti` and `android.hardware.gnss@{1.1,2.1}-service-qti` are defined
**both** by our device tree (`gps/android/*/Android.mk`) **and** by the base
(`hardware/qcom/sm8150/gps/android/*/Android.bp`).

Status: **UNCERTAIN, not a confirmed failure.** Both repos declare a `soong_namespace`, which can make
same-name modules legal across namespaces — but incident 3 shows prebuilt/source resolution crosses
namespace boundaries for the partition check. This must be adjudicated from Soong semantics or a build,
**not** guessed.

### 3.3 Module-type divergence (40 pairs) — mostly benign

`cc_prebuilt_library_shared` (ours) vs `cc_library_shared` (base) is the **legal** prebuilt-over-source
pattern: `camera.device@*-impl`, `libbundlewrapper`, `libbluetooth_audio_session`, etc.
One pair is *not* benign by inspection: `com.dsi.ant@1.0` — ours is a prebuilt library, the base defines
it as a `hidl_interface`.

### 3.4 Property-key collision (1, minor)

`ro.charger.enable_suspend` is set in both `product.prop` and `system.prop`.

### 3.5 Classes checked and found CLEAN

- install-path collisions across 866 modules / 968 install paths — **0**
- `PRODUCT_COPY_FILES` destination collisions — **0**
- duplicate module names *within* our own files — **0**
- `shared_libs` / `static_libs` / `header_libs` resolution (C61) — all 546 resolve
- ELF `DT_NEEDED` closure over 968 blobs (C60) — 0 executable-blocking

## 4. Durable rule this enables

The corpus makes the collision class checkable against the **whole base** rather than a guess at where
to look. That check belongs in the lint (proposed **C64**), reading the swept corpus, so a partition
collision can never again pass silently.

## 5. Reproduce

```bash
python3 roms/common/tools/sweep-manifest-sources.py --workers 12   # resumable
python3 roms/common/tools/deep-search-module.py --module <name>    # coverage-enforced verdicts
```
