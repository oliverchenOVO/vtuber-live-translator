# 介面、字幕效果與紀錄方式

這些是開發驗證時留下的**實際程式截圖**，橫跨 v0.6 預覽版與 v1.0.0 候選版；不是同一次直播，也不是正式 GA 發行版的宣傳樣張。畫面中的辨識與翻譯可能有錯，不能以單張截圖推論整場直播的準確率。截圖只節錄公開直播的短句，未公開完整 Session 或資料庫。

## 日文與英文逐字稿

![日文測試 Session 的 Transcript Studio，顯示日文原文、中文譯文、時間與 unknown Speaker](../assets/screenshots/studio-japanese.png)

*v1.0.0 候選版，日文公開直播測試 Session。這張圖是在 Session 完成後拍攝，所以狀態顯示 OFFLINE。部分短句沒有可靠譯文，Speaker 保留 unknown；這些都是實際觀察到的狀態。*

![英文測試 Session 的 Transcript Studio，顯示英文原文、中文譯文及 Speaker 狀態](../assets/screenshots/studio-english.png)

*v1.0.0 候選版，英文公開直播測試 Session。Final Segment 顯示 Session 相對時間、原文和已產生的譯文；短句可能沒有譯文。自動 Speaker ID 是暫定分組，不等同真實人物身分。*

即時辨識時，partial 會更新同一筆 LIVE Segment；語音結束後 Final 才成為正式紀錄。Final 原文逐筆寫入 SQLite，翻譯完成後再更新同一 Segment。若翻譯尚未完成，保留 `translation_pending`，原文仍可查看。

## Overlay 字幕

![Minimal 模式 Overlay 顯示單行中文譯文](../assets/screenshots/overlay-minimal.png)

*v1.0.0 候選版實際測試畫面；Minimal 模式只呈現目前譯文。這是一次顯示效果的截圖，不代表譯文經人工確認。*

介面另提供 Gaming（譯文與 Speaker）和 Watching（譯文與原文）模式。Overlay 設計為置頂、深色半透明與滑鼠穿透，方便覆蓋直播或遊戲；在獨立乾淨 Windows 與各種全螢幕遊戲中的實體操作仍待完整驗收。

## History 與 Speaker 修正

![History 中的已完成實測 Session，可開啟、改名、找到資料夾或匯出](../assets/screenshots/history-phase6.png)

*v0.6 預覽版的一場已完成日文測試 Session，約 32 分鐘；此圖用來展示 History 的紀錄流程。後續 v1.0.0 介面文字與排版已有調整。*

History 可重新開啟既有 Session、改名、找到資料夾及重新匯出。程式意外中斷後，恢復流程沿用原 Session ID 和資料夾；已保存的 Final 不必等到直播結束才存在。

![Speaker 管理介面顯示三個暫定分組及人工確認入口](../assets/screenshots/speakers.png)

*v1.0.0 候選版的 Speaker 管理畫面。`speaker_001` 等是模型暫定分組；圖中的 segment 數量不是辨識準確率或已確認人物數。使用者可改顯示名稱、人工指定或保留 Unknown。*

## 本機保存與匯出

預設資料位於 Windows 的 `%LOCALAPPDATA%\VtuberLiveTranslator`。SQLite 的 `app.db` 保存 Session 與 Final Segment；每個 Session 資料夾包含 metadata `session.json` 和持續更新的 `transcript.json`。這是資料關係示意，資料夾名稱由程式依 Session 產生：

```text
%LOCALAPPDATA%\VtuberLiveTranslator\
├── app.db
└── <Session 資料夾>\
    ├── session.json
    ├── transcript.json
    ├── transcript.md
    └── exports\
        ├── transcript.srt
        └── transcript.vtt
```

`transcript.md`、SRT、VTT 是可從已保存紀錄重建的匯出檔；Session 完成、Speaker 編輯或手動匯出時可重新產生。SRT/VTT 可選原文、譯文或雙語。原始音訊預設**不寫入硬碟**。此 repository 沒有上列檔案的實際內容，也不包含 API Key 或 voice embedding。

已知限制與量測範圍見[Phase 9 驗證報告（中文）](zh-TW/phase9-ga.md)與[Phase 10B 翻譯測試報告（中文）](zh-TW/phase10b-bakeoff.md)。
