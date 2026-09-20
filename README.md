# Vtuber Live Translator

Windows 10/11 即時翻譯桌面程式，開發中。此版本是 **Phase 1**：可啟動的 Transcript Studio、Overlay 預覽、設定與 Session 持久化基礎。**目前尚不能擷取音訊、辨識語音或翻譯直播**；介面會清楚顯示此狀態。

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

使用者資料預設保存在 Windows 的 `%LOCALAPPDATA%\VtuberLiveTranslator`；可在開發或測試時用 `VLT_DATA_DIR` 改變位置。Session 使用 UUID 作為身份，SQLite 記錄路徑和狀態，個別資料夾保存 `session.json` 與 `transcript.json`。目前介面的「建立空白 Session」只建立資料結構，不會假裝開始翻譯。

## 階段

- Phase 1：Studio、Overlay 預覽、設定、Session/DB 基礎。
- Phase 2 起：Windows 指定程式音訊擷取、ASR、翻譯、speaker diarization、匯出、崩潰恢復與 EXE 安裝包，依需求逐階段完成。

