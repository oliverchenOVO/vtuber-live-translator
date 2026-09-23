# Vtuber Live Translator 1.0.0 — Release Candidate

Status: **Release Candidate; GA withheld** — 2026-09-24. Phase 8 approval was limited to its executed
local scope. Phase 9 found missing independent acceptance and a critical translation-quality issue.
See PHASE9_REPORT.md for the current release gates. Do not distribute this candidate as 1.0.0 GA.

## Features

Capture audio from one Windows process and its children, transcribe Japanese/English locally,
translate into Traditional/Simplified Chinese, show subtitles in Studio/Overlay, and preserve
Session history in SQLite/JSON with Markdown/SRT/VTT exports. Unknown speaker corrections
can be made with one-click buttons or a time range. Identity confirmation is manual.

## Requirements and installation

64-bit Windows build 20348 or newer (Windows 11 recommended). Older Windows builds cannot
use Application Process Loopback; the app does not silently capture the entire system.
No Python, Git, developer tools or Ollama CLI installation is required for end users.
First setup downloads approximately 2.45 GB; reserve at least 7 GB disk space.
Installed size is approximately 3.3 GB after clearing download cache, or 4.7 GB with cache.
Models and local runtime are managed in First Run / Settings; model setup needs internet access.

## Privacy

Audio is processed locally. Raw audio is not saved by default. Transcripts are stored locally.
Model downloads contact their distribution servers; translation uses a local Ollama HTTP endpoint.
Diagnostics contain app/Windows versions, numeric hardware summary, allowlisted settings,
model identifiers and parsed numeric recent log metrics. No raw logs, full transcripts, audio,
credentials, paths, person identities or voice embeddings are included.

## Known limitations

- Speaker diarization may mark uncertain speech as Unknown; overlapping speakers may not be separable.
- Translation and recognition are fallible. Factual guards are heuristics, not a semantic guarantee.
- Dense conversation can fill the bounded translation queue in Gaming mode. The long test measured
  Final translation mean 38.2 s / P95 63.3 s and 14.48 s of dropped older ASR audio under extra load.
  Untranslated originals remain durable and can be retried.
- Memory remains a tracked MAJOR: active Private Memory slope +5.64 MiB/min overall, +1.25 in
  the second hour; 20 Start/Stop cycles ended about 153 MiB above the first stop. Idle slope was
  -0.22 MiB/min. Queues/live history are bounded, but arbitrary-duration memory stability is unproven.
- Quality remains a MAJOR: small models can mistranslate, misdetect short utterances, or occasionally
  include instruction-like text in output. Passing factual guards is not a correctness guarantee.
- Phase 9 review found multiple clear invented-content translations in a 100 Japanese / 50 English
  sample. A narrow guard now rejects explicit prompt leakage, unchanged Japanese source text and
  grossly overlong output, retaining the original as translation pending. Semantic drift remains
  a CRITICAL GA gate; this guard is not a complete quality fix.
- Gaming/Balanced use 1.5B only; optional 7B correction requires High Quality and explicit opt-in,
  approximately 5 GB additional RAM, and an already installed 7B model. It may delay subtitles.
- This RC is unsigned unless the builder provides SIGNING_CERT. Unknown publisher or SmartScreen
  may appear. No antivirus settings should be disabled.
- An independent clean Windows VM/second-PC end-to-end run has not yet been verified.
- Chrome/YouTube process-tree capture is tested. Edge, Firefox, Discord, VLC, Twitch and a
  deliberate Chrome renderer restart do not have completed audio compatibility acceptance here.
- Overlay keyboard controls, Qt input flags and saved geometry are tested; physical mouse
  passthrough, dragging and resizing have not completed a full manual audit in this environment.
- Physical multi-monitor unplugging has not yet been verified.
- Warm model caching is deferred; models load when a Session starts and are released on stop.
- No public release has been published. Clean-machine and physical interaction gaps above remain unverified.

## Signing and reproducibility

Run scripts/build_release.ps1. SIGNING_CERT optionally identifies a code-sign certificate
thumbprint in Cert:\CurrentUser\My with an accessible private key. The script signs the app
before installer creation, signs the installer, verifies both, and calculates checksums afterwards.
Without that environment variable it creates an unsigned RC. A failed requested signature fails the build.

## Validation

385 automated tests passed (110 retained + 275 Phase 8), plus 9 packaged Qt checks.
The installed app completed 153 minutes including more than 120 minutes of real Japanese/English
media and about 32 minutes of silence. Final-artifact smoke, 20 Start/Stop cycles, 5 forced kills
with recovery, normal runtime-child cleanup and uninstall/data retention passed.

The continuous soak used an earlier build; final rebuild differences are owned runtime shutdown
and two display-status corrections. Capture/inference/QML are unchanged, and the final artifact
passed the targeted checks above. The report lists both artifact hashes explicitly.

The local long run used an existing Ollama 0.20.3 service; managed Ollama 0.34.2 download, repair
and shutdown were checked separately. No independent clean-PC result is implied.

Final EXE and installer passed a Windows Defender custom scan with no detections. Both are unsigned.
See PHASE8_REPORT.md for sample tables, slopes, latency definitions, preset differences and evidence.
No unexecuted test is marked passed.
