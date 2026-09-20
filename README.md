# Vtuber Live Translator

Windows 即時翻譯桌面程式，開發中。此版本是 **Phase 2**：保留可啟動的 Transcript Studio、Overlay 預覽、設定與 Session 基礎，加入指定 Windows 程式音訊擷取、即時音量 meter 與有上限的記憶體 PCM 緩衝區。**目前尚無語音辨識與翻譯，也尚無正式 EXE**；介面會清楚顯示此狀態。

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

使用者資料預設保存在 Windows 的 `%LOCALAPPDATA%\VtuberLiveTranslator`；可在開發或測試時用 `VLT_DATA_DIR` 改變位置。Session 使用 UUID 作為身份，SQLite 記錄路徑和狀態，個別資料夾保存 `session.json` 與 `transcript.json`。「建立空白 Session」只建立資料結構，不會假裝開始翻譯。

## 音訊監聽

在 LIVE 的 **APPLICATION AUDIO** 選擇程式並按「開始監聽」。清單顯示程序名稱、根 PID 和音訊輸出狀態，每 2.5 秒更新。來源消失後可重新偵測再連接。只監聽選取程序及其子程序；不會儲存擷取的原始音訊。

使用 Windows `ActivateAudioInterfaceAsync`、`AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK` 與 `PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE`。需要 Windows Build **20348 或更新**。較舊 Windows 10 不具備此正式 API，本版本會顯示清楚的版本錯誤；不會暗中退回整機 Stereo Mix。

格式流程：Windows Audio Engine 將程序音訊轉為 **44.1 kHz、stereo、signed 16-bit PCM**，接著在記憶體中 downmix 成 mono，以 libsoxr 連續重採樣到 **16 kHz**，輸出 **mono、signed 16-bit PCM**。Ring buffer 上限為 5 秒（160,000 bytes）；不會隨直播時間增長。此階段尚未接 ASR，音訊只供即時 meter 和後續管線使用。

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
- 後續階段：ASR、翻譯、speaker diarization、匯出、崩潰恢復與 EXE 安裝包。
