# ASR 準確度改善驗證（2026-10-02）

> 本頁是 [英文原始報告](../../ASR_ACCURACY_REPORT.md)的繁體中文閱讀版。這次只比較語音辨識；翻譯與 Speaker 歸屬沒有改動。

## 測試方法

- **資料：**Google FLEURS 日文 `ja_jp` 與美式英文 `en_us` 的 dev 語音與參考文字，授權為 CC BY 4.0。下載腳本依 repository metadata 驗證封存檔 SHA-256 和參考 TSV 的 Git blob SHA-1；逐段資料留在未追蹤的 `data/asr-eval/`。
- **樣本與指標：**每種語言固定取前 80 段。日文使用字元錯誤率 CER，英文使用詞錯誤率 WER；都做 NFKC、轉小寫及對應的標點／空白正規化。數字越低越好。
- **環境：**既有 faster-whisper／CTranslate2 模型、NVIDIA RTX 3070 Ti Laptop GPU 8 GiB、float16。各 beam 預熱後輪替測試。時間是每段推論呼叫平均值，**不含模型載入**。
- **適用範圍：**這是乾淨朗讀語音，**不是 VTuber 直播**；沒有量到 VAD 漏檢、背景音樂、重疊語音、幻覺或端到端延遲。

| 語言／指標 | 模型 | Beam 1 錯誤率 | Beam 3 錯誤率 | Beam 5 錯誤率 | Beam 1／3／5 平均呼叫時間 |
| --- | --- | ---: | ---: | ---: | --- |
| 日文 CER | base | 26.58% | **23.31%** | 22.79% | 0.123／0.139／0.143 秒 |
| 英文 WER | base | 11.79% | **10.15%** | 10.34% | 0.073／0.083／0.087 秒 |
| 日文 CER | small | 13.78% | **12.36%** | 11.81% | 0.256／0.287／0.310 秒 |
| 英文 WER | small | 7.06% | **6.05%** | 6.31% | 0.166／0.184／0.191 秒 |

## 決策與限制

Final 採用 **beam 3**，LIVE partial 保持 beam 1。Balanced 預設仍用 base，下載大小不變；既有 High Quality 可用 small，但在這張 GPU 上每段推論約慢一倍，並須另外下載模型。Beam 5 的額外收益很小，英文甚至退步，因此沒有選用。

另外抽查 24 段日文 CPU／int8：small beam 3 的 CER 為 **13.69%**，平均呼叫 **2.15 秒**。這和上表 80 段 GPU 測試不是同一樣本；只能說明沒有 GPU 時 High Quality 可能較慢，不能當作直播延遲。

Auto 語言模式在各 beam 下都將這批 80 段日文與 80 段英文判成預期語言，錯誤率與固定語言測試相同。Auto 另有偵測成本：beam 3 平均呼叫日文 **0.170 秒**、英文 **0.100 秒**。這不能證明短句或吵雜直播中的 Auto 同樣可靠。

正式程式的 ASR 信心門檻 **0.35** 沒有修改。這批乾淨樣本全數高於門檻，卻不能據此校準真實直播。舊直播紀錄中有不少日文短句被標為不確定；因為原始音訊沒有保存，無法事後判斷是 ASR 錯誤還是音訊本來就不清楚。

## 重現與驗證狀態

先執行 `python scripts/asr_eval_fetch.py ja_jp`／`en_us`，再執行 `python scripts/asr_eval_fleurs.py --language ja --model base --limit 80`，並對英文與 small 重複測試。回歸測試覆蓋 Final／partial 的不同 beam 設定；當時完整測試 **463 項通過**。

這輪改善**尚未完成新的 Chrome 直播端到端品質測試**：當時瀏覽器控制服務無法初始化，執行政策也拒絕從 shell 啟動 Chrome。因此沒有宣稱真實 Chrome 辨識品質或端到端延遲。手動輔助工具為 `scripts/probe_asr.py`；`--model-path` 可指向既有模型快照，只保存逐字稿與指標，不保存 PCM。
