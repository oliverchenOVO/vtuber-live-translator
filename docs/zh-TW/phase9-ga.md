# Phase 9：真實環境驗證與 GA 門檻

> 本頁是 [英文原始報告](../../PHASE9_REPORT.md)的繁體中文閱讀版，記錄當時的驗證狀態。**GA READY: NO**。這不是已完成獨立驗收的聲明；沒有公開 `v1.0.0` GA tag 或正式 Release。倉庫後來改為 public，只是程式碼可見性變更，**不代表通過 GA**。

## 未通過的門檻

| 等級 | 項目 | 證據與待完成事項 |
| --- | --- | --- |
| **BLOCKER** | 獨立 Windows 11 安裝與首次使用 | 當時沒有第二台 PC 或乾淨 VM。開發機已有 Python、原始碼、模型快取和工具，不能代替驗收。須在無預裝依賴的電腦完成安裝 → 下載 → 重啟 → Chrome → Session → ASR → 翻譯 → Overlay → 匯出 → 重啟 → History，不能手動補開發依賴。 |
| **BLOCKER** | 實體遊戲與 Overlay | 尚未完成 30–60 分鐘「遊戲＋Chrome＋Translator」測試，實體滑鼠穿透／拖曳／調整大小／鎖定、Alt-Tab 及 fullscreen／borderless 都未驗證。兩個螢幕存在，但搬移、重啟和拔除第二螢幕未做實測。Phase 8 Qt flag／位置測試僅為 **simulated only**。 |
| **BLOCKER** | 來源矩陣與獨立使用者 | 尚未在乾淨主機分別完成日文單人、雙人、3–4 人及英文談話每類 15–30 分鐘，也未完成 Chrome Twitch、Edge、Firefox、VLC 的音訊試驗。沒有未受指導的外部使用者測安裝包；正式打包版截圖當時亦待補。 |
| **CRITICAL** | Final 譯文會加入不存在的事實 | 對 Phase 8 儲存的 100 筆日文、50 筆英文 Final 做固定種子助理審查，至少 **22 筆**有明顯擴寫／新增內容。這是保守下限，**不是錯誤率**。狹義防護攔下 prompt 洩漏、未翻譯日文及過長輸出，只拒絕 150 筆中的 8 筆；語意錯誤仍在，須獨立人工核對來源／音訊。 |
| **MAJOR** | 密集語音翻譯延遲 | Phase 8 的額外觀測負載下，Gaming Final 翻譯平均 **38.2 秒**、P95 **63.3 秒**；原文會以 `translation_pending` 持續保存。 |
| **MAJOR** | 活躍記憶體趨勢 | Phase 8 Private Memory 整體 **+5.64 MiB／分**，第二小時 **+1.25 MiB／分**；20 次停止後比第一次停止高 **153 MiB**。任意時長穩定性未證實。 |
| **MAJOR** | Speaker 準確度與 Unknown | 1,456 筆 speech 中 **1,173 筆 unknown**；speaker 001／002／003 分別有 138／63／62 筆。這是保守顯示，不是多人分離準確率。19 個 overlap 全保留 `unknown_overlap` 或 `overlapping_speech`。 |

原報告門檻總數為 **BLOCKER 3、CRITICAL 1、MAJOR 3**。前三項是缺少必要驗收證據，不表示已觀察到程式 crash；翻譯品質問題則直接影響核心輸出。

## 開發機實際執行範圍

- 當時開發機為 Windows build 26200、RAM **47.7 GiB**、雙螢幕（2560×1440 與 2048×1280）；**不是**乾淨驗收機。C 槽約有 29.6 GiB 可用。Hyper-V 查詢需要提權，未找到現成 VM 映像或命令；這不證明日後無法建立 VM。
- Phase 8 打包程式在開發機播放 Chrome／YouTube：日文單人約 **31 分鐘**、日文多人約 **39 分鐘**、英文談話約 **51 分鐘**，另有靜音段。當時使用既有 Ollama runtime，不能替代乾淨安裝；雙人和 3–4 人類別也沒有分別證實。
- 翻譯抽樣由 Phase 8 SQLite 中以種子 `20260924` 選出 100 筆日文、50 筆英文 Final。審查比較的是**已保存 ASR 文字與譯文，沒有原始語音**；不能拿它評分 ASR，也不是外部真人研究。
- 新輸出防護保留被拒譯文的原文為 pending。修改後 **390 項自動化測試通過**，包含五項新增防護測試與既有 Phase 1–8 測試。

