# Changelog

## 1.0.0 — Release Candidate hardening

- Windows process-tree audio capture, local streaming transcription and Chinese translation.
- Session history, conservative speaker grouping and manual identity correction.
- Durable SQLite/JSON records and Markdown/SRT/VTT exports.
- Managed model installation, per-user installer, tray and hardware presets.
- Fixed long-sentence translation bypassing the Gaming/Balanced 7B restriction.
- Preserved interrupted model downloads; added model verification and repair.
- Added quick Unknown speaker assignment and time-range assignment.
- Added startup stage feedback, cancellation, overlay edit/lock and keyboard focus.
- Added privacy-preserving diagnostics and optional Windows certificate-store signing.
- Strengthened JSON flush/fsync and recovery from malformed JSON using SQLite.
- Released Process Loopback COM completion references and stopped ASR model weights/tasks.
- Prevented Windows oneMKL per-thread buffers accumulating across repeated model reloads.
- Bounded Studio live history and transcript replay caches; added numeric latency/resource diagnostics.
- Corrected numeric token matching and Japanese uncertainty/negation checks.
- Fixed window close when minimizing to the tray is disabled.
- Terminate owned Ollama runner children when closing the managed runtime.

Release approval and measurements are documented in RELEASE_NOTES_1.0.0.md.
