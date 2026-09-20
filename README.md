# Vtuber Live Translator

Windows 即時翻譯桌面程式，開發中。此版本是 **Phase 4**：保留 Windows 指定程式擷取、本機串流辨識、Session 與 SQLite/JSON，加入本機日英語即時中譯、專有名詞詞庫與三種 Overlay 模式。**目前尚無 speaker diarization 或正式 EXE**。

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

本機 `OllamaTranslationBackend` 使用 Qwen2.5 1.5B 量化模型（必要時 CPU 的 7B 模型補救事實檢查未通過的句子）。不需要 API Key，翻譯文字只傳至 `127.0.0.1:11434`，模型以 `num_gpu=0` 與四個 CPU threads 運行，不佔用 Faster-Whisper 的 GPU 計算。請先啟動 Ollama 並拉取上述兩個模型；若服務不可用，原文會繼續保存，翻譯標記 `translation_pending`，約 30 秒後重試。開啟既有 Session 或恢復中斷 Session 也會掃描 pending，不建立新資料夾。

右側可以切換 `zh-TW` / `zh-CN` 和 Natural / Faithful / Minimal Subtitle；詞庫在 Dictionary 中增改刪並用 JSON 路徑匯入、匯出。兩個中文 locale 會進入模型 prompt，OpenCC 只作最後字形檢查，指定譯名最後套用。最近五句、30 秒內的 Final 原文用於消歧。翻譯部分更新同一 LIVE 項目；ASR Final 先持久化原文與 pending 標記，再對完整原文重新翻譯並原子更新 SQLite/JSON。長句按句子邊界翻譯，避免過長 prompt；明顯丟失數字、時間、否定、推測、譯名時拒絕 Final 並等待重試。這是保守檢查，並不能形式化保證每一項語意完全正確，重要內容仍需人工核對。

翻譯佇列最多 12 筆，partial 同句合併且至少間隔 1.2 秒（標點處可優先），Final 優先；滿載時 Final 已保存在 SQLite pending 並由後續掃描補做。Overlay 的 Gaming 顯示譯文與 speaker placeholder，Watching 顯示譯文及原文，Minimal 只顯示譯文；視窗維持置頂、透明深色、滑鼠穿透。翻譯不保存原始音訊。

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
- 後續階段：speaker diarization、匯出與 EXE 安裝包；本階段未開始。
