# Phase 8 — Release Candidate Hardening

驗證日期：2026-09-23–24，Asia/Taipei。狀態：**Release Candidate Approved**（本機已執行驗收範圍；保留 3 項 MAJOR 與下述未驗證項目）。

## 範圍與環境

沿用 Phase 1–7 的 Windows Process Loopback、Faster-Whisper、Ollama、Speaker、Session 與深色 QML 介面。沒有開始 Phase 9，也沒有公開發布。

- 實機：Windows 11 Home build 26200；Intel Core i9-12900H，14 cores / 20 logical processors；47.7 GiB RAM，RTX 3070 Ti Laptop 8 GB。
- 長測、corpus、preset 與 packaged 啟停沿用本機既有 Ollama **0.20.3**、qwen2.5:1.5b Q4_K_M；獨立 managed runtime 下載／修復／關閉使用 pinned **0.34.2**。不把兩者視為同一 runtime 版本。
- 使用已安裝的正式 PyInstaller EXE / Inno Setup；另以獨立小型 probe 定位 native 資源生命週期。
- 這是開發主機。沒有可用的獨立乾淨 Windows VM / 第二台 PC，該項未驗證。
- CPU 百分比採「100% = 一個 logical core」；GPU 數值若取自 nvidia-smi，為整台機器使用量，不能當成 App 獨佔 VRAM。
- 所有實測擷取音訊只在有上限的記憶體緩衝區處理，未保存原始音訊。

## 問題分級與修正紀錄

| 等級 | 問題 | 修正／驗證 |
|---|---|---|
| CRITICAL | Process Loopback callback 與 async operation 互相持有 COM reference；每次啟停留下約 16 handles | callback 僅通知事件，結果改由呼叫端持有的 operation 取回；20 次 audio-only handles 約 360–366，COM instance 每次歸零 |
| CRITICAL | Windows CTranslate2 / oneMKL 重建 native worker 後保留內部緩衝區 | 官方 MKL_DISABLE_FAST_MM=1 在 import runtime 前設定；獨立 native 30 次由 1,736.8 MiB 終值降至 668.8 MiB；完整 ASR 20 次 724.9 → 729.5 MiB |
| CRITICAL | 結束自有 Ollama server 時，runner 子程序可能留下模型記憶體 | 關閉前取得自有程序子樹並清理；真實 1.5B 模型測試，主程序及 3 個子程序約 0.234 秒全部退出 |
| MAJOR | 長句拆分翻譯可能繞過 Gaming/Balanced 禁止 7B | 每個 Final 子句沿用明確的 allow_fallback；Partial 永遠 1.5B；HQ 額外勾選才允許 7B |
| MAJOR | 模型下載中斷或 Windows regular-file snapshot 損壞後無法局部修復 | 保留下載 partial；僅隔離損壞模型檔並重新下載，固定版本 hash 驗證 |
| MAJOR | 持續直播會累積已顯示 segment / dedup identity | LIVE 保留 120 筆、identity cache 512；較早歷史另行讀取，SQLite 保留去重判斷 |
| MAJOR | JSON / 匯出被中斷可能留下半份檔案 | temp + flush + fsync + replace；SQLite 交易與啟動修復驗證 |
| MINOR | 「かもしれない」被誤判成否定、3 可誤匹配 13 | 區分不確定語法、完整數值 token；新增 score/minute 單位漂移檢查 |
| MINOR | 停止期間切換來源、快速重按啟停可能形成中間狀態 | 錄製／啟停期間禁用來源選單；取消 Start、避免重複 stop worker |
| MINOR | 關閉視窗但取消系統匣模式時程序仍留在背景 | 明確觸發完整退出 |
| MINOR | Gaming 的 Speaker 上限文案固定寫 4 人，limited 後進度退成 3/4 | 依 backend 上限顯示；limited 仍屬已就緒，保留 Unknown 提示 |