## 音訊來源相容性

| 來源 | 分類 | 範圍 |
| --- | --- | --- |
| Chrome ＋ YouTube | **Works with limitations** | Phase 8 開發機真實媒體與程序音訊擷取；不是獨立 Phase 9 驗收。 |
| Chrome ＋ Twitch | **Not verified** | 尚待測。 |
| Chrome ＋ Bilibili／其他 HTML5 | **Not verified** | 可選測項，尚未完成。 |
| Edge | **Not verified** | 開發機已安裝，音訊驗收未完成。 |
| Firefox／VLC | **Not verified** | 標準路徑未找到可執行檔，未完成音訊驗收。 |
| Discord | **Not verified** | 有捷徑，未完成合適音訊試驗。 |

擷取層使用 Windows Process Loopback，不依賴網站 API；這是架構事實，**不等同每個來源已相容驗收**。

## 隱私與網路稽核

程式碼檢視顯示程序音訊使用有界記憶體緩衝、逐字稿保存在本機 SQLite／JSON、Speaker embedding 留在本機；Phase 8 本機執行未儲存 PCM。診斷 ZIP 使用白名單 enum 設定及數值指標，不加入逐字稿、原始音訊、API Key、embedding 或原始 log。

正常本機翻譯連向 `127.0.0.1:11434`。模型設定會從 GitHub 下載固定版 Ollama、從 Hugging Face 取得 ASR 模型、從 sherpa-onnx GitHub Release 取得 diarization 模型；Ollama 的模型下載由本機 runtime 連到其模型 registry。`VLT_RELEASES_API` 預設為空，因此更新檢查停用；原始碼中未找到遙測 endpoint。這只是**原始碼層級稽核**，不是乾淨安裝後的封包擷取，GA 前仍須做實際連線稽核。

## 打包、簽章與 Defender

- 候選版 Setup **未簽章**；當時使用者的 Personal 憑證庫沒有可用的 code-signing 憑證。Windows 可能顯示 Unknown publisher／SmartScreen，不應用測試憑證冒充正式簽章。
- 設定 `SIGNING_CERT` 後，`build_release.ps1` 會簽主程式與 Installer，檢查 Authenticode，並要求 `signtool verify /pa /v`。沒有另行自製的 native helper EXE／DLL；第三方 DLL 不重新簽署。
- Phase 9 候選版建置來源是乾淨提交 `0c7d2449b603c87481e72c059a93995192a63896`，建置腳本先跑完 **390 項測試**。候選 Setup 改名為 `VtuberLiveTranslator-1.0.0-rc-phase9-Setup.exe`，用來和舊 RC 區別，**不是 GA artifact**。
- 舊 Phase 8 RC Setup 為 **105,881,875 bytes**，SHA-256 `1e9fd97697ea7d5b65e0a39ed2f1345f4c588c9cb36b9436651cf346380c942d`。Phase 9 候選 Setup 為 **105,885,046 bytes**，SHA-256 `f06d32ad5ea953e42e1d1a9d77cb9a9e06f971558b1e1e9fef43c775c4679e85`；候選主 EXE 為 `b908585b92247034d2fbab0ce9215a3f2a9bf2ba03fdbf21f363b378b2162cc8`。重建的 `SHA256SUMS.txt` 已逐項讀回驗證。Portable 資料夾 **439,629,523 bytes**，只是建置產物，不是已驗收的便攜版。
- 2026-09-24 03:21:18（UTC+8），Windows Defender 對**這個精確的候選 Setup** 完成自訂掃描，Operational 事件 1000／1001 同一 scan ID，前後均記錄 **0 項偵測**。當時 AntivirusEnabled=true、RealTimeProtectionEnabled=false，未調整該設定；單引擎掃描不保證所有防毒都不會警示。
- 首次下載約 **2.45 GB**；安裝與模型約 **3.3 GB**（清快取後）或 **4.7 GB**（保留快取）。這是 Phase 8 估計，不是乾淨 Phase 9 主機測量。

## GA artifact 規則

未關閉上述門檻前，**不得把 RC 改稱 GA、建立最終 GA Installer、沿用舊 checksum、推送 `v1.0.0` tag 或發布 GitHub Release**。門檻通過後，才由指定的乾淨提交重新建置全部產物、掃描精確檔案、重新計算 SHA-256，並提出 tag target 供使用者確認。英文原報告另記錄了當時對倉庫可見性的限制；後續公開原始碼不改變這些 GA 產物門檻。
