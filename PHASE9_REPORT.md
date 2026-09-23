# Phase 9 GA validation record

Status: **GA READY: NO**. This is a release gate record, not a claim of completed independent acceptance. No public release or `v1.0.0` tag has been pushed.

## Release gates

| Severity | Open item | Evidence / next acceptance |
| --- | --- | --- |
| BLOCKER | Independent Windows 11 install and full first-use journey | No second PC or clean VM was available to this run. The current development PC has Python, project source, model cache and tools. Run Setup on a machine without those prerequisites and complete Install → Download → Restart → Chrome → Session → ASR → Translation → Overlay → Export → Restart → History. Do not use development tools to repair dependencies. |
| BLOCKER | Physical gaming and Overlay acceptance | Native desktop input control was unavailable in this run. A 30–60 minute game + Chrome + Translator test, real pointer click-through/drag/resize/lock, alt-tab and fullscreen/borderless behavior remain unverified. Two monitors are currently attached, but move/restart/unplug was not physically checked. Phase 8 Qt flag and geometry tests remain **simulated only**. |
| BLOCKER | Source/category matrix and independent usability | Phase 9 has not completed 15–30 minutes each of Japanese solo, 2-person, 3–4-person and English talk on the clean host, nor Chrome Twitch, Edge, Firefox or VLC audio trials. No uninstructed outside participant has tested the installer. Formal packaged-build screenshots are pending. |
| CRITICAL | Final translation can contain invented facts or prompt text | A fixed-seed assistant review of 100 Japanese and 50 English translated Final segments from the Phase 8 local run found at least 22 clearly expanded/invented-content examples, including short source phrases rendered as unrelated paragraphs. This is a conservative count, not a measured error rate. A narrow guard now rejects explicit prompt leakage, an unchanged Japanese source and grossly overlong output; eight of the 150 saved examples are rejected by the new guard. Semantic mistakes remain, so this is not a full fix. Independent human source/audio checking is still required. |
| MAJOR | Translation latency/quality under dense speech | Phase 8 measured 38.2 s mean / 63.3 s P95 Final translation delay in Gaming with extra observation load; original speech persists as `translation_pending`. |
| MAJOR | Active memory trend | Phase 8 measured +5.64 MiB/min Private Memory overall and +1.25 MiB/min in its second hour; 20 stop cycles finished 153 MiB above first stop. Long-duration stability remains unproven. |
| MAJOR | Speaker accuracy and Unknown frequency | In the existing local long run, 1,173 of 1,456 speech segments were `unknown`; 138/63/62 were assigned to speakers 001/002/003. This is conservative display, not proof of accurate multi-speaker assignment. All 19 overlap events stayed `unknown_overlap` or `overlapping_speech`. |

The release gate counts above are **BLOCKER 3, CRITICAL 1, MAJOR 3**. The first three BLOCKERs are missing required acceptance evidence, not claims of an observed application crash. The quality issue affects a core output and has not been made safe by the narrow guard alone.

## Executed on the development PC

- Windows build 26200, 47.7 GiB RAM, two active screens (`XG27UCG` 2560×1440 and `DISPLAY1` 2048×1280). This PC is **not** a clean acceptance machine. Local C: had about 29.6 GiB free; Hyper-V feature queries required elevation, and no VM image or available VM command was found. This does not prove that a clean VM cannot be created later.
- Phase 8's real packaged local run remains evidence for Chrome/YouTube: Japanese solo ~31 min, Japanese group ~39 min, English talk ~51 min, plus silence. It used an existing Ollama runtime and cannot substitute for clean installation. It did not separately prove 2-person and 3–4-person categories.
- For the Phase 9 translation sample, selected 100 Japanese and 50 English translated Final segments from the stored Phase 8 SQLite corpus with seed `20260924`; transcript sample stayed under ignored `data/phase9_review.json`. The reviewer compared stored ASR text with stored translation, **not source audio**, so ASR accuracy is outside this spot check. This assistant review is not an external human study.
- New output guard rejects obvious instruction leakage and gross expansion while leaving the original segment pending for retry. 390 automated tests passed after the change, including five new output-guard cases and the retained Phase 1–8 suite.