oneMKL 修正依據：[Intel memory management guidance](https://www.intel.com/content/www/us/en/docs/onemkl/developer-guide-windows/2024-2/avoiding-memory-leaks-in-onemkl.html)。這會改用系統配置器，需搭配實測效能數值，不能只憑記憶體改善推論效能。

## 已完成的獨立驗證

- 既有 110 項保留，首輪 build 後 **383 passed**；加入 owned runtime 關閉回歸後，最終狀態文案修正後仍為 **385 passed**（110 既有 + 275 Phase 8；45.58 秒）。
- 10,020 segments / 8 小時 fixture：Markdown + SRT + VTT 約 0.263 秒；Working Set 峰值約 95.1 MiB。索引、時間、Unicode、多行與多人事件有 assertions。
- 在 Markdown、SRT、VTT render 中途分別強制結束真實 Python process，SQLite 保持 active，可重新 Finalize；不是僅拋 mock exception。
- 五次不同持久化階段強制結束 process：保留同 session_id / folder、無重複 segment、Speaker mappings 可恢復。完整 packaged Session 強制結束另記錄。
- 模擬磁碟不足：Finalize 不 falsely completed，DB integrity_check=ok。
- 真實 ASR download 強制中止時留下 66,991,554 bytes partial，重啟下載成功。
- 真實隔離 Ollama download 中止時約 9,528,385 bytes / 11 partial files，重啟成功取得 qwen2.5:1.5b。
- 實際破壞模型副本：Verify 偵測，Repair 約 25.44 秒後 hash 與載入驗證成功；未刪除整個模型目錄。
- 獨立聲源隔離：另一 Python process 播放 1733 Hz，最終 Chrome stream 同頻振幅約 0.00018，另一 process 約 0.21325（約 1175 倍差異）；不等於已測所有第三方播放器。

## UI 實測紀錄

- 真實原生輸入：Ctrl+H 切到 History、停止監聽、結束 Session、Speaker 改名「胡桃のあ 🎮 測試」，存檔後重讀 SQLite 名稱一致。
- 時間範圍 00:00:10–00:05:00 一鍵指定 Unknown，畫面回報 14 筆；原先已指定部分不變。
- Qt packaged probe 已驗證 Ctrl+H/L/O、Escape、Tab focus、Enter、Overlay edit/passthrough flags、geometry persistence；與實際滑鼠拖曳測試分開記錄。
- 保留深色介面、原 spacing/card/button；沒有整頁重做設計。

## 正式 EXE 長測與無聲測試

2026-09-23 約 21:18–23:51，本機 installed EXE 連續運行 **153.27 分鐘**並正常 Finalize / 退出。音源暫停紀錄位於監測第 **120.79 分鐘**，後續約 **32.2 分鐘無聲**。153 筆每分鐘樣本；起始模型載入前的第 0 分鐘不納入斜率。

來源順序：

- 單人日文：[胡桃のあ夜更雜談](https://www.youtube.com/watch?v=sbbsqPqv26s)，約 21:18–21:49。
- 多人日文：[ぶいすぽお悩み相談部](https://www.youtube.com/watch?v=phmjbPeQQIE)，約 21:49–22:28；播放器選擇日語原始音軌。
- 英文：[Daily Life English Conversation](https://www.youtube.com/watch?v=u44jm6oeEdI)，約 22:28–23:19。
- Chrome 兩個測試分頁曾重疊播放約 40 秒；擷取根 PID 不變。另有獨立 Windows 程序合成語句與音調隔離測試。

主 Session **1,454 筆**（1,435 speech + 19 多人事件）、3 位 Speaker、1,337 筆已完成翻譯。仍有 **98 筆 speech translation_pending**，保留原文可補做，未冒稱全數翻譯完成。 SQLite integrity_check=ok，JSON 與 DB ID 集合相同，沒有重複 ID、空白 speech 或反向時間。Markdown / SRT / VTT 已生成，SRT/VTT 均為 1,454 cues。

每 15 分鐘切換 Studio 顯示／隱藏、History / LIVE，輪流 Gaming / Watching / Minimal Overlay；LIVE 顯示始終最多 120 筆。History 另有一筆固定 fixture，因此下表原始監控的總筆數比主 Session 多 1。

### 資源採樣

CPU 已換算為整台 20 logical processors 的百分比。RAM 單位 MiB；GPU 欄是整機 nvidia-smi 用量，包含瀏覽器及其他程式。

| 分鐘 | App WS | App Private | App CPU | Ollama CPU | Ollama WS | 整機 GPU MiB |
|---:|---:|---:|---:|---:|---:|---:|
| 15 | 1008.9 | 2592.4 | 14.20% | 4.76% | 1489.5 | 6344 |
| 30 | 1092.8 | 2688.1 | 14.24% | 4.54% | 1531.0 | 6340 |
| 45 | 1286.4 | 2883.8 | 14.24% | 8.85% | 1509.8 | 6433 |
| 60 | 1358.3 | 2984.5 | 14.12% | 8.95% | 1522.6 | 6453 |
| 75 | 1389.6 | 3080.5 | 13.62% | 9.58% | 1520.8 | 6357 |
| 90 | 1422.2 | 3066.2 | 13.38% | 9.11% | 1504.8 | 6348 |
| 105 | 1502.0 | 3118.9 | 14.12% | 8.08% | 1544.1 | 6349 |
| 120 | 1525.6 | 3144.4 | 13.60% | 8.02% | 1503.6 | 6357 |
| 135 | 1424.8 | 3042.3 | 2.74% | 0.54% | 1496.7 | 6343 |
| 150 | 1429.0 | 3052.5 | 2.92% | 0.17% | 1493.8 | 6355 |

| 分鐘 | ASR queue bytes | 翻譯 queue | Speaker queue | Cache MiB | 總筆數 | 累計 dropped audio bytes |
|---:|---:|---:|---:|---:|---:|---:|
| 15 | 0 | 0 | 0 | 0.0 | 129 | 132806 |
| 30 | 0 | 0 | 0 | 0.0 | 244 | 132806 |
| 45 | 0 | 12 | 0 | 0.0 | 454 | 194350 |
| 60 | 0 | 11 | 0 | 0.0 | 651 | 396258 |
| 75 | 0 | 12 | 0 | 0.0 | 859 | 463200 |
| 90 | 0 | 12 | 0 | 0.0 | 1064 | 463200 |
| 105 | 0 | 12 | 0 | 0.0 | 1250 | 463200 |
| 120 | 0 | 12 | 0 | 0.0 | 1451 | 463200 |
| 135 | 0 | 0 | 0 | 0.0 | 1455 | 463200 |
| 150 | 0 | 0 | 0 | 0.0 | 1455 | 463200 |

整段觀察到的最大 ASR queue 122,010 bytes（設計上限 128,000）；翻譯 queue 最大 12；Speaker queue 最大 4、Speaker audio drop 0。ASR 累計丟棄 463,200 bytes，約 **14.48 秒 PCM**，約占有聲測試長度 0.20%；UI 有落後提示，不把它說成零遺失。Cache 目錄採樣皆 0 MiB，指測試 root 的可清理快取，非模型檔案或資料庫大小。

Gaming 的 Ollama `/api/ps` 回報模型 `size_vram=0`。另外實測 Windows per-process GPU counters：Studio 約 101–106 MiB dedicated（Qt 畫面）、Ollama runner 約 137 MiB圖形／runtime allocation；不能把模型 CPU 推論說成整個程序絕對零 GPU 配置，也不能把整機約 6.3 GiB 全算給本產品。

### 記憶體趨勢

以每分鐘數值做最小平方法直線斜率，單位 MiB/min：

| 區間 | Private Memory 斜率 |
|---|---:|
| 有聲全段（第 1 分鐘起） | +5.636 |
| 排除前 15 分鐘 | +3.987 |
| 第二小時 | +1.246 |
| 有聲最後 30 分鐘 | +2.668 |
| 無聲，排除前 2 分鐘收尾 | -0.223 |

有聲 App Private 範圍 2,184.7–3,153.7 MiB，有多次回落，但整段斜率仍為正；不宣稱任意長時間皆不成長。停止模型後約 1,841.8 MiB、WS 1,130.4 MiB，隨後程序退出。記憶體定位 probe 與修正前後差異另列。

### 無聲穩定區間

排除前兩分鐘收尾後的 30 筆每分鐘樣本：總筆數始終 **1,455**（含一筆 fixture），Speaker 始終 **3**；ASR Partial / Final 計數不變，沒有空白完成翻譯。原有 pending 低頻補做，完成翻譯由 1,332 增至 1,334，屬舊句修復。

App 平均 CPU **2.69% 整機**，Ollama **0.44%**；App Private **3036.8–3054.0 MiB**，斜率 -0.223 MiB/min。Speaker 仍低頻處理窗口，並非所有 worker 完全停用。

### 長測延遲

| 指標 | 樣本 | 平均 s | 中位 s | P95 s | 最大 s |
|---|---:|---:|---:|---:|---:|
| ASR_first_partial | 727 | 5.894 | 5.788 | 7.162 | 16.287 |
| Translation_partial | 136 | 3.224 | 2.742 | 6.844 | 10.000 |
| ASR_final | 1435 | 4.709 | 4.093 | 8.406 | 21.718 |
| Translation_final | 1477 | 38.204 | 41.766 | 63.282 | 84.110 |

翻譯樣本是成功回呼次數，包含重做同一 segment 的請求，不等於唯一完成 segment 數。Auto 語言辨識與 Gaming CPU 模式、密集對話及額外診斷負載都包含在此長測；後面的固定音訊 preset probe 條件不同。


## 已知限制

- 未驗證獨立 clean Windows；不能以同主機改 PATH 或新資料夾取代這项證據。
- 沒有提供 code-signing certificate，因此產物 unsigned；簽章管線有保留，實際有效簽章尚未測試。
- 保守 Speaker 辨識可標 Unknown，重疊發言可能無法分離；候選身分需人工確認。
- 小型翻譯模型仍可能出現用詞、單位或語意錯誤；heuristic facts guard 不等於完整語意驗證。
- warm model cache 未加入；停止後釋放模型。Ollama 現有 keep_alive 為 10 分鐘。

## 重現方式與本地證據

`python -m pytest -q`；`scripts/build_release.ps1`；`--phase8-cycle-test`、`--phase8-soak-test`、`--phase8-ui-test` 是明確指定才啟用的 packaged probe，正常啟動不執行。

本地 evidence 放在 gitignored `data/phase8-*`；模型 cache、私人逐字稿和 binary 不納入 git。測試原始碼、固定人工 corpus、彙總報告納入版本控制。

## 固定翻譯 corpus 實測

人工固定資料為 60 組日英對照、120 條不同來源文字，分別測 zh-TW / zh-CN，共 240 次真實 qwen2.5:1.5b 呼叫。沒有載入 7B。

| 類別 | 通過 guard／總數 |
|---|---:|
| 數字 | 27 / 28 |
| 日期 | 16 / 16 |
| 否定 | 28 / 28 |
| 不確定語氣 | 21 / 28 |
| 日常口語 | 36 / 36 |
| 遊戲詞彙 | 32 / 32 |
| Vtuber 用語 | 28 / 28 |
| 未完成語句 | 24 / 24 |
| 人名 glossary | 20 / 20 |

整體 232 / 240 產生通過 guard 的非空結果；另 8 筆被拒絕，保留原文待重試。Glossary 偏好名稱 20 / 20 出現在結果中。平均呼叫 2.129 秒、中位 0.849 秒、P95 8.806 秒；這是 corpus 呼叫時間，不能直接當作直播 Partial latency。

Guard 通過不等於人工語意驗收。抽查仍見「回復してる」誤成「正在回覆」、「回線が重い」直譯成「線路很重」，以及「ここで待とう」人稱偏移。這是仍開放的 MAJOR 翻譯品質限制，未宣稱模型 100% 正確。

## 安全掃描、簽章與 Diagnostics

2026-09-23 23:14:45–23:14:55（Asia/Taipei），Defender Custom Scan 掃描重建後最終 release 目錄（含 EXE 與 Installer），病毒碼 1.459.359.0，無偵測結果。主機即時保護原本為關閉狀態，測試未更動任何防護設定；此結果不代表所有防毒產品均不會誤判。

未提供 SIGNING_CERT，實際 Installer 為 NotSigned。管線具備 EXE / Installer 簽章及驗證步驟，但有憑證的端到端簽章尚未實測。

實際 Diagnostics ZIP 只有 diagnostics.json、recent-metrics.json、PRIVACY.txt；數值指標取最近 300 筆上限。沒有原始 log line、逐字稿、音訊、API key、路徑、身分或 embedding。Diagnostics 的模型欄是配置／managed runtime 識別，不是外部 Ollama server 的即時版本探測。

## 來源相容性與操作限制

| 來源／操作 | 實際證據與限制 |
|---|---|
| Chrome / YouTube | 本機 Process Loopback + 真實 ASR / 翻譯 / Studio / Overlay / SQLite 進行長時間測試 |
| 其他程式同時出聲 | 獨立 Python 音調隔離量測；另有 PowerShell System.Speech 合成語句，不保存音訊 |
| 錄製中換 source | UI 選單禁用並顯示先停止監聽；controller 同樣拒絕 busy / active 期間切換 |
| 程式關閉 | 實際來源程序結束後顯示「音訊來源程式已關閉。請重新偵測並選擇來源。」 |
| Edge | 已安裝；原生操作工具無法可靠辨認測試頁 URL，安全檢查停止操作，未宣稱完成音訊播放測試 |
| Firefox / VLC | 本次環境未找到安裝版本，未實測 |
| Discord | 列舉到背景程序，但本次沒有有效發聲測試 |
| Chrome renderer restart | 未刻意結束使用者瀏覽器的 renderer，未實測 |
| Twitch | 尚未實測 |

## 一般使用流程與 friction

| 步驟 | 結果／改善 |
|---|---|
| Download | 本機產出正式 Setup 與 checksums；未公開發布，沒有假裝測過公開下載頁 |
| Install / upgrade | 正式 Inno Setup 實際安裝至隔離測試目錄，既有測試資料保留 |
| First Run | packaged smoke 實際顯示深色精靈；下載中斷、checksum、磁碟錯誤、局部修復分別有對應測試 |
| Start | 四階段進度與取消；已在快速啟停 probe 觀察到約 1.6–2.5 秒就緒，但不等同於全新開機冷啟動 |
| Read Overlay | 真實翻譯接入三種模式；實體滑鼠穿透、拖曳、resize 未完成完整人工 audit |
| Stop / find transcript | 原生按鈕停止，Ctrl+H 開 History，SQLite / JSON 保留 |
| Rename speaker | 實際原生輸入 Unicode / emoji 名稱並保存；範圍批次 Unknown 指派 14 筆成功 |
| Export | 完成 Session 產生三格式；10,020 筆大型 fixture 和中斷恢復另行驗證 |
| Restart | 真實 packaged 多次啟動及 History 測試；五次強制結束結果另列 |
| Uninstall | 最終 Setup 的靜默卸載 exit=0，測試 EXE 移除；15 個 Session／DB／設定檔 SHA-256 未變 |

快捷鍵與 Qt focus 共 9 項 probe 通過。這提供鍵盤事件、Overlay flags 與 geometry 儲存的自動化證據，不能取代尚未完成的實體滑鼠驗證。原生工具因 URL 安全判定停止後，沒有改用 Win32 腳本繞過限制。

## 記憶體定位補充

- 來源列舉 300 次：Private 635.45 → 636.18 MiB，handles 298–301，COM instances 一直為 0。
- 同一 ASR 模型分別在 8 個 worker 上做兩輪相同 RAM 音訊推論：第一個 worker 後 1716.43 MiB，第八個 1718.15 MiB；第二輪 1718.45 MiB，停止模型後 720.21 MiB。未重現每個 worker 持續增加數十 MiB。
- 隔離的 production QML、120 筆固定假資料、300 次更新：100 次 793.03 MiB、200 次 793.84 MiB、300 次 793.15 MiB；QML GC 後 785.25 MiB。這是 offscreen/software renderer 診斷，不取代真實視窗滑鼠 audit。
- 第一輪 QML probe 意外因 fixture 的 pending 欄位觸發一筆翻譯，造成 22:15:56–22:16:05 的 Ollama 4→2 thread reload；已修正測試隔離並重跑。該段已標註，未拿來宣稱純 UI / 無模型測試。
- 以上定位 probe 可縮小資源成長的排查範圍，但不足以證明長測中的全部成長皆無害；仍列出完整正斜率與量測時間範圍。
- Soak 期間有短暫測試套件、列舉／ASR／QML 診斷等額外負載；長測資源數字屬壓力驗收紀錄，不是完全隔離的效能 benchmark。Preset 比較另外使用相同的 RAM 音訊樣本。

## 長測版本與最終重建範圍

本輪連續長測使用 installed EXE SHA-256 `addc78f843fa1a7c071cce1087e7b1e3908eaa344567251da63a46571bdfaacc`，對應 Setup SHA-256 `9dd0c695da64128cc2288bf03427a66ae39f7ebd9e8969c78b06b55d82298351`。

在長測中發現 owned Ollama server 的子程序清理問題，故保留長測繼續執行，另行重建最終 RC。產品程式差異為 `ModelManager.close()` 的 owned process-tree 清理，以及 controller 兩項純顯示判斷：Speaker 達上限仍算已就緒、上限人數依 preset 顯示。音訊擷取、ASR、翻譯推論／排程與 QML 均相同。新增兩項回歸與獨立真實 Ollama 測試均通過。最終 binary 的 packaged smoke、啟停、強制結束／恢復與卸載結果另列，不把舊 hash 的長測冒稱為新 hash 的完整長測。

## 最終產物

- Installer：`release/VtuberLiveTranslator-1.0.0-Setup.exe`，105,881,875 bytes（約 100.98 MiB）。
- Installer SHA-256：`1e9fd97697ea7d5b65e0a39ed2f1345f4c588c9cb36b9436651cf346380c942d`。
- EXE SHA-256：`812aeea578468891d72d467ce8a61b417a588d8b4770d66aaa86577291e1daf9`。
- 兩者 Authenticode 皆為 NotSigned；沒有公開發布。

## ASR 設定與延遲量測定義

沿用 WebRTC VAD mode 2、20 ms frame、5 幀中 3 幀為語音才啟動、200 ms pre-roll；至少約 1 秒語音才請求 Partial，Partial 最短 1.2 秒間隔；600 ms 無聲結束一句，最長 15 秒。Final 最短接受約 250 ms 的 PCM。未為追求延遲而改掉原有 Final 模型／解碼設定。

首次 Partial 從 utterance 第一段音訊計時；Final 從最後有聲 frame 計時；Translation 從該次請求入列計時（首輪由 ASR 事件觸發），包含等待 queue 的時間；補做請求會重新計時，不包含跨次重試的間隔。這些是不同指標，不能互相替代。

停止後明確卸載 ASR，沒有新增常駐 warm model cache。重複啟動仍受 Windows 檔案快取影響，因此快速 Start 數字不是全新開機、首次下載後的冷啟動承諾。

## 驗收證據索引

| 驗收 | 本機證據 / 可重現工具 |
|---|---|
| 正式 EXE 長測與每分鐘資源 | `data/phase8-rc-soak/{resources,acceptance,source-events}.jsonl`；`scripts/phase8_monitor.py`、`scripts/phase8_summarize.py` |
| 最終 packaged 20 次啟停與 owned runtime 退出 | `scripts/phase8_packaged_cycles.py`；`data/phase8-cycles-final/` |
| 五次 packaged taskkill /F | `scripts/phase8_packaged_crash.py`；`data/phase8-packaged-crashes-final/` |
| 固定 corpus 真實推論 | `tests/fixtures/translation_corpus.json`、`scripts/phase8_translation_corpus.py`；`data/phase8-corpus-summary.json` |
| 相同 RAM 音訊 preset 比較 | `scripts/phase8_presets.py`；`data/phase8-presets-final.json` |
| Whisper / Ollama download 中斷續傳 | `scripts/phase8_download_recovery.py`；`data/phase8-download-recovery/result.json` |
| 真實模型破壞與修復 | `scripts/phase8_model_repair_probe.py`；`data/phase8-model-repair/result.json` |
| 10,020 段與匯出中斷恢復 | `scripts/phase8_export_probe.py`、`tests/test_phase8_recovery.py`；`data/phase8-large-export-verified/` |
| 最終 release Defender / 簽章 / hash | `data/phase8-defender-release.json`；`release/SHA256SUMS.txt` |
| 完整回歸與 build | `data/phase8-final-build.log`；`scripts/build_release.ps1` |

上述 `data/` 是開發機的 gitignored 證據目錄，沒有把私人逐字稿或模型納入 Git；未來 clone 可用同名腳本重新產生自己的測試資料。

## 翻譯服務中斷恢復

長測中於 21:34:37 強制結束本次測試自有的 Ollama server，21:35:23 重新啟動，約 46 秒服務中斷。21:35:33 出現恢復後第一筆成功 Final 翻譯，約為 server 重啟後 10 秒。Audio / ASR 仍維持原 Session，沒有 ASR reconnect 或 capture failure；前後 SQLite 的 Session ID 未變。

這是本機 HTTP provider 中斷／恢復測試，不是停用使用者網路介面或雲端 WebSocket 測試。模型下載中止／續傳另外驗證。翻譯事實檢查拒絕的句子仍可能長時間 pending，退避重試不代表品質問題已修復。

## 三種效能模式實測

使用 Chrome 真實英文對話擷取最後 30 秒，僅保存在 RAM，再附加 1 秒 silence；同一份 31 秒 PCM 依序餵入三種 production backend 設定，語言固定 en。每次按 20 ms frame 餵入；Windows event loop 的實際排程間隔可能較長，並非嚴格 wall-clock realtime benchmark。

這是 ASR + Speaker + Final 翻譯的 pipeline probe，沒有 Studio/QML 開銷，也沒有 production Partial 翻譯排隊；不能直接等同完整 Studio 的資源與端到端延遲。三模式在同一個 probe process 依序執行，RAM 峰值可能含先前 runtime 的配置高水位。下面仍如實列出可測差異，不拿短 probe 推翻長測結果。

| 模式 | 實際 ASR device/model | threads / Speaker 間隔 | 首次 Partial 範圍 s | Final 平均 s | 翻譯平均 s | 模型啟動 s |
|---|---|---|---:|---:|---:|---:|
| gaming | cpu / base | 2 / 5s | 2.21–3.72 | 1.77 | 4.63 | 0.78 |
| balanced | cuda / base | 4 / 3s | 1.66–2.00 | 0.65 | 5.69 | 0.67 |
| quality | cuda / small | 6 / 2s | 1.76–3.22 | 0.77 | 4.65 | 1.25 |

| 模式 | App CPU（整機） | App WS 峰值 MiB | App Private 峰值 MiB | Ollama CPU（整機） | Ollama WS 峰值 MiB | Probe GPU dedicated MiB |
|---|---:|---:|---:|---:|---:|---:|
| gaming | 5.00% | 498.9 | 2020.6 | 2.52% | 1516.6 | 0.0 |
| balanced | 0.82% | 935.8 | 2147.2 | 5.11% | 1515.0 | 379.2 |
| quality | 1.32% | 1234.7 | 2640.3 | 4.62% | 1501.7 | 803.2 |

各模式 3 個 Final，ASR dropped bytes 全部 0；三模式皆使用 1.5B 翻譯、7B correction=false。Gaming/Balanced 都是 base；High Quality 是較大的 small ASR、6 threads 與 2 秒 Speaker 間隔，不代表所有句子必然更準。

人工抽查仍見 Balanced 的一筆輸出包含「我將把前述英文句子翻譯……」之類的指令說明，而非單純譯文。此例雖通過有限 facts guard，仍是品質不合格，列入開放 MAJOR。沒有把成功 HTTP 回應等同於正確中文。

此處模型啟動是已下載、OS cache 已暖的模型載入，不包含 First Run 下載。完整 fresh-root packaged smoke 從 process 啟動至自動退出約 4.34 秒（內含預定 1.8 秒顯示等待），不冒稱等於 UI 首幀時間或全新開機冷啟動。

## 最終 packaged smoke、History 與 Overlay 重開

最終 EXE SHA-256 與安裝後檔案一致，Setup 升級 exit=0。全新測試資料目錄的 packaged smoke exit=0，真實深色 First Run 畫面正常；耗時 4.34 秒包含 QA 的顯示等待。

以長測資料的隔離副本啟動最終 EXE，9 項 Qt keyboard / Overlay 檢查全部通過；History 真實顯示完成的長測 Session 與同一 ID。原始長測 evidence 未改動。第二次重開，Overlay 保留 Watching、locked=true、邏輯尺寸 720×152、位置 (920,1218)；150% scaling 截圖為 1080×228。實體滑鼠 drag / resize / passthrough 仍未完成手動 audit。

## 修改檔案摘要

- `audio/native/process_loopback.py`：移除 COM cycle；`asr/faster_whisper_backend.py`：native allocator 設定與明確釋放模型。
- `translation/{pipeline,ollama_backend}.py`：1.5B/7B 邊界、facts guard、過時 Partial / bounded cache；既有 translation abstraction 保留。
- `diarization/sherpa_backend.py`：模型續傳與停止後的 callback / worker 清理；沒有改寫辨識架構。
- `sessions/manager.py`、`subtitles/live.py`：原子 JSON、durable recovery、字幕格式安全、120 筆 LIVE window、Unknown 範圍指派。
- `product/{models,downloads,diagnostics,acceptance}.py`：局部 Verify/Repair、續傳、owned runtime 清理、隱私診斷、明確 opt-in QA probes。
- `ui/controller.py`、`ui/qml/{Main,Overlay}.qml`、settings/app：進度、取消、Speaker 修正、focus、Overlay edit/lock 與狀態文字；保留 Dark Theme 與既有版型。
- `scripts/build_release.ps1`、README、CHANGELOG、Release Notes：版本化安裝包、可選簽章、SHA-256、已知限制。
- `tests/test_phase8*.py`、固定 corpus 與 `scripts/phase8_*`：可重現回歸、下載／故障／資源／packaged 驗收工具。

## 最終 EXE 的五次強制結束

使用最終已安裝 EXE，Chrome 真實日文音訊、Gaming / ja，同一個 Session。分別在 Audio / ASR / Speaker 就緒後不同時間點執行 `taskkill /F`：

| 次數 | 就緒後秒數 | 結束前後保留的累積 segment 數 | 結果 |
|---:|---:|---:|---|
| 1 | 10 | 3 | 同 ID / folder，舊資料與人工名稱保留，DB ok |
| 2 | 15 | 6 | 同 ID / folder，舊資料與人工名稱保留，DB ok |
| 3 | 20 | 9 | 同 ID / folder，舊資料與人工名稱保留，DB ok |
| 4 | 25 | 13 | 同 ID / folder，舊資料與人工名稱保留，DB ok |
| 5 | 30 | 17 | 同 ID / folder，舊資料與人工名稱保留，DB ok |

第六次啟動恢復第五次 crash，正常 Finalize 與退出；最終 **20 筆**，JSON/DB ID 相同、SQLite integrity=ok，Session `a9edb1ee-ba59-4a8d-8221-b5cc97824682` 為 completed。測試只強制結束本次啟動的 packaged EXE PID。

## 最終 EXE 的 20 次啟停與 runtime 清理

20 輪完成，含退出檢查約 **179.38 秒**，exit=0。同一 Session、每輪 LIVE=false、Speaker worker 釋放，實際保存 **24 筆翻譯**。Audio / ASR / Speaker 就緒 **1.437–2.453 秒**；此 ready 門檻不包含尚在連接的翻譯，四階段會分開顯示。

停止後 Private Memory **1003.39 → 1156.82 MiB**（峰值 1156.82）；handles **2356 → 2358**。記憶體不是每次固定線性增加，中途有回落，但終值仍比起點多約 153.4 MiB，列為持續追蹤的 MAJOR，不宣稱完全零成長。

測試前僅清掉本次測試自有的外部 server，確認 localhost 沒有既有服務，再由 packaged app 自行啟動 Ollama。整段觀察到的自有子程序在正常退出後全部消失，沒有殘留 server / runner。獨立 managed 0.34.2 的同項測試也通過，詳見前述修正紀錄。

## 卸載與保留資料

在確認所有 packaged 測試程序退出後，執行隔離安裝目錄內的正式 uninstaller。exit=0，該目錄的 EXE 已移除。卸載前後比較長測、crash、cycle 以及既有預設資料目錄中的 DB／settings／Session JSON，共 **15 檔 SHA-256 全部相同**。沒有刪除使用者 AppData。

兩個本次建立的 Chrome 測試分頁已關閉；本次啟動的 App / Ollama 程序已退出。Edge 的原生測試操作曾被工具 URL 安全判定停止，未繞過限制繼續操作。

## RC 判定與仍開放問題

| 等級 | 仍開放數量 | 說明 |
|---|---:|---|
| BLOCKER | **0** | 已執行範圍內未觀察到 EXE 無法啟動、Session 遺失、抓錯 process、長測 crash、installer 損壞或升級／卸載刪除 transcript |
| CRITICAL | **0** | 本階段發現的 3 項資源生命週期問題均修正並重跑對應驗收 |
| MAJOR | **3** | 以下品質、延遲與資源趨勢仍須追蹤 |

1. **MAJOR-01 翻譯／辨識品質**：固定 corpus guard 232/240；人工抽查仍見直譯、人稱偏移、Auto 短句語言誤判、偶發指令說明混入譯文。不可當成完全正確字幕。
2. **MAJOR-02 Gaming 密集對話延遲**：長測 Final 翻譯平均 38.2 秒、P95 63.3 秒；ASR 在額外壓力下丟棄約 14.48 秒舊音訊。Queue 有上限、原文可恢復、錯誤不阻塞 ASR，但直播體感仍有改善空間。
3. **MAJOR-03 記憶體趨勢／資源預算**：已修正已定位的 COM / native worker / owned runner 問題；有聲長測仍為正斜率、最終 20 輪停止後 Private 增加約 153 MiB。無聲無持續成長且正常退出完全釋放程序，但本次資料不足以證明任意長時間的 native / UI 配置高水位上界。

**驗證缺口**：獨立 clean Windows、部分來源相容性、Chrome renderer restart、實體滑鼠 Overlay audit、實際有憑證簽章與全新開機冷啟動未完成，不標為通過。這些限制已寫入 Release Notes。Diagnostics 的 external runtime 版本僅有配置識別，是 MINOR 診斷限制。

本次 **385 pytest passed**（既有 110 + Phase 8 新增 275）、9 項 packaged Qt checks，以及上述真實模型／故障／長測探針分開計數。最終 binary 的 20 輪、5 次 crash、smoke、History／Overlay restart、卸載驗證均通過。依本階段「沒有 BLOCKER 可標記 RC」的條件，產出 **1.0.0 Release Candidate Approved**，不代表上述 MAJOR 與未驗證項目消失。沒有發布 public GitHub Release，也沒有開始 Phase 9。
