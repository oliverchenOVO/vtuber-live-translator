# Phase 10B：翻譯 Backend 比較與替換評估

> 本頁是 [英文原始報告](../../PHASE10B_REPORT.md)的繁體中文閱讀版。**推薦替換 Backend：無；即時翻譯門檻：FAIL；沒有本地候選通過門檻。** 這是開發機證據，不是 GA 結論。現有產品預設 Backend **未更換**，任何候選都沒有加入 Installer 或 Model Manager。

22 筆 Critical 來源中，新候選仍會加入原文沒有的事實；TranslateGemma 在日／英文真實 Chrome 長測的 p95 都超過 **2.5 秒**，650 筆的安全可用覆蓋率也尚未建立。模型能輸出文字、甚至很快輸出文字，**不等於譯文安全可用**。

## 候選模型、授權與環境

| 類型 | 候選 | 測試 runtime | 上游條款 | 本機 artifact |
| --- | --- | --- | --- | --- |
| 專用機器翻譯 | [MADLAD-400-3B-MT](https://huggingface.co/google/madlad400-3b-mt)／[Nextcloud int8 轉換](https://huggingface.co/Nextcloud-AI/madlad400-3b-mt-ct2-int8) | CTranslate2 CPU int8、4 threads | Apache 2.0 | Hugging Face revision `aa32bbdeba7880eff2096ec044cb155a340a9400`；`model.bin` 2,950,208,329 bytes |
| 翻譯導向 LLM | [TranslateGemma 4B](https://huggingface.co/google/translategemma-4b-it)／[Ollama 包](https://ollama.com/library/translategemma:4b) | Ollama CPU Q4_K_M、4 threads | [Gemma Terms](https://ai.google.dev/gemma/terms) | Ollama ID `c49d986b0764`；3,298,875,707 bytes |
| 現行基準 | [Qwen2.5 1.5B Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct) | 既有 Ollama CPU 與語意檢查、4 threads；不使用 7B 修正 | Apache 2.0 | Ollama ID `65ec06548149`；986,061,892 bytes |

[NLLB-200 distilled 600M](https://huggingface.co/facebook/nllb-200-distilled-600M) 模型卡標示 CC BY-NC 4.0，因此沒有作為發行候選；這是授權篩選，**不是品質評價**。

開發機是 Windows 11、Intel Core i9-12900H（14 cores／20 threads）、RAM **47.7 GiB**、RTX 3070 Ti Laptop GPU **8 GiB VRAM**。三候選均以 CPU 四 threads 測試，Ollama 候選之間會卸載模型。第一次資料列的最大值含 cold load；每列 p50／p95 分開記錄。`nvidia-smi` 是**全系統** GPU 使用量，不能歸給翻譯模型。

## 固定測試資料與判讀方法

[650 筆固定語料](../../tests/fixtures/translation_bakeoff_650.json)包含 **500 日文、150 英文**：Phase 10 撰寫的 400 筆（有相關句型變體）、Phase 9 真實 ASR 問題 100 日文＋50 英文、Phase 10 30 分鐘 Chrome 長測去重後 100 日文。後兩部分共 250 筆**沒有人工參考譯文**。[22 筆 Critical](../../tests/fixtures/translation_regression_critical.json)及[六筆詞庫測試](../../tests/fixtures/translation_bakeoff_glossary.json)另報。

固定類別包括閒聊 61、日期 27、遊戲 50、未完成句 36、多子句 12、名字 30、否定 48、數字 47、推測 48、VTuber 俚語 41、Phase 9 真實 ASR 問題 150、Phase 10 直播 ASR 100。撰寫的 400 筆有相關措辭變體，**不是 400 個不同說話人或直播**。

`scripts/phase10b_benchmark.py` 將每列結果立即寫到 ignored `data/phase10b/` JSONL，並可按 ID 續跑；紀錄模型輸出、呼叫延遲、CPU／RSS 採樣、全系統 VRAM、磁碟大小和自動旗標。三候選完成的逐列 JSONL 與摘要已固定在 `evidence/phase10b/`。650 筆的**輸出率不是安全可用覆蓋率**；語意及來源可評性仍需人工審查。產生的 `review_650.tsv` 人工欄位留白；一候選一列的 `review_650_long.tsv` 亦沒有完成真人審查。

## 離線比較結果

| Backend | 模型大小 | 有輸出／650 | 安全覆蓋率 | Critical 22 | 平均呼叫 | p50／p95 | 最大呼叫 | 峰值 RSS | CPU／模型 VRAM |
| --- | ---: | ---: | --- | --- | ---: | --- | ---: | ---: | --- |
| MADLAD int8 | 2.95 GB | 650／650 | **未建立** | 5 可接受、8 錯、9 幻覺 | 1.156 秒 | 0.953／2.219 秒 | 9.422 秒 | 3,062 MiB | 採樣平均約 385% 單核心；僅 CPU |
| TranslateGemma 4B | 3.30 GB | 650／650 | **未建立** | 4 正確、7 可接受、4 錯、7 幻覺 | 1.266 秒 | 1.141／2.219 秒 | 5.563 秒 | 4,440 MiB | 採樣平均約 492% 單核心；僅 CPU |
| Qwen2.5 1.5B | 0.99 GB | 143／650 | **未建立**，輸出率 22% | 2 可接受、20 無輸出 | 9.927 秒 | 11.562／15.609 秒 | 20.468 秒 | 1,539 MiB | 採樣平均約 377% 單核心；僅 CPU |

22 筆分類出自 **Codex 文字審查，不是獨立真人審查**；沒有這些列的原始音訊。八個來源看似 ASR 錯誤，但沒有音訊就不能標成確定的 `ASR_SOURCE_ERROR`。各模型輸出與文字標籤保存在 [Critical review JSON](../../PHASE10B_CRITICAL_REVIEW.json)。

**650 筆的幻覺、無根據擴寫、漏譯、實體／數字／否定／推測錯誤及安全覆蓋率尚未建立。** MADLAD 有 32 個、TranslateGemma 有 30 個「數字不一致」自動旗標；中文字數字可能造成誤報，不能當成確認錯誤。未翻譯的日文腳本旗標分別為 1 和 12，也要人工審查。Qwen 有 507 筆無輸出。沒有保存原始音訊，不能對疑似 ASR 問題作確定語音評分。

已足以否決安全門檻的例子：

- MADLAD：`Honestly, some days are harder than others, but I` → `說實話，有些日子比其他日子更難，但我做到了。`；替未完句加了「做到了」。
- MADLAD：`配信は6月8日です` → `遊戲將於6月8日釋出。`；把直播變成遊戲上市。
- TranslateGemma：`将来 もうすでにしたいことがあるよって人は` → `如果有人已經有明確的未來目標，請告訴我。`；新增要求。
- TranslateGemma：`テレビが特集して…え?ないないさ` → `電視臺並沒有播出…`；改變陳述／否定。
- TranslateGemma：`The volume is 50` → `這本書的頁數是 50 頁。`；憑空加入書和頁數。

## 詞庫、locale 與候選佇列策略

MADLAD 與 TranslateGemma 候選用臨時 marker 保護來源專有名詞，翻譯後以 OpenCC 正規化字形，再還原 zh-TW／zh-CN 指定寫法；marker 遺失或洩漏就拒絕。六筆詞庫個案中兩候選的 marker 均存活，但 `Noa and Pekora will play together` 仍被 MADLAD 譯成「將一起播放」、TranslateGemma 譯成「將一起執行／運行」。**名字正確不代表動詞或整句正確**。

既有有界佇列可觀察深度、最舊項目年齡、近期 Final throughput 及舊項目延後數。可選的 10 秒 stale 政策會把已在 SQLite 的舊 Final 延後，讓新語音追上，待補列仍 pending；**現行產品預設未啟用**。另一個可選 `FaithfulFirstBackend` 在 Natural 潤飾不過保守檢查時回退 Faithful；候選通過前也**未啟用**。

## 原時間戳 replay 與真實 Chrome 測試

TranslateGemma 將 Phase 10 的 **193 筆** Final ASR，按原本 **1,789.1 秒**跨度以 1 倍速 replay，包含排空總計 **1,790.5 秒（29 分 50.5 秒）**。193 筆都有文字輸出，沒有 pending；佇列峰值 **1**，近期最高 **16 Finals／分**，觀察到 Final 端到端延遲 **p50 0.859 秒／p95 1.578 秒**。[重播摘要](../../evidence/phase10b/replay-gemma-1x.summary.json)已固定。這只證明儲存 ASR 文字的時間容量，**不是語意安全或真實 Chrome 效能**。

### 日文：30 分 10.6 秒

Chrome 播放 [Pekora 直播存檔](https://www.youtube.com/watch?v=_tOGno89h7s)並走完整 Process Loopback、Faster-Whisper GPU、Sherpa、TranslateGemma CPU、SQLite。完成的 [Studio 截圖](../../evidence/phase10b/studio-gemma-ja.png)對應 **465 筆 Final ASR**：235 筆有譯文、230 筆明確為 `uncertain_source`。235／235 筆文字可評 Final 有輸出，**安全可用性未建立**。成功輸出的 Final 端到端延遲 **p50 2.235 秒／p95 5.063 秒**，未達 2.5 秒 p95 目標。佇列峰值 **3**，暫時尖峰時最舊項達 **25.5 秒**；361 次五秒採樣有 4 次超過 10 秒，完成時沒有持續積壓。

程式 RSS 峰值 **973.4 MiB**、Ollama **4,422.3 MiB**；採樣平均 CPU 分別 **97.3%／137.4% 單核心**。全系統 GPU 記憶體由 **3,554** 到最高 **4,119 MiB**，不能歸給翻譯模型。完整[摘要](../../evidence/phase10b/live-gemma-ja.summary.json)與資源採樣已提交，SQLite 逐字稿仍在 ignored 本機資料。文字審查發現 `あんま分かって分かんないはどうしっ` → `我不太明白，請您再解釋一下。`，加入原 ASR 文字沒有的請求；未保留音訊，不能回頭確認語音來源。

### 英文：15 分 6.6 秒

Chrome 播放 [Hakos Baelz 直播存檔](https://www.youtube.com/watch?v=nJQzIBTsiKA)，使用同一真實管線。完成的 [Studio 截圖](../../evidence/phase10b/studio-gemma-en.png)有 **186 筆 Final**：140 筆有譯文、46 筆 `uncertain_source`；140／140 筆文字可評 Final 有輸出，**安全可用性未建立**。成功 Final 延遲 **p50 2.094 秒／p95 5.390 秒**，同樣超過目標。佇列峰值 **3**，最舊項 **7.688 秒**；181 次五秒採樣只有 1 次超過 5 秒，沒有超過 10 秒。

程式 RSS 峰值 **978.2 MiB**、Ollama **4,399.8 MiB**；採樣平均 CPU 分別 **84.2%／133.8% 單核心**。全系統 GPU 記憶體從 **3,531** 到最高 **4,149 MiB**，不是模型專屬 VRAM。完整[摘要](../../evidence/phase10b/live-gemma-en.summary.json)已提交。文字審查中 `Take a T9.` 被譯成 `請乘坐9號線。`，增加未確認的交通情境；原始音訊沒有保存，無法事後核對語音。

## 尚未完成的門檻

- 對 650 筆全部類別做獨立錯誤稽核；目前固定的 Codex 審查只涵蓋 22 筆 Critical。
- 由獨立真人審查來源是否可評及譯文品質。
- 只有在安全與真實即時門檻都通過後，才更換產品預設 Backend。

Critical 結果與兩段真實直播的 p95 都阻止 PASS。這階段沒有開始 Phase 11、GA、Installer、Overlay、History 或 Export 修改。開發機完整既有與新增回歸測試為 **462 項通過**。

## 重現與證據邊界

從 repository 根目錄安裝選用 benchmark tokenizer：`python -m pip install -e '.[dev,bakeoff]'`。650 筆 fixture 已提交，可不依賴 ignored Session 資料庫執行固定比較；`phase10b_build_corpus.py` 若要重建 fixture，則仍需要 ignored 原始資料。

MADLAD 測試固定前述 Hugging Face revision 及 `model.bin`、vocabulary、SentencePiece、config 與 tokenizer 檔。這台 Windows 的 SentencePiece／CTranslate2 原生庫無法開啟含中文字的路徑，因此比較測試用 `C:\vlt10b-madlad` NTFS junction 指向 ignored 模型目錄，並設定 `VLT_PHASE10B_MADLAD_DIR`；**這只是開發機 workaround，不是 Installer 解法**。

TranslateGemma 用 `ollama pull translategemma:4b`；基準保留 `qwen2.5:1.5b`。計時時只載入一個 Ollama 候選；第一次 Qwen Critical 嘗試因兩模型同時常駐而逾時，其 `*.contention.jsonl` 留在本機但排除於乾淨比較，重跑前用 `ollama stop <other model>`。

`scripts/phase10b_benchmark.py --backend madlad --set corpus`（亦可改 `gemma`／`qwen`）跑固定語料；`critical`／`glossary` 切換資料集，`--target zh-CN` 測簡體。`phase10b_review_sheet.py` 產生仍待人工填寫的比較 TSV；`phase10b_review_critical.py` 重建 Codex 文字標籤。`phase10b_replay.py --backend gemma --speed 1` 用既存 ASR Final 原時間跨度重播，**不含音訊擷取或 ASR**；`phase10b_live_soak.py --backend gemma --language ja --minutes 30`／`en --minutes 15` 則要求 Chrome 正在播放真實語音，使用完整現有音訊、ASR、Speaker、Session 管線。除 1 倍速外的 replay 只供診斷，不能算真實即時門檻。兩支腳本都不把 Gemma 升為產品預設。
