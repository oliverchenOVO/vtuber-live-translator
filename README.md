# Vtuber Live Translator

Windows 即時翻譯桌面程式，開發中。此版本是 **Phase 3**：保留 Transcript Studio、Overlay 預覽、設定與 Windows 指定程式擷取，加入本機串流語音辨識、逐字稿與即時保存。**目前尚無翻譯、speaker diarization 或正式 EXE**。

## 開發版啟動

需要 Python 3.12+。在 PowerShell 執行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
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
- 後續階段：翻譯、speaker diarization、匯出與 EXE 安裝包。
