# Vtuber Live Translator 1.0.0 — 候選版說明

> 本頁是 [英文原始 Release Notes](../../RELEASE_NOTES_1.0.0.md)的繁體中文閱讀版。紀錄時間為 **2026-09-24**。狀態是 **Release Candidate；暫緩 GA**，不要把此候選版當成 1.0.0 正式版散布。Phase 8 的驗收只涵蓋當時已執行的本機範圍；[Phase 9](phase9-ga.md)仍有獨立環境驗收缺口與關鍵翻譯品質問題。

## 功能

- 指定一個 Windows 程式及其子行程的音訊，在本機辨識日文／英文，翻譯成繁體／簡體中文，並顯示於 Studio 和 Overlay。
- Session 的原文、譯文和狀態保存在 SQLite／JSON；可從 History 恢復，匯出 Markdown／SRT／VTT。
- Speaker 不確定時顯示 Unknown；使用者可按鈕或時間範圍修正。人物身分必須人工確認。

## 系統需求與安裝

需要 **64 位元 Windows build 20348 或更新**，建議 Windows 11。較舊版本無法使用 Application Process Loopback；程式不會偷偷改抓全系統音訊。正式安裝包設計為不要求使用者另裝 Python、Git、開發工具或 Ollama CLI。

首次設定約需下載 **2.45 GB**，建議預留至少 **7 GB** 空間。清理下載快取後的完整安裝與必要模型約 **3.3 GB**；保留快取約 **4.7 GB**。First Run／Settings 會管理模型和本機 runtime；下載階段需要網路。目前**沒有公開安裝檔或 GitHub Release**。

## 隱私

音訊在本機處理，原始音訊預設不保存；逐字稿留在本機。模型下載會連線到發行來源，翻譯使用本機 Ollama HTTP endpoint。診斷檔僅包含程式與 Windows 版本、數值硬體摘要、白名單設定、模型識別值及解析後的數值 log 指標；不含原始 log、完整逐字稿、音訊、憑證、路徑、人物身分或 voice embedding。

## 已知限制

- **Speaker：**不確定語音可能是 Unknown；重疊說話不一定能分開。
- **辨識與翻譯：**兩者都可能出錯；事實檢查只是啟發式規則，不能保證語意正確。[Phase 9](phase9-ga.md)對 100 筆日文、50 筆英文 Final 的檢查找到多個明顯新增原文沒有內容的譯文。狹義防護只攔下明顯 prompt 洩漏、未翻譯日文與過長輸出，**語意偏移仍是 CRITICAL GA gate**。
- **密集對話延遲：**Gaming 模式在額外觀測負載下，Final 翻譯延遲平均 **38.2 秒**、P95 **63.3 秒**，較舊 ASR 音訊丟棄約 **14.48 秒**。未譯原文仍持久保存，可稍後重試。
- **記憶體：**Phase 8 活躍期間 Private Memory 整體斜率 **+5.64 MiB／分**，第二小時 **+1.25 MiB／分**；20 次啟停後比第一次停止高約 **153 MiB**。閒置斜率為 **−0.22 MiB／分**。佇列和即時歷史有上限，但任意長時間穩定性尚未證實。
- **效能模式：**Gaming／Balanced 只用 1.5B。High Quality 的 7B 修正須另行勾選且模型已安裝，約增加 **5 GB RAM**，也可能延後字幕。
- **簽章：**沒有正式憑證時候選版為 unsigned，Windows 可能顯示 Unknown publisher／SmartScreen；不應因此停用防毒。
- **尚未驗收：**獨立乾淨 Windows 安裝、Edge／Firefox／Discord／VLC／Twitch 音訊相容性、Chrome renderer 重啟、Overlay 實體滑鼠穿透／拖曳／調整大小，以及實體拔除第二螢幕。Chrome／YouTube 的程序音訊擷取已在開發機測試。
- **模型載入：**尚未做 warm model cache；Session 開始時載入，停止時釋放。

## 建置、簽章與可重現性

`scripts/build_release.ps1` 會執行完整測試並建立 EXE、Installer 與 SHA-256 校驗檔。可選的 `SIGNING_CERT` 指向 `Cert:\CurrentUser\My` 中可用的正式 code-signing 憑證 thumbprint；建置會簽署與驗證程式和 Installer，要求簽章卻失敗時會中止。沒有設定憑證則建立 unsigned RC。

## 當時驗證範圍

Phase 8 當時有 **385 項自動化測試通過**（保留 110 項及新增 275 項），另有 9 項打包後 Qt 檢查。已安裝程式的本機執行累計 **153 分鐘**，其中真實日／英文媒體超過 120 分鐘，靜音約 32 分鐘。最終 artifact 啟動煙霧測試、20 次啟停、5 次強制終止後恢復、runtime 子程序清理與卸載資料保留均通過。

連續長跑使用較早的 build；最終重建只變更 runtime 關閉與兩個顯示狀態修正，capture／推論／QML 未變，最終 artifact 另通過相關檢查。長跑使用既有 Ollama 0.20.3；受管 Ollama 0.34.2 的下載、修復與關閉另行測試，**不能視為乾淨電腦驗收**。當時 EXE／Installer 經 Windows Defender 自訂掃描沒有偵測項，但兩者均未簽章。詳細採樣與 artifact hash 見[英文 Phase 8 原始報告](../../PHASE8_REPORT.md)。

上述數字反映候選版當時狀態；後續 ASR 與翻譯實驗另見[中文 ASR 報告](asr-accuracy.md)、[Phase 10](phase10-translation.md)及[Phase 10B](phase10b-bakeoff.md)，不能把較新的測試數量回填成舊 Installer 已驗證。
