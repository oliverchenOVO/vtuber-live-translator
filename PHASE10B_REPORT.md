# Phase 10B — Translation Backend Bake-off

**RECOMMENDED TRANSLATION BACKEND: NONE**

**TRANSLATION REALTIME GATE: FAIL**

**NO LOCAL BACKEND MET GATE**

The new candidates have unsupported additions in the 22 Critical sources;
TranslateGemma's real Chrome p95 exceeded 2.5s for both languages, and safely
usable 650-row coverage is not established. This is development-PC evidence,
not a GA release decision. The existing
product default has not been changed. No test candidate is bundled in the
installer or added to Model Manager.

## Candidate selection and rights

| Class | Candidate | Runtime | Upstream terms | Local artifact |
|---|---|---|---|---|
| Dedicated MT | [MADLAD-400-3B-MT](https://huggingface.co/google/madlad400-3b-mt), [Nextcloud CTranslate2 int8 conversion](https://huggingface.co/Nextcloud-AI/madlad400-3b-mt-ct2-int8) | CTranslate2 CPU int8, four threads | Apache 2.0 | Hugging Face revision `aa32bbdeba7880eff2096ec044cb155a340a9400`; `model.bin` 2,950,208,329 bytes |
| Translation-oriented LLM | [TranslateGemma 4B](https://huggingface.co/google/translategemma-4b-it), [Ollama package](https://ollama.com/library/translategemma:4b) | Ollama CPU Q4_K_M, four threads | [Gemma Terms](https://ai.google.dev/gemma/terms) | Ollama ID `c49d986b0764`; 3,298,875,707 bytes |
| Existing baseline | [Qwen2.5 1.5B Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct) | Existing Ollama CPU + existing semantic verifier, four threads; no 7B repair | Apache 2.0 | Ollama ID `65ec06548149`; 986,061,892 bytes |

[NLLB-200 distilled 600M](https://huggingface.co/facebook/nllb-200-distilled-600M)
was not a distribution candidate because its model card specifies CC BY-NC 4.0.
This is a licensing screen, not a quality judgement.

## Hardware and method

Development PC: Intel Core i9-12900H (14 cores, 20 threads), 47.7 GiB RAM,
NVIDIA GeForce RTX 3070 Ti Laptop GPU (8 GiB VRAM), Windows 11. All three
candidates ran on CPU with four configured threads so GPU availability did not
give one candidate an unfair advantage. `nvidia-smi` usage is system-wide, not
attributable to the translation process. Cold model load is included in the
first-row maximum; per-row p50 and p95 are recorded separately. Models were
unloaded between Ollama candidate runs.

The fixed [650-row corpus](tests/fixtures/translation_bakeoff_650.json) has
500 Japanese and 150 English rows. It combines the Phase 10 authored 400
(including related variants), Phase 9's 100 Japanese and 50 English real ASR
problem rows, and 100 de-duplicated Japanese rows from the Phase 10 30-minute
Chrome soak. The latter 250 have no human reference translation. The
[22-row Critical set](tests/fixtures/translation_regression_critical.json) is
reported separately. The [six-row glossary set](tests/fixtures/translation_bakeoff_glossary.json)
tests both source languages and both Chinese locales.
The frozen categories include casual (61), dates (27), gaming (50), incomplete
(36), multi-clause (12), names (30), negatives (48), numbers (47), uncertainty
(48), VTuber slang (41), Phase 9 real ASR problems (150), and Phase 10 live ASR
(100). The authored 400 contain related phrasing variants, not 400 independent
speakers or streams.

`scripts/phase10b_benchmark.py` writes each result immediately to ignored
`data/phase10b/` JSONL and resumes by ID. It records output, model-call latency,
CPU/RSS samples, system-wide VRAM samples, disk size, and automated flags. The
completed, frozen [MADLAD](evidence/phase10b/madlad-corpus-zh-TW.jsonl),
[TranslateGemma](evidence/phase10b/gemma-corpus-zh-TW.jsonl), and
[Qwen](evidence/phase10b/qwen-corpus-zh-TW.jsonl) per-row results and their
summary JSON files are committed under `evidence/phase10b/`. The
automated output rate is **not** safely usable coverage. Semantic quality and
source eligibility require human review. The generated `review_650.tsv` has
blank human-review columns. `review_650_long.tsv` has one row per candidate
and explicit eligibility, safe usability, hallucination, unsupported expansion,
omission, entity, number, negation, modality, and untranslated-output columns.
Neither file is a completed review.

## Comparison

| Backend | Model size | Output / 650 | Safe coverage | Critical 22 | Mean call | Call p50 | Call p95 | Max call | Peak RSS | CPU | Model VRAM |
|---|---:|---:|---|---|---:|---:|---:|---:|---:|---|---|
| MADLAD int8 | 2.95 GB | 650 / 650 | Not established | 5 acceptable, 8 wrong, 9 hallucinated | 1.156 s | 0.953 s | 2.219 s | 9.422 s | 3,062 MiB | Mean sampled 385% of one core | CPU only |
| TranslateGemma 4B | 3.30 GB | 650 / 650 | Not established | 4 correct, 7 acceptable, 4 wrong, 7 hallucinated | 1.266 s | 1.141 s | 2.219 s | 5.563 s | 4,440 MiB | Mean sampled 492% of one core | CPU only |
| Qwen2.5 1.5B | 0.99 GB | 143 / 650 | Not established; output rate 22% | 2 acceptable, 20 no output | 9.927 s | 11.562 s | 15.609 s | 20.468 s | 1,539 MiB | Mean sampled 377% of one core | CPU only |

| Backend | Hallucinations / 650 | Unsupported expansions | Omissions | Entity errors | Number errors | Negation errors | Modality errors | Untranslated output |
|---|---|---|---|---|---|---|---|---|
| MADLAD int8 | Not reviewed; 9/22 Critical | Not reviewed | Not reviewed | Not reviewed | 32 automated digit flags; unconfirmed | Not reviewed | Not reviewed | 1 Japanese-script flag; unconfirmed |
| TranslateGemma 4B | Not reviewed; 7/22 Critical | Not reviewed | Not reviewed | Not reviewed | 30 automated digit flags; unconfirmed | Not reviewed | Not reviewed | 12 Japanese-script flags; unconfirmed |
| Qwen2.5 1.5B | Not reviewed; 0/22 Critical with 20 no output | Not reviewed | Not reviewed | Not reviewed | 10 automated digit flags; unconfirmed | Not reviewed | Not reviewed | 507 no output; zero Japanese-script flags on published text |

The 22 labels are Codex text-only review, **not independent human review**.
Original speech audio is unavailable for those rows. Eight sources look like
possible ASR errors, but none are marked confirmed `ASR_SOURCE_ERROR` without
audio. A model's unsupported additions relative to the saved ASR text remain
visible in the review. The frozen [Critical output and text-only labels](PHASE10B_CRITICAL_REVIEW.json)
contain every candidate output and label.

The requested 650-row semantic error counts are **not established**:
hallucinations, unsupported expansions, omissions, entity errors, number
errors, negation errors, modality errors, and safely usable coverage require
source-aware review. Automated digit mismatches were 32 for MADLAD and 30 for
TranslateGemma, but those are review flags, not confirmed number errors;
Chinese numerals can produce false positives. Untranslated Japanese-script
flags were 1 and 12 respectively, also requiring review. No source audio was
saved, so suspected ASR errors cannot be conclusively graded against speech.

Examples already falsifying the safety gate:

- MADLAD: `Honestly, some days are harder than others, but I` →
  `說實話，有些日子比其他日子更難，但我做到了。` (invented completion).
- MADLAD: `配信は6月8日です` → `遊戲將於6月8日釋出。` (stream became game release).
- TranslateGemma: `将来 もうすでにしたいことがあるよって人は` →
  `如果有人已經有明確的未來目標，請告訴我。` (invented request).
- TranslateGemma: `テレビが特集して…え?ないないさ` →
  `電視臺並沒有播出…` (changed assertion/negation).
- TranslateGemma: `The volume is 50` → `這本書的頁數是 50 頁。`
  (invented book/page meaning from a clean English source).

## Glossary and locale

The MADLAD and TranslateGemma candidates protect source terms with temporary
markers, translate, normalize script with OpenCC, then restore exact locale
spellings. Missing or leaked markers fail closed. This is a candidate mechanism,
not a claim that named entities or whole-sentence meaning are solved. In the
six-case MADLAD and TranslateGemma probes, all markers survived in zh-TW and
zh-CN, but `Noa and Pekora will play together` became `將一起播放` in MADLAD and
`將一起執行／運行` in TranslateGemma: names were correct while the action was wrong.

## Queue and fallback work

The existing bounded queue exposes depth, oldest age, recent Final throughput,
and stale deferral count. An optional 10-second live stale policy defers old
Final requests already durable in SQLite so new speech can catch up; deferred
rows remain pending for later retry. It is not enabled in the current product
default. A separate optional `FaithfulFirstBackend` returns the Faithful text
if Natural polishing fails a conservative deterministic check. It is also not
enabled until a candidate qualifies.

## Original-timestamp replay

The provisional TranslateGemma candidate replayed all **193** Phase 10 Final
ASR records over their original **1,789.1-second** timestamp span. Total run
time, including final drain, was **1,790.5 seconds** (29m 50.5s). All 193
requests returned text; none remained pending. The bounded queue peaked at
**one** item, recent output peaked at **16 Finals/min**, and observed
end-to-end Final latency was **0.859s p50 / 1.578s p95**. The replay text
and [metrics](evidence/phase10b/replay-gemma-1x.summary.json) are frozen in
`evidence/phase10b/`. This shows timing capacity on saved ASR text, **not**
semantic safety or real Chrome performance.

## Real Chrome sessions

**Japanese, 30m 10.6s:** Chrome played [Pekora's archived talk stream](https://www.youtube.com/watch?v=_tOGno89h7s)
from 10:00, with the existing Process Loopback, Faster-Whisper GPU, Sherpa
diarization, TranslateGemma CPU, and SQLite Session. The real Studio view is
[captured here](evidence/phase10b/studio-gemma-ja.png). The Session completed
with **465 Final ASR segments**: **235** translated and **230** clearly
`uncertain_source`. Thus 235/235 text-eligible Finals received output, but
safe usability is not established. Successful Final end-to-end latency was
**2.235s p50 / 5.063s p95**, exceeding the 2.5s p95 target. The queue peaked
at **3** items, and its oldest observed item reached **25.5s** during a
transient spike; 4 of 361 five-second samples exceeded 10s. No continuing
backlog remained at finish. Peak app RSS **973.4 MiB**, peak Ollama RSS
**4,422.3 MiB**, mean app CPU **97.3% of one core**, mean Ollama CPU from
samples **137.4% of one core**. System-wide GPU memory was **3,554 MiB** at
start and peaked at **4,119 MiB**; it is not model-attributable. The full
[summary](evidence/phase10b/live-gemma-ja.summary.json) and resource samples
are committed; the SQLite transcript remains in ignored local test data.
Text-only inspection found unsupported completion on a broken ASR source:
`あんま分かって分かんないはどうしっ` became
`我不太明白，請您再解釋一下。` The request to explain again is absent from the
saved ASR text. Original audio was not retained, so the source cannot be
graded against speech.

**English, 15m 6.6s:** Chrome played [Hakos Baelz's archived talk stream](https://www.youtube.com/watch?v=nJQzIBTsiKA)
from 10:00 through the same actual capture, ASR, diarization, translation,
and SQLite path. The completed real Studio view is
[captured here](evidence/phase10b/studio-gemma-en.png). The Session has
**186 Finals**: **140** translated and **46** `uncertain_source`; 140/140
text-eligible Finals received output, with safe usability unestablished.
Successful Final latency was **2.094s p50 / 5.390s p95**, again exceeding
the 2.5s target. Queue peak **3**, oldest observed item **7.688s**; one of
181 five-second samples exceeded 5s and none exceeded 10s. Peak app RSS
**978.2 MiB**, peak Ollama RSS **4,399.8 MiB**, mean app CPU **84.2% of one
core**, mean Ollama CPU **133.8% of one core**. System-wide GPU memory rose
from **3,531** to at most **4,149 MiB**; this is not translation model VRAM.
See the frozen [summary](evidence/phase10b/live-gemma-en.summary.json) and
resource samples. In text-only review, `Take a T9.` became `請乘坐9號線。`,
adding an unconfirmed transit context. Its spoken source cannot be checked
because the application correctly did not save raw audio.

## Outstanding gates

- Independent category error audit of all 650 rows. The frozen Codex review is
  limited to the 22 Critical sources.
- Independent human review of source eligibility and translation quality.
- Default-backend replacement only after safety and real-time gates pass.

The Critical results and both live p95 values prevent a PASS. No Phase 11, GA,
Installer, Overlay, History, or Export work was started.

Full existing and new regression suite: **462 passed** on this Windows 11
development PC (`.venv/Scripts/python.exe -m pytest -q`).

## Reproduction and evidence boundaries

From the repository root, use the project's Python environment and install the
optional benchmark tokenizer: `python -m pip install -e '.[dev,bakeoff]'`.
The 650-row fixture is committed, so the benchmark does not need the ignored
Phase 9/10 Session database. `phase10b_build_corpus.py` documents how this
fixture was assembled on the development PC; it needs the ignored source data
if run again. The committed fixture is the fixed comparison input.

The MADLAD CTranslate2 conversion was downloaded from the pinned Hugging Face
revision above with `model.bin`, `shared_vocabulary.json`, `spiece.model`,
`config.json`, `generation_config.json`, `added_tokens.json`,
`special_tokens_map.json`, `tokenizer.json`, and `tokenizer_config.json`.
On this Windows checkout, the native SentencePiece/CTranslate2 library could
not open a path containing Chinese characters. The local benchmark used an
NTFS junction at `C:\vlt10b-madlad` pointing to the ignored model directory,
and `VLT_PHASE10B_MADLAD_DIR=C:\vlt10b-madlad`. The failed path-load probes
are retained locally under `data/phase10b/*load-failure*`. This path issue
would need an installer-safe solution before MADLAD could ship; the junction
is only a development-PC comparison workaround.

Run `ollama pull translategemma:4b` for the translation-oriented LLM and keep
the existing `qwen2.5:1.5b` for the baseline. Only one Ollama candidate should
be loaded during a timed run. The first Qwen Critical attempt had both models
resident and timed out; its `*.contention.jsonl` is retained but excluded from
the clean comparison. `ollama stop <other model>` was used before rerunning.

`python scripts/phase10b_benchmark.py --backend madlad --set corpus` and the
same command with `gemma` or `qwen` run the fixed 650 rows. Replace `corpus`
with `critical` or `glossary`; use `--target zh-CN` for Simplified Chinese.
The runner's `data/phase10b/` directory remains ignored; the three completed
corpus JSONL files and summaries have frozen copies under `evidence/phase10b/`.
Other local run files are not packaged or committed. `phase10b_review_sheet.py`
regenerates the 650-row comparison TSV; its review columns are intentionally
blank. `phase10b_review_critical.py` regenerates the Codex text-only labels.

`phase10b_replay.py --backend gemma --speed 1` feeds previously saved ASR
Finals to the bounded translation worker over their actual roughly 30-minute
timestamp span, without audio capture or ASR. `phase10b_live_soak.py --backend
gemma --language ja --minutes 30` and the corresponding `en --minutes 15`
command require Chrome to be playing a real spoken source. The live runs use
the existing Process Loopback, ASR, diarization, Session and SQLite components.
Neither script promotes Gemma to the product default. Any replay speed other
than `1` is diagnostic and does not satisfy the real-time replay gate.
