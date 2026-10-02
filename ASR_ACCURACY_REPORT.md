# ASR accuracy recovery check — 2026-10-02

This check isolates speech recognition. Translation and speaker attribution were not changed.

## Reproducible probe

- Source: Google FLEURS Japanese (`ja_jp`) and US English (`en_us`) dev audio and references, CC BY 4.0. The fetch script verifies archive SHA-256 and reference TSV Git blob SHA-1 against repository metadata. Evaluation data and per-clip results stay in ignored `data/asr-eval/`.
- Fixed sample: first 80 dev clips in each language. Japanese metric is character error rate (NFKC, lowercase, whitespace/punctuation removed). English metric is word error rate (NFKC, lowercase, alphanumeric/apostrophe words). Lower is better.
- Runtime: faster-whisper CTranslate2 models already present in the app cache, NVIDIA RTX 3070 Ti Laptop GPU 8 GiB, float16. Each beam is warmed up, and beam order rotates for each clip. Reported time is mean inference call per clip, excluding model load.
- This is clean read speech, not a VTuber stream. It does not measure VAD misses, music, overlapping speech, hallucinations, or full end-to-end latency.

| Language | Model | Beam 1 error | Beam 3 error | Beam 5 error | Beam 1 / 3 / 5 mean call |
| --- | --- | ---: | ---: | ---: | --- |
| Japanese CER | base | 26.58% | 23.31% | 22.79% | 0.123 / 0.139 / 0.143 s |
| English WER | base | 11.79% | 10.15% | 10.34% | 0.073 / 0.083 / 0.087 s |
| Japanese CER | small | 13.78% | 12.36% | 11.81% | 0.256 / 0.287 / 0.310 s |
| English WER | small | 7.06% | 6.05% | 6.31% | 0.166 / 0.184 / 0.191 s |

The change uses beam 3 for Final results and keeps beam 1 for LIVE partials. Base therefore retains its download size and remains the Balanced default. The existing High Quality profile already offers small; its measured accuracy gain comes with roughly twice the inference time on this GPU and an extra model download. Beam 5 gave little further gain or regressed on English, so it was not selected.

For a separate 24-clip Japanese CPU/int8 spot check, small with beam 3 had 13.69% CER and a 2.15 s mean inference call. This sample differs from the 80-clip GPU run; the timing confirms that High Quality may feel slower without a GPU. It is not an end-to-end latency measure.

With the app's Auto language setting, base detected the expected language for all 80 Japanese and all 80 English clips at each beam width. CER/WER matched the corresponding fixed-language runs, while Auto added language-detection work (beam 3 mean call: 0.170 s Japanese, 0.100 s English). These clean clips do not establish Auto reliability on short, noisy live speech.

The production confidence cutoff of 0.35 was not changed. All 80 clean samples in each language were above it, but that does not calibrate the cutoff for noisy live streams. Prior live-session data showed many short Japanese utterances marked uncertain; retained transcript data cannot distinguish ASR mistakes from correctly uncertain audio because raw audio is not saved.

## Validation and limits

Run the probe with `python scripts/asr_eval_fetch.py ja_jp` / `en_us`, then `python scripts/asr_eval_fleurs.py --language ja --model base --limit 80` (repeat for English and small). The ASR regression test verifies the Final/partial decoding split. The full existing test suite passed: 463 tests.

An actual Chrome playback check is still required. The browser control service failed to initialize on this machine, and the execution policy rejected launching Chrome from the shell. No Chrome live quality or end-to-end latency result is claimed here. A manual capture helper is available at `scripts/probe_asr.py`; `--model-path` accepts a previously downloaded model snapshot and saves transcript/metrics only, not PCM.