## Source compatibility

| Source | Classification | Scope |
| --- | --- | --- |
| Chrome + YouTube | Works with limitations | Phase 8 development-PC process capture and real media; not independent Phase 9 acceptance. |
| Chrome + Twitch | Not verified | Phase 9 test pending. |
| Chrome + Bilibili / other HTML5 | Not verified | Optional test pending. |
| Edge | Not verified | Installed on the development PC; no completed audio acceptance. |
| Firefox | Not verified | No installed executable found at standard paths; no audio acceptance. |
| VLC | Not verified | No installed executable found at standard paths; no audio acceptance. |
| Discord | Not verified | Shortcut present; no appropriate audio trial completed. |

The capture API is Windows Process Loopback and does not depend on website APIs. This architecture claim is separate from the compatibility evidence above.

## Privacy and network audit

- Source review shows bounded in-memory process audio, local SQLite/JSON transcripts and local speaker embeddings. The Phase 8 local run did not save PCM. The diagnostic ZIP implementation serializes allowlisted enum settings and numeric metrics; it does not add transcript, raw audio, API key, embedding or raw log files.
- Normal local translation talks to `127.0.0.1:11434`; model setup fetches pinned Ollama from GitHub, ASR model files through Hugging Face, and diarization models from sherpa-onnx GitHub releases. Ollama model pull uses localhost, whose runtime contacts its model registry. Update checks are disabled by default because `VLT_RELEASES_API` is empty; no telemetry endpoint was found in app source.
- This is a **source-level audit**, not a packet capture from the final clean installation. Perform a live connection audit before GA. The privacy statement must continue to distinguish one-time model downloads from local Session inference.

## Packaging and signing

- Current RC Setup is unsigned. No usable code-signing certificate was found in the current user's Personal store; do not issue a test signature or claim signed release. Windows may show Unknown publisher / SmartScreen.
- `build_release.ps1` signs the owned main EXE and installer when `SIGNING_CERT` is supplied, checks PowerShell Authenticode status and now also requires `signtool verify /pa /v`. There is no separate owned native helper EXE/DLL in the package; bundled third-party DLLs are not re-signed.
- Build source commit `0c7d2449b603c87481e72c059a93995192a63896` was clean before `scripts/build_release.ps1`; the script ran all 390 tests and built the EXE and Installer successfully. The unsigned Phase 9 candidate was renamed to `VtuberLiveTranslator-1.0.0-rc-phase9-Setup.exe` to distinguish it from the earlier RC. It is **not** a GA artifact. The original Phase 8 RC Setup was 105,881,875 bytes with SHA-256 `1e9fd97697ea7d5b65e0a39ed2f1345f4c588c9cb36b9436651cf346380c942d`.
- Candidate Setup: 105,885,046 bytes; SHA-256 `f06d32ad5ea953e42e1d1a9d77cb9a9e06f971558b1e1e9fef43c775c4679e85`. Candidate main EXE: SHA-256 `b908585b92247034d2fbab0ce9215a3f2a9bf2ba03fdbf21f363b378b2162cc8`. Every entry in the regenerated `release/SHA256SUMS.txt` was read back and verified against its file. The portable folder is 439,629,523 bytes; it is a build output, not an accepted portable distribution.
- Microsoft Defender custom scan of the **exact renamed candidate Setup** completed on 2026-09-24 03:21:18 +08:00 (Operational events 1000/1001, same scan ID) with zero recorded detections before or after. Defender reported AntivirusEnabled=true and RealTimeProtectionEnabled=false on this PC; that setting was not changed. The scan is one-engine local evidence, not a guarantee against all antivirus detections.
- Approximate first-run download is 2.45 GB; installation plus required models is ~3.3 GB after cache cleanup or ~4.7 GB with cache. These are Phase 8 estimates, not measurements on a clean Phase 9 host.

## GA artifact rule

Do not relabel the RC as GA, create a final GA installer, reuse an old checksum, push a tag, publish a GitHub Release or change repository visibility while the gates above remain open. After acceptance, build all artifacts from the chosen clean commit, scan the exact installer, calculate SHA-256 from that exact file and propose that commit as the `v1.0.0` tag target for user confirmation.
