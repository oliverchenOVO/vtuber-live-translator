# Vtuber Live Translator

Windows 即時翻譯桌面程式，開發中。此版本是 **Phase 6**：保留 Windows 指定程式擷取、串流辨識、本機即時中譯與 Speaker 分離，加入可恢復的 Session History、Speaker 人工修正、搜尋與 Markdown/SRT/VTT 最終輸出。**目前尚無正式 EXE**。

## 開發版啟動

需要 Python 3.12+。在 PowerShell 執行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
ollama pull qwen2.5:1.5b
ollama pull qwen2.5:7b
.\.venv\Scripts\python.exe -m vlt.app
```

測試：

```powershell
.\.venv\Scripts\python.exe -m pytest
```

使用者資料預設保存在 Windows 的 `%LOCALAPPDATA%\VtuberLiveTranslator`；可在開發或測試時用 `VLT_DATA_DIR` 改變位置。Session 使用 UUID 作為身份，SQLite 記錄路徑和狀態，個別資料夾保存 `session.json` 與 `transcript.json`。未先建立 Session 時，按「開始監聽」會自動建立；中斷後從 History 選回原 Session 可在同一資料夾繼續。

## 音訊監聽

在 LIVE 的 **APPLICATION AUDIO** 選擇程式並按「開始監聽」。清單顯示程序名稱、根 PID 和音訊輸出狀態，每 2.5 秒更新。來源消失後可重新偵測再連接。只監聽選取程序及其子程序；不會儲存擷取的原始音訊。

使用 Windows `ActivateAudioInterfaceAsync`、`AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK` 與 `PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE`。需要 Windows Build **20348 或更新**。較舊 Windows 10 不具備此正式 API，本版本會顯示清楚的版本錯誤；不會暗中退回整機 Stereo Mix。

格式流程：Windows Audio Engine 將程序音訊轉為 **44.1 kHz、stereo、signed 16-bit PCM**，接著在記憶體中 downmix 成 mono，以 libsoxr 連續重採樣到 **16 kHz**，輸出 **mono、signed 16-bit PCM**。原有 ring buffer 上限為 5 秒（160,000 bytes）；不會隨直播時間增長。

## 串流逐字稿

在右側「來源語言」選擇自動偵測、日文或英文，再開始監聽。Phase 3 使用 `FasterWhisperBackend` 與 multilingual `base` model。首次使用會下載模型到使用者資料目錄的 `models`；若 CUDA 可用則以 GPU float16 推論，否則使用 CPU int8。**本機 backend 不需 API Key，也不傳送音訊到雲端。**

`ASRBackend` 是可替換的介面，Studio 只依賴辨識事件。未來的 `RealtimeCloudASRBackend` 可實作相同介面，不需修改 QML 或 Windows Process Loopback。ASR 直接消費 Phase 2 的 16 kHz mono int16 PCM；交接 queue 最多 128,000 bytes，落後時丟棄最舊音訊。VAD 組成語音片段，partial 更新同一 LIVE 項目；final 每句只保存一次，立即寫入 SQLite 並原子更新 `transcript.json`。Session 恢復時以 SQLite 修復可能尚未寫完的 JSON。原始音訊不落盤。

## 即時翻譯

本機 `OllamaTranslationBackend` 使用 Qwen2.5 1.5B 量化模型（只有 Final 必要時才用 CPU 的 7B 模型補救事實檢查未通過的句子；Partial 永不觸發 7B）。不需要 API Key，翻譯文字只傳至 `127.0.0.1:11434`，模型以 `num_gpu=0` 與四個 CPU threads 運行，不佔用 Faster-Whisper 的 GPU 計算。請先啟動 Ollama 並拉取上述兩個模型；若服務不可用，原文會繼續保存，翻譯標記 `translation_pending`，約 30 秒後重試。開啟既有 Session 或恢復中斷 Session 也會掃描 pending，不建立新資料夾。

右側可以切換 `zh-TW` / `zh-CN` 和 Natural / Faithful / Minimal Subtitle；詞庫在 Dictionary 中增改刪並用 JSON 路徑匯入、匯出。兩個中文 locale 會進入模型 prompt，OpenCC 只作最後字形檢查，指定譯名最後套用。最近五句、30 秒內的 Final 原文用於消歧。翻譯部分更新同一 LIVE 項目；ASR Final 先持久化原文與 pending 標記，再對完整原文重新翻譯並原子更新 SQLite/JSON。長句按句子邊界翻譯，避免過長 prompt；明顯丟失數字、時間、否定、推測、譯名時拒絕 Final 並等待重試。這是保守檢查，並不能形式化保證每一項語意完全正確，重要內容仍需人工核對。

翻譯佇列最多 12 筆，partial 同句合併且至少間隔 1.2 秒（標點處可優先），Final 優先；滿載時 Final 已保存在 SQLite pending 並由後續掃描補做。Overlay 的 Gaming 顯示譯文與 speaker placeholder，Watching 顯示譯文及原文，Minimal 只顯示譯文；視窗維持置頂、透明深色、滑鼠穿透。翻譯不保存原始音訊。

## 即時 Speaker 分離

`DiarizationBackend` 與 UI、ASR 和音訊擷取解耦。預設 `SherpaOnnxDiarizationBackend` 使用 sherpa-onnx 的 pyannote segmentation 3.0 int8 ONNX 與 3D-Speaker CampPlus 中英語 embedding，均在 CPU 執行；已有 512 維 ERes2Net embedding 的 Session 恢復時仍使用原模型，保留舊 speaker profile。首次開始監聽時從 sherpa-onnx 官方 GitHub release 下載並檢查 SHA-256。模型存放在使用者資料目錄 `diarization-models`；不需 API Key。若無網路或模型載入失敗，Speaker 會顯示暫不可用，ASR 和翻譯繼續。

分離器讀取同一份 16 kHz mono int16 PCM，獨立工作執行緒處理最多 20 秒的記憶體視窗。輸入佇列最多 256 塊，每塊最多一秒 PCM（約 8 MB 上限）；結果最多 180 個時間區間，最多八個暫定候選，每位 Speaker 最多保存三個代表 embedding（新 Session 為 192 維，舊 Session 為 512 維）；佇列滿時丟棄最舊塊。原始直播音訊不寫入硬碟。每次 Final 以時間區間優勢判斷 Speaker；不足時標 `unknown`，後續可靠結果可補回自動指定，手動指定永不被覆蓋。多人同時說話而無法可靠分離時建立 `multi_speaker_event`。只有兩位已確認 Speaker 的原文均明確標示笑聲或同時驚呼，才會將事件升級為 laughter 或 collective reaction；其餘保留 overlapping_speech/unknown_overlap，不推測原因。

Session Speaker 使用不可變 `speaker_001` 等 ID，顯示名稱與 `person_id` 分開保存。V1 最多自動建立四位 Speaker；之後無法可靠匹配的聲音保留為 `unknown`。Speakers 頁面可改名、保存 person mapping、合併；逐字稿可手動指定 Final 的 Speaker。所有操作立即寫入 SQLite，`transcript.json` 及 `exports/transcript.md`、`exports/subtitles.srt`、`exports/subtitles.vtt` 由當前 mapping 重繪；合併會留下 `speaker_audit` 記錄且 ID 不重用。單人未改名時可隱藏標籤；多人時 Studio/Overlay 顯示名稱與固定 accent 色。LIVE 頁面預設呈現最新 120 筆，較早逐字稿可分批載入；完整紀錄一直保存在 SQLite/JSON 與匯出檔，避免長直播在 QML 同時建立無上限的段落卡片。

**限制：**此版是有限視窗的即時分離，並非離線全場回看。交疊聲音、短句、音效、遠近音量差異大的情況可能輸出 `unknown` 或多餘候選；請用 Speakers 頁面的合併與手動指定修正。笑聲與集體反應只接受明確、雙 Speaker 的原文證據，通常會保守地保留為一般 overlap。

## Session History 與最終輸出

Session 以 UUID 作為真正身份，可讀資料夾名只用於辨識。每場至少有 `session.json`、`transcript.json`、`transcript.md`、`exports/transcript.srt` 與 `exports/transcript.vtt`；原始音訊預設不儲存。SQLite 和 `transcript.json` 在直播中持續更新，Markdown/SRT/VTT 在 Session 完成、Speaker 改名／合併／手動指定或人工匯出時重新產生。SRT/VTT 可選譯文、原文或雙語。

History 可開啟舊 Session、改名、開啟資料夾、重新匯出與刪除；刪除需要第二次確認。意外中斷的 Session 在下次啟動顯示繼續、封存或新建選項，繼續時保留原 session ID、資料夾、speaker ID 與待補翻譯。完成時會等待背景 Final 翻譯最多 15 秒，逾時保留 `translation_pending` 與原文，不會無限卡住。可設定音訊來源關閉或指定無聲時間後自動完成，並可在所有持久化與匯出成功後自動關閉。

Studio 搜尋可配對原文、譯文與 Speaker 顯示名稱。控制器只從 SQLite 載入最新 120 筆 Final，「載入更早逐字稿」每次再載入 120 筆；搜尋結果上限 100，避免長直播在 Python 與 QML 同時建立數千張卡片。

中斷補譯驗證（使用資料目錄中現有 Session，**不建立新 Session**）：

```powershell
.\.venv\Scripts\python.exe scripts\probe_translation_recovery.py <session-id>
```

手動實測可在 Chrome 播放語音後執行：

```powershell
.\.venv\Scripts\python.exe scripts\probe_asr.py --language auto --seconds 30
```

此診斷工具輸出 partial、final、延遲、CPU/RAM 與暫存 Session 路徑；不保存 PCM。

手動診斷：

```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe scripts\probe_audio.py
.\.venv\Scripts\python.exe scripts\probe_audio.py --pid 12345 --seconds 5
```

`scripts\verify_isolation.py --chrome-pid 12345` 會在另一個 Python 程序播放合成測試音，並比較兩個程序的記憶體擷取頻譜；測試音與 capture 都不寫入硬碟。

## 階段

- Phase 1：Studio、Overlay 預覽、設定、Session/DB 基礎，已完成。
- Phase 2：Windows 指定程式音訊擷取與音量測試，已完成。
- Phase 3：本機 Streaming ASR、partial/final 與即時持久化，已完成。
- Phase 4：本機翻譯、詞庫與 Overlay，已完成。
- Phase 5：即時 Speaker 分離、管理、多人事件與顯示名稱輸出，已完成。
- Phase 6：Session History、中斷恢復、Speaker 修正、搜尋與 Markdown/SRT/VTT 匯出，已完成。
- 後續階段尚未開始。
