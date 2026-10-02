import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    visible: true
    width: 1380
    height: 830
    minimumWidth: 900
    minimumHeight: 520
    title: "Vtuber Live Translator — Transcript Studio"
    color: "#101319"
    font.family: "Microsoft JhengHei UI"

    property string page: "LIVE"
    property color bg: "#101319"
    property color panel: "#181d26"
    property color raised: "#202733"
    property color line: "#303947"
    property color muted: "#8e9bab"
    property color ink: "#eef2f6"
    property color accent: "#6ce2c5"
    property int firstRunPage: 0
    property bool trayPromptVisible: false
    property string modelRemovalTarget: ""
    function pageLabel(value) {
        return ({LIVE: "即時逐字稿", History: "歷史記錄", Speakers: "Speaker 管理",
                 Dictionary: "詞庫", Exports: "匯出", Settings: "設定"})[value] || value
    }
    Shortcut { sequence: "Ctrl+L"; onActivated: window.page = "LIVE" }
    Shortcut { sequence: "Ctrl+H"; onActivated: window.page = "History" }
    Shortcut { sequence: "Ctrl+O"; onActivated: studio.toggleOverlay() }
    Shortcut { sequence: "Escape"; onActivated: { window.modelRemovalTarget = ""; window.trayPromptVisible = false } }

    onClosing: function(close) {
        if (!!studio.preferences.minimize_to_tray) {
            close.accepted = false
            if (!studio.preferences.tray_prompt_seen) {
                window.trayPromptVisible = true
            } else {
                window.hide()
            }
        } else {
            close.accepted = false
            studio.quitApplication()
        }
    }

    function formatTime(ms) {
        const seconds = Math.floor(ms / 1000)
        return String(Math.floor(seconds / 3600)).padStart(2, "0") + ":" +
               String(Math.floor(seconds / 60) % 60).padStart(2, "0") + ":" +
               String(seconds % 60).padStart(2, "0")
    }
    function languageName(code) {
        return code === "ja" ? "Japanese" : code === "en" ? "English" : code.toUpperCase()
    }

    component AppButton: Button {
        id: control
        property bool primary: false
        property bool danger: false
        implicitHeight: 40
        leftPadding: 18
        rightPadding: 18
        font.pixelSize: 13
        font.bold: true
        contentItem: Text {
            text: control.text
            font: control.font
            color: control.primary ? "#10221e" : (control.danger ? "#ffb9bc" : window.ink)
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: 10
            color: control.primary ? (control.down ? "#49bd9e" : control.hovered ? "#8ef2d8" : window.accent)
                                   : control.danger ? (control.hovered ? "#4a3038" : "#382930")
                                                    : (control.hovered ? "#344052" : window.raised)
            border.color: control.activeFocus ? "#ffffff" : control.primary ? "transparent" : window.line
            border.width: control.activeFocus ? 2 : 1
            Behavior on color { ColorAnimation { duration: 140 } }
        }
    }

    component InfoCard: Rectangle {
        radius: 17
        color: window.panel
        border.color: window.line
        border.width: 1
    }

    component DarkField: TextField {
        color: window.ink
        placeholderTextColor: window.muted
        font.pixelSize: 12
        background: Rectangle { radius: 8; color: window.raised; border.color: parent.activeFocus ? window.accent : window.line }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.preferredWidth: 218
            Layout.minimumWidth: 218
            Layout.maximumWidth: 218
            Layout.fillHeight: true
            color: "#151a22"
            border.color: window.line
            clip: true
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 20
                spacing: 10
                RowLayout {
                    Layout.fillWidth: true
                    Layout.topMargin: 8
                    spacing: 10
                    Rectangle {
                        width: 35; height: 35; radius: 11
                        color: window.accent
                        Text { anchors.centerIn: parent; text: "V"; color: "#10221e"; font.bold: true; font.pixelSize: 20 }
                    }
                    Column {
                        Text { text: "VTUBER"; color: window.ink; font.bold: true; font.pixelSize: 14; font.letterSpacing: 2 }
                        Text { text: "LIVE TRANSLATOR"; color: window.muted; font.pixelSize: 9; font.letterSpacing: 1 }
                    }
                }
                Rectangle { Layout.fillWidth: true; Layout.topMargin: 21; Layout.bottomMargin: 10; height: 1; color: window.line }
                Text { text: "工作區"; color: "#68788d"; font.pixelSize: 10; font.bold: true; font.letterSpacing: 1.7; Layout.bottomMargin: 7 }
                Repeater {
                    model: [
                        {name: "LIVE", icon: "◉"}, {name: "History", icon: "▤"},
                        {name: "Speakers", icon: "◌"}, {name: "Dictionary", icon: "▦"},
                        {name: "Exports", icon: "↗"}, {name: "Settings", icon: "⚙"}
                    ]
                    delegate: Rectangle {
                        required property var modelData
                        activeFocusOnTab: true
                        Accessible.role: Accessible.Button
                        Accessible.name: window.pageLabel(modelData.name)
                        Keys.onReturnPressed: window.page = modelData.name
                        Keys.onSpacePressed: window.page = modelData.name
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.maximumWidth: 178
                        height: 43
                        radius: 10
                        color: window.page === modelData.name ? "#263d3c" : navMouse.containsMouse ? "#222b37" : "transparent"
                        border.color: activeFocus ? window.accent : window.page === modelData.name ? "#3d6961" : "transparent"
                        border.width: activeFocus ? 2 : 1
                        Behavior on color { ColorAnimation { duration: 130 } }
                        Row {
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.left: parent.left
                            anchors.leftMargin: 13
                            spacing: 13
                            Text { text: modelData.icon; color: window.page === modelData.name ? window.accent : window.muted; font.pixelSize: 18; width: 19 }
                            Text { text: window.pageLabel(modelData.name); color: window.page === modelData.name ? window.ink : "#adbac8"; font.pixelSize: 13; font.bold: window.page === modelData.name }
                        }
                        MouseArea { id: navMouse; anchors.fill: parent; hoverEnabled: true; onClicked: window.page = modelData.name }
                    }
                }
                Item { Layout.fillHeight: true }
                Rectangle {
                    Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.maximumWidth: 178
                    height: 96; radius: 13
                    color: "#202a32"; border.color: "#34474b"
                    Column {
                        anchors.fill: parent; anchors.margins: 13; spacing: 7
                        Text { text: "●  已就緒"; color: window.accent; font.pixelSize: 11; font.bold: true; font.letterSpacing: 1 }
                        Text { text: "直播工作區"; color: window.ink; font.pixelSize: 13; font.bold: true }
                        Text { text: "即時字幕 · 歷史 · 輸出"; color: window.muted; font.pixelSize: 11; width: 150; wrapMode: Text.WordWrap }
                    }
                }
                Text { text: "v" + studio.appVersion + "  ·  Windows"; color: "#647185"; font.pixelSize: 10; Layout.topMargin: 9 }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 78
                Layout.leftMargin: 30
                Layout.rightMargin: 30
                Text { text: "TRANSCRIPT STUDIO"; color: window.muted; font.pixelSize: 11; font.bold: true; font.letterSpacing: 2.1 }
                Item { Layout.fillWidth: true }
                Rectangle { width: 7; height: 7; radius: 4; color: studio.audioState === "capturing" ? window.accent : "#e6b865" }
                Text { text: studio.audioState === "capturing" ? "音訊監聽中 · ASR " + studio.asrState.toUpperCase() : "等待音訊來源"; color: studio.audioState === "capturing" ? window.accent : "#d7c298"; font.pixelSize: 12 }
            }
            Rectangle { Layout.fillWidth: true; height: 1; color: window.line }

            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 0

                Flickable {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    contentWidth: width
                    contentHeight: contentColumn.implicitHeight + 60
                    ScrollBar.vertical: ScrollBar { }

                    ColumnLayout {
                        id: contentColumn
                        x: 30; y: 27
                        width: parent.width - 60
                        spacing: 19

                        RowLayout {
                            Layout.fillWidth: true
                            Text {
                                text: window.pageLabel(window.page)
                                color: window.ink; font.pixelSize: 29; font.bold: true
                            }
                            Item { Layout.fillWidth: true }
                            Text {
                                visible: window.page === "LIVE"
                                text: studio.audioState === "capturing" ? "●  AUDIO LIVE" : "●  OFFLINE"
                                color: studio.audioState === "capturing" ? window.accent : "#dfbd82"; font.pixelSize: 11; font.bold: true; font.letterSpacing: 1
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            text: window.page === "LIVE" ? "一切對話，清楚留下。" :
                                  window.page === "History" ? "查看已建立的直播記錄。" :
                                  window.page === "Settings" ? "設定來源語言、即時翻譯與字幕顯示。" :
                                  window.page === "Dictionary" ? "管理專有名詞與譯名。" :
                                  window.page === "Speakers" ? "管理直播中偵測到的聲音與名稱。" :
                                  window.page === "Exports" ? "查看隨 Session 更新的字幕輸出。" :
                                  "此區域將隨後續階段開放。"
                            color: window.muted; font.pixelSize: 13
                        }

                        InfoCard {
                            visible: window.page === "LIVE" && !!studio.interruptedSession.session_id
                            Layout.fillWidth: true
                            Layout.preferredHeight: 130
                            color: "#2b2720"; border.color: "#695637"
                            ColumnLayout {
                                anchors.fill: parent; anchors.margins: 18; spacing: 9
                                Text { text: "上次 Session 未正常結束"; color: "#f0cd8d"; font.pixelSize: 15; font.bold: true }
                                Text { text: studio.interruptedSession.title + "  ·  " + studio.interruptedSession.duration; color: window.ink; font.pixelSize: 12 }
                                RowLayout {
                                    AppButton { text: "繼續原 Session"; primary: true; onClicked: studio.continueInterruptedSession(studio.interruptedSession.session_id) }
                                    AppButton { text: "完成並封存"; onClicked: studio.archiveInterruptedSession(studio.interruptedSession.session_id) }
                                    AppButton { text: "新建 Session"; onClicked: studio.createSession() }
                                }
                            }
                        }

                        InfoCard {
                            visible: window.page === "LIVE" && studio.audioState !== "capturing" && studio.transcriptSegments.length === 0 && !studio.liveSegment.id
                            Layout.fillWidth: true
                            Layout.preferredHeight: 156
                            color: "#1c292d"
                            border.color: "#345450"
                            RowLayout {
                                anchors.fill: parent; anchors.margins: 22; spacing: 17
                                Rectangle {
                                    width: 53; height: 53; radius: 16; color: "#2c4946"
                                    Text { anchors.centerIn: parent; text: "◉"; color: window.accent; font.pixelSize: 28 }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 7
                                    Text { text: "準備好你的直播工作區"; color: window.ink; font.pixelSize: 18; font.bold: true }
                                    Text { text: "選擇正在播放的程式，開始監聽並辨識即時語音。"; color: "#a5b8ba"; font.pixelSize: 12; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                    Text { text: "使用本機 Faster Whisper；逐字稿會立即寫入 Session。"; color: "#82a19f"; font.pixelSize: 11; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                }
                            }
                        }

                        InfoCard {
                            visible: window.page === "LIVE"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 211
                            ColumnLayout {
                                anchors.fill: parent; anchors.margins: 20; spacing: 10
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text { text: "程式音訊"; color: window.ink; font.pixelSize: 13; font.bold: true; font.letterSpacing: 1.1 }
                                    Item { Layout.fillWidth: true }
                                    AppButton { text: "↻  重新偵測"; onClicked: studio.refreshAudioSources() }
                                }
                                RowLayout {
                                    Layout.fillWidth: true; spacing: 11
                                    ComboBox {
                                        id: sourcePicker
                                        Accessible.name: "音訊來源"
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        model: studio.audioSources
                                        textRole: "display"
                                        valueRole: "id"
                                        currentIndex: studio.audioSources.findIndex(item => item.id === studio.selectedAudioSource)
                                        enabled: studio.audioSources.length > 0 && !studio.audioBusy && studio.audioState !== "capturing"
                                        onActivated: studio.selectAudioSource(String(currentValue))
                                    }
                                    AppButton {
                                        text: studio.audioBusy ? "取消啟動／停止" : studio.audioState === "capturing" ? "停止監聽" : "開始監聽"
                                        primary: studio.audioState !== "capturing"
                                        enabled: studio.audioBusy || studio.audioState === "capturing" || studio.audioSources.length > 0
                                        onClicked: {
                                            if (studio.audioBusy || studio.audioState === "capturing") studio.stopAudioCapture()
                                            else {
                                                studio.selectAudioSource(String(sourcePicker.currentValue))
                                                studio.startAudioCapture()
                                            }
                                        }
                                    }
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: studio.audioState === "capturing" ? studio.audioStatus + " · 切換來源前請先停止監聽。" : studio.audioSources.length === 0 && studio.audioState !== "error" && studio.audioStatus === "請選擇音訊來源" ?
                                          "尚未發現具有 Windows 音訊 Session 的程式。請播放聲音後重新偵測。" : studio.audioStatus
                                    color: studio.audioState === "error" ? "#ffb9bc" : window.muted
                                    font.pixelSize: 11; wrapMode: Text.WordWrap
                                }
                                RowLayout {
                                    Layout.fillWidth: true; spacing: 12
                                    Text { text: "音量"; color: "#7e91a1"; font.pixelSize: 10; font.bold: true; font.letterSpacing: 1 }
                                    Rectangle {
                                        Layout.fillWidth: true; height: 9; radius: 5; color: "#2d3743"
                                        Rectangle {
                                            height: parent.height; radius: 5
                                            width: parent.width * Math.sqrt(Math.min(1, studio.audioPeak))
                                            color: studio.audioPeak > 0.7 ? "#f0b86b" : window.accent
                                            Behavior on width { NumberAnimation { duration: 90 } }
                                        }
                                    }
                                    Text { text: Math.round(studio.audioPeak * 100) + "%"; color: window.ink; font.pixelSize: 11; font.bold: true; width: 32; horizontalAlignment: Text.AlignRight }
                                }
                            }
                        }

                        RowLayout {
                            visible: window.page === "LIVE"
                            spacing: 10
                            AppButton { text: "＋  建立空白 Session"; primary: true; enabled: studio.audioState !== "capturing" && !studio.audioBusy; onClicked: studio.createSession() }
                            AppButton { text: studio.overlayVisible ? "隱藏 Overlay" : "預覽 Overlay"; onClicked: studio.toggleOverlay() }
                        }
                        Flow {
                            visible: window.page === "LIVE" && (studio.audioBusy || studio.audioState === "capturing")
                            Layout.fillWidth: true; spacing: 12
                            Text { text: studio.startupStages.filter(s => s.ready).length + " / 4"; color: window.accent; font.pixelSize: 12 }
                            Repeater {
                                model: studio.startupStages
                                delegate: Text {
                                    required property var modelData
                                    text: (modelData.ready ? "✓ " : "● ") + modelData.name
                                    color: modelData.ready ? window.accent : window.muted; font.pixelSize: 12
                                }
                            }
                        }

                        InfoCard {
                            visible: window.page === "LIVE"
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.max(290, transcriptColumn.implicitHeight + 48)
                            ColumnLayout {
                                id: transcriptColumn
                                anchors.fill: parent; anchors.margins: 24; spacing: 13
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text { text: "逐字稿"; color: window.ink; font.pixelSize: 16; font.bold: true }
                                    Item { Layout.fillWidth: true }
                                    DarkField { id: transcriptSearch; Layout.preferredWidth: 230; placeholderText: "搜尋原文、譯文或 Speaker"; onAccepted: studio.searchTranscript(text) }
                                    AppButton { text: "搜尋"; onClicked: studio.searchTranscript(transcriptSearch.text) }
                                    Text { text: "Session 檢視"; color: "#607287"; font.pixelSize: 10; font.bold: true; font.letterSpacing: 1.4 }
                                }
                                Rectangle { Layout.fillWidth: true; height: 1; color: window.line }
                                Text { visible: transcriptSearch.text.length > 0; text: studio.searchResults.length + " 筆符合結果"; color: window.muted; font.pixelSize: 11 }
                                Flow {
                                    visible: studio.searchResults.length > 0
                                    Layout.fillWidth: true; spacing: 7
                                    Repeater {
                                        model: studio.searchResults
                                        delegate: AppButton {
                                            required property var modelData
                                            text: window.formatTime(modelData.start_ms) + " · " + (modelData.speaker_display_name || "未知說話人")
                                            onClicked: studio.showSearchResult(modelData.id)
                                        }
                                    }
                                }
                                Rectangle {
                                    visible: !!studio.focusedSegment.id
                                    Layout.fillWidth: true; implicitHeight: focusColumn.implicitHeight + 24
                                    radius: 10; color: "#263d3c"; border.color: "#3d6961"
                                    ColumnLayout {
                                        id: focusColumn; anchors.fill: parent; anchors.margins: 12; spacing: 6
                                        Text { text: "搜尋結果 · " + window.formatTime(studio.focusedSegment.start_ms || 0); color: window.accent; font.pixelSize: 11; font.bold: true }
                                        Text { text: studio.focusedSegment.translation ? studio.focusedSegment.translation.text : ""; visible: !!studio.focusedSegment.translation; color: window.ink; font.pixelSize: 15; font.bold: true; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                        Text { text: studio.focusedSegment.original || ""; color: "#b0bdca"; font.pixelSize: 13; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                    }
                                }
                                Item { Layout.fillHeight: true; visible: studio.transcriptSegments.length === 0 && !studio.liveSegment.id }
                                Text {
                                    visible: studio.transcriptSegments.length === 0 && !studio.liveSegment.id
                                    Layout.alignment: Qt.AlignHCenter
                                    text: studio.asrState === "connecting" || studio.asrState === "reconnecting" ? "音訊已接收，正在連接語音辨識…" : studio.asrState === "error" ? studio.asrStatus : "正在等待語音…"
                                    color: studio.asrState === "error" ? "#ffb9bc" : window.muted; font.pixelSize: 13
                                }
                                AppButton {
                                    visible: studio.earlierSegmentCount > 0
                                    text: "載入更早逐字稿（尚有 " + studio.earlierSegmentCount + " 筆）"
                                    Layout.alignment: Qt.AlignHCenter
                                    onClicked: studio.loadEarlierSegments()
                                }
                                Repeater {
                                    model: studio.transcriptSegments
                                    delegate: Rectangle {
                                        id: transcriptCard
                                        required property var modelData
                                        Layout.fillWidth: true
                                        implicitHeight: finalColumn.implicitHeight + 25
                                        radius: 10; color: window.raised; border.color: window.line
                                        ColumnLayout {
                                            id: finalColumn
                                            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                                            anchors.margins: 13; spacing: 7
                                            Text { text: window.formatTime(modelData.start_ms) + "  ·  " + (modelData.type === "multi_speaker_event" ? "MULTI" : window.languageName(modelData.language || "")); color: window.accent; font.pixelSize: 11; font.bold: true }
                                            RowLayout {
                                                visible: modelData.show_speaker && modelData.type !== "multi_speaker_event"
                                                Rectangle { width: 6; height: 17; radius: 3; color: modelData.speaker_color }
                                                Text { text: modelData.speaker_display_name + (modelData.speaker_new ? "  ·  NEW" : ""); color: modelData.speaker_color; font.pixelSize: 12; font.bold: true }
                                            }
                                            Text { visible: modelData.type === "multi_speaker_event"; text: (modelData.event_type === "unknown_overlap" ? "【重疊】" : "【多人】") + (modelData.description ? modelData.description.zh_tw : "偵測到重疊聲音，無法可靠區分。"); color: window.ink; font.pixelSize: 14; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                            Text { visible: modelData.type !== "multi_speaker_event" && !!modelData.translation; Layout.fillWidth: true; text: modelData.translation ? modelData.translation.text : ""; wrapMode: Text.WordWrap; color: window.ink; font.pixelSize: 17; font.bold: true }
                                            Text { visible: modelData.type !== "multi_speaker_event" && !modelData.translation; text: modelData.translation_state === "uncertain_source" ? "原文可能辨識不完整" : modelData.translation_state === "verifying" ? "正在校對…" : "翻譯待補"; color: window.muted; font.pixelSize: 11 }
                                            Text { visible: modelData.type !== "multi_speaker_event"; Layout.fillWidth: true; text: modelData.original || ""; wrapMode: Text.WordWrap; color: "#b0bdca"; font.pixelSize: 14 }
                                            RowLayout {
                                                visible: modelData.type === "speech"
                                                Text { text: "Speaker"; color: window.muted; font.pixelSize: 10 }
                                                ComboBox {
                                                    id: segmentSpeakerPicker
                                                    Layout.preferredWidth: 145
                                                    model: ["unknown"].concat(studio.speakers.map(s => s.speaker_id))
                                                    currentIndex: Math.max(0, model.indexOf(modelData.speaker_id))
                                                }
                                                AppButton { text: "手動指定"; onClicked: studio.assignSegmentSpeaker(modelData.id, segmentSpeakerPicker.currentText) }
                                            }
                                            Flow {
                                                Layout.fillWidth: true; spacing: 6
                                                visible: modelData.type === "speech" && (!modelData.speaker_id || modelData.speaker_id === "unknown")
                                                Repeater {
                                                    model: studio.speakers.slice(0, 4)
                                                    delegate: AppButton {
                                                        required property var modelData
                                                        text: modelData.display_name
                                                        onClicked: studio.assignSegmentSpeaker(transcriptCard.modelData.id, modelData.speaker_id)
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                                Rectangle {
                                    visible: !!studio.liveSegment.id
                                    Layout.fillWidth: true
                                    implicitHeight: liveColumn.implicitHeight + 25
                                    radius: 10; color: "#203932"; border.color: "#3d6961"
                                    ColumnLayout {
                                        id: liveColumn
                                        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                                        anchors.margins: 13; spacing: 7
                                        Text { text: window.formatTime(studio.liveSegment.start_ms || 0) + "  ·  LIVE  ·  " + window.languageName(studio.liveSegment.language || ""); color: window.accent; font.pixelSize: 11; font.bold: true }
                                        Text { visible: !!studio.liveSegment.show_speaker; text: studio.liveSegment.speaker_display_name + (studio.liveSegment.speaker_new ? "  ·  NEW" : ""); color: studio.liveSegment.speaker_color || window.accent; font.pixelSize: 12; font.bold: true }
                                        Text { visible: !!studio.liveSegment.translation; Layout.fillWidth: true; text: studio.liveSegment.translation ? studio.liveSegment.translation.text : ""; wrapMode: Text.WordWrap; color: window.ink; font.pixelSize: 17; font.bold: true }
                                        Text { Layout.fillWidth: true; text: studio.liveSegment.original || ""; wrapMode: Text.WordWrap; color: "#b0bdca"; font.pixelSize: 14 }
                                    }
                                }
                                Item { Layout.fillHeight: true; visible: studio.transcriptSegments.length === 0 && !studio.liveSegment.id }
                            }
                        }

                        InfoCard {
                            visible: window.page === "History"
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.max(150, historyColumn.implicitHeight + 38)
                            ColumnLayout {
                                id: historyColumn
                                anchors.fill: parent; anchors.margins: 18; spacing: 12
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text { text: "Session 歷史"; color: window.ink; font.pixelSize: 15; font.bold: true; font.letterSpacing: 1 }
                                    Item { Layout.fillWidth: true }
                                    Text { text: studio.history.length + " sessions"; color: window.muted; font.pixelSize: 11 }
                                }
                                Text { visible: studio.history.length === 0; text: "尚未建立 Session。可從 LIVE 建立空白 Session。"; color: window.muted; font.pixelSize: 13 }
                                Repeater {
                                    model: studio.history
                                    delegate: Rectangle {
                                        required property var modelData
                                        Layout.fillWidth: true; implicitHeight: historyItemColumn.implicitHeight + 24; radius: 10
                                        color: historyMouse.hovered ? "#293443" : window.raised
                                        border.color: studio.selectedSession.session_id === modelData.session_id ? window.accent : window.line
                                        ColumnLayout {
                                            id: historyItemColumn
                                            anchors.fill: parent; anchors.margins: 12; spacing: 9
                                            RowLayout {
                                                Layout.fillWidth: true
                                                ColumnLayout {
                                                    Layout.fillWidth: true; spacing: 4
                                                    Text { text: modelData.title; color: window.ink; font.pixelSize: 15; font.bold: true }
                                                    Text { text: modelData.date + "  ·  " + modelData.duration + "  ·  " + window.languageName(modelData.source_language) + " → " + modelData.target_language + "  ·  " + modelData.speaker_count + " speakers"; color: window.muted; font.pixelSize: 11 }
                                                }
                                                Text { text: modelData.status.toUpperCase(); color: modelData.status === "completed" ? window.accent : "#e6bc79"; font.pixelSize: 10; font.bold: true }
                                            }
                                            RowLayout {
                                                Layout.fillWidth: true; spacing: 7
                                                AppButton { text: "開啟"; primary: true; onClicked: { studio.selectSession(modelData.session_id); window.page = "LIVE" } }
                                                AppButton { text: "資料夾"; onClicked: studio.openSessionFolderFor(modelData.session_id) }
                                                AppButton { text: "匯出"; onClicked: studio.exportSession(modelData.session_id) }
                                                DarkField { id: historyRename; Layout.fillWidth: true; text: modelData.title; placeholderText: "Session 名稱" }
                                                AppButton { text: "改名"; onClicked: studio.renameSession(modelData.session_id, historyRename.text) }
                                                AppButton { text: "刪除"; danger: true; onClicked: studio.requestDeleteSession(modelData.session_id) }
                                            }
                                            Rectangle {
                                                visible: studio.pendingDeleteSessionId === modelData.session_id
                                                Layout.fillWidth: true; height: 54; radius: 8; color: "#382930"; border.color: "#6b3b47"
                                                RowLayout {
                                                    anchors.fill: parent; anchors.margins: 8
                                                    Text { text: "確定刪除此 Session 與其所有輸出？"; color: "#ffb9bc"; font.pixelSize: 12; Layout.fillWidth: true }
                                                    AppButton { text: "取消"; onClicked: studio.cancelDeleteSession() }
                                                    AppButton { text: "確定刪除"; danger: true; onClicked: studio.confirmDeleteSession() }
                                                }
                                            }
                                        }
                                        HoverHandler { id: historyMouse }
                                    }
                                }
                            }
                        }

                        InfoCard {
                            visible: window.page === "Settings"
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.max(690, settingsColumn.implicitHeight + 48)
                            ColumnLayout {
                                id: settingsColumn
                                anchors.fill: parent; anchors.margins: 24; spacing: 17
                                Text { text: "偏好設定"; color: window.ink; font.pixelSize: 17; font.bold: true }
                                Text { text: "設定會立即保存在本機。"; color: window.muted; font.pixelSize: 12 }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text { text: "效能模式"; color: window.ink; font.pixelSize: 13; Layout.fillWidth: true }
                                    ComboBox { model: ["Gaming", "Balanced", "High Quality"]; currentIndex: ["gaming", "balanced", "quality"].indexOf(studio.preferences.performance_preset); onActivated: studio.selectPerformancePreset(["gaming", "balanced", "quality"][currentIndex]) }
                                }
                                Text { visible: studio.preferences.performance_preset === "quality"; text: "High Quality 使用 small ASR。選用 7B 修正額外約需 5 GB RAM，部分字幕可能延後修正；不會自動下載。"; color: window.muted; wrapMode: Text.WordWrap; Layout.fillWidth: true; font.pixelSize: 12 }
                                CheckBox { visible: studio.preferences.performance_preset === "quality"; text: "啟用已安裝的 High Quality Correction（7B）"; checked: !!studio.preferences.quality_correction; onToggled: { studio.setPreference("quality_correction", checked); studio.selectPerformancePreset("quality") } }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text { text: "來源語言"; color: window.ink; font.pixelSize: 13; Layout.fillWidth: true }
                                    ComboBox { model: ["日文", "英文", "自動偵測"]; currentIndex: ["ja", "en", "auto"].indexOf(studio.preferences.source_language); onActivated: studio.setPreference("source_language", ["ja", "en", "auto"][currentIndex]) }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text { text: "翻譯語言"; color: window.ink; font.pixelSize: 13; Layout.fillWidth: true }
                                    ComboBox { model: ["繁體中文", "简体中文"]; currentIndex: ["zh-TW", "zh-CN"].indexOf(studio.preferences.target_language); onActivated: studio.setPreference("target_language", ["zh-TW", "zh-CN"][currentIndex]) }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text { text: "翻譯風格"; color: window.ink; font.pixelSize: 13; Layout.fillWidth: true }
                                    ComboBox { model: ["自然", "忠實", "精簡字幕"]; currentIndex: ["natural", "faithful", "minimal"].indexOf(studio.preferences.translation_style); onActivated: studio.setPreference("translation_style", ["natural", "faithful", "minimal"][currentIndex]) }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text { text: "字幕輸出內容"; color: window.ink; font.pixelSize: 13; Layout.fillWidth: true }
                                    ComboBox { model: ["只輸出譯文", "只輸出原文", "原文＋譯文"]; currentIndex: ["translation", "original", "both"].indexOf(studio.preferences.subtitle_mode); onActivated: studio.setPreference("subtitle_mode", ["translation", "original", "both"][currentIndex]) }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text { text: "音訊來源關閉時自動完成"; color: window.ink; font.pixelSize: 13; Layout.fillWidth: true }
                                    Switch { Accessible.name: "音訊來源關閉時自動完成"; checked: !!studio.preferences.auto_finalize_source_closed; onToggled: studio.setPreference("auto_finalize_source_closed", checked) }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text { text: "連續無聲自動完成"; color: window.ink; font.pixelSize: 13; Layout.fillWidth: true }
                                    ComboBox { model: ["關閉", "5 分鐘", "15 分鐘", "30 分鐘"]; currentIndex: [0, 5, 15, 30].indexOf(Number(studio.preferences.silence_timeout_minutes)); onActivated: studio.setPreference("silence_timeout_minutes", [0, 5, 15, 30][currentIndex]) }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text { text: "Session 完成後自動關閉應用程式"; color: window.ink; font.pixelSize: 13; Layout.fillWidth: true }
                                    Switch { Accessible.name: "Session 完成後關閉"; checked: !!studio.preferences.auto_close_after_finalize; onToggled: studio.setPreference("auto_close_after_finalize", checked) }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text { text: "登入 Windows 後啟動"; color: window.ink; font.pixelSize: 13; Layout.fillWidth: true }
                                    Switch { Accessible.name: "登入 Windows 後啟動"; checked: !!studio.preferences.start_with_windows; onToggled: studio.setPreference("start_with_windows", checked) }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text { text: "啟動後最小化"; color: window.ink; font.pixelSize: 13; Layout.fillWidth: true }
                                    Switch { Accessible.name: "啟動後最小化"; checked: !!studio.preferences.start_minimized; onToggled: studio.setPreference("start_minimized", checked) }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text { text: "記住上次音訊來源"; color: window.ink; font.pixelSize: 13; Layout.fillWidth: true }
                                    Switch { Accessible.name: "記住上次音訊來源"; checked: !!studio.preferences.remember_audio_source; onToggled: studio.setPreference("remember_audio_source", checked) }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text { text: "啟動後顯示 Overlay"; color: window.ink; font.pixelSize: 13; Layout.fillWidth: true }
                                    Switch { Accessible.name: "啟動時顯示 Overlay"; checked: !!studio.preferences.show_overlay_on_start; onToggled: studio.setPreference("show_overlay_on_start", checked) }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text { text: "啟動時檢查更新"; color: window.ink; font.pixelSize: 13; Layout.fillWidth: true }
                                    Switch { Accessible.name: "啟動時檢查更新"; checked: !!studio.preferences.update_checks; onToggled: studio.setPreference("update_checks", checked) }
                                    AppButton { text: "檢查更新"; onClicked: studio.checkForUpdates() }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text { text: "關閉視窗時縮到系統匣"; color: window.ink; font.pixelSize: 13; Layout.fillWidth: true }
                                    Switch { Accessible.name: "關閉視窗時縮到系統匣"; checked: !!studio.preferences.minimize_to_tray; onToggled: studio.setPreference("minimize_to_tray", checked) }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    AppButton { text: "資料資料夾"; onClicked: studio.openDataFolder() }
                                    AppButton { text: "診斷記錄"; onClicked: studio.openLogFolder() }
                                    AppButton { text: "匯出診斷"; onClicked: studio.exportDiagnostics() }
                                    AppButton { text: "清除快取 " + studio.cacheSize; enabled: !studio.componentState.busy; onClicked: studio.clearCache() }
                                }
                                Text { text: "AI 元件"; color: window.ink; font.pixelSize: 13; font.bold: true }
                                Repeater {
                                    model: [{id:"asr", title:"語音辨識", ready:studio.componentState.asr}, {id:"translation", title:"本機中文翻譯", ready:studio.componentState.translation}, {id:"diarization", title:"Speaker 分析", ready:studio.componentState.diarization}]
                                    delegate: RowLayout {
                                        required property var modelData; Layout.fillWidth: true
                                        Text { text: modelData.title + "  ·  " + (modelData.ready ? "已安裝" : "尚未安裝"); color: modelData.ready ? window.accent : window.muted; font.pixelSize: 12; Layout.fillWidth: true }
                                        AppButton { text: modelData.ready ? "修復" : "下載"; enabled: !studio.componentState.busy && !studio.audioBusy && studio.audioState !== "capturing"; onClicked: studio.installComponent(modelData.id) }
                                        AppButton { text: "驗證"; visible: modelData.ready; enabled: !studio.componentState.busy && studio.audioState !== "capturing"; onClicked: studio.verifyComponent(modelData.id) }
                                        AppButton { text: "移除"; danger: true; visible: modelData.ready; enabled: !studio.componentState.busy && !studio.audioBusy && studio.audioState !== "capturing"; onClicked: window.modelRemovalTarget = modelData.id }
                                    }
                                }
                                ProgressBar { Layout.fillWidth: true; visible: studio.componentState.busy; value: studio.componentState.percent / 100 }
                                Text { visible: !!studio.componentState.message; text: studio.componentState.message; color: window.muted; font.pixelSize: 11; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                RowLayout {
                                    Layout.fillWidth: true
                                    DarkField { id: sessionRootField; Layout.fillWidth: true; text: studio.sessionFolder; placeholderText: "Session 儲存資料夾" }
                                    AppButton { text: "套用位置"; onClicked: studio.setSessionRoot(sessionRootField.text) }
                                }
                                Rectangle { Layout.fillWidth: true; height: 1; color: window.line }
                                Text { text: "Vtuber Live Translator " + studio.appVersion + "  ·  Build " + studio.appBuild; color: window.ink; font.pixelSize: 13; font.bold: true }
                                Text { text: "隱私：音訊於本機處理，預設不保存原始音訊；逐字稿儲存在本機。診斷 ZIP 不含逐字稿、音訊、API Key 或聲紋。"; color: window.muted; font.pixelSize: 11; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                AppButton { text: studio.preferences.overlay_locked ? "解鎖 Overlay 編輯" : "鎖定 Overlay（滑鼠穿透）"; onClicked: studio.setPreference("overlay_locked", !studio.preferences.overlay_locked) }
                                Text { text: "Overlay 解鎖後可拖曳，右下角調整大小；Escape 鎖定。Ctrl+L 直播、Ctrl+H 歷史、Ctrl+O Overlay。"; color: window.muted; wrapMode: Text.WordWrap; Layout.fillWidth: true; font.pixelSize: 11 }
                                Text { text: "資料  " + studio.dataFolder + "\n記錄  " + studio.logFolder; color: window.muted; font.pixelSize: 10; wrapMode: Text.WrapAnywhere; Layout.fillWidth: true }
                                RowLayout {
                                    AppButton { text: "檢視授權"; onClicked: studio.openLicense() }
                                    AppButton { text: "開放原始碼聲明"; onClicked: studio.openOpenSourceNotices() }
                                }
                                Item { Layout.fillHeight: true }
                            }
                        }

                        InfoCard {
                            visible: window.page === "Dictionary"
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.max(360, dictionaryColumn.implicitHeight + 45)
                            ColumnLayout {
                                id: dictionaryColumn
                                anchors.fill: parent; anchors.margins: 20; spacing: 10
                                Text { text: "專有名詞詞庫"; color: window.ink; font.pixelSize: 17; font.bold: true }
                                Text { text: "原文 / 別名 → 繁體及簡體譯名；相同原文可直接覆寫。"; color: window.muted; font.pixelSize: 11 }
                                DarkField { id: glossarySource; Layout.fillWidth: true; placeholderText: "原文（例：兎田ぺこら）" }
                                DarkField { id: glossaryTw; Layout.fillWidth: true; placeholderText: "繁體譯名" }
                                DarkField { id: glossaryCn; Layout.fillWidth: true; placeholderText: "簡體譯名" }
                                DarkField { id: glossaryAliases; Layout.fillWidth: true; placeholderText: "別名，以逗號分隔（Pekora,ぺこら）" }
                                AppButton { text: "保存譯名"; primary: true; onClicked: studio.saveGlossaryEntry(glossarySource.text, glossaryTw.text, glossaryCn.text, glossaryAliases.text) }
                                Repeater {
                                    model: studio.glossaryEntries
                                    delegate: RowLayout {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        Text { text: modelData.source + "  →  " + modelData.preferred_zh_tw + " / " + modelData.preferred_zh_cn; Layout.fillWidth: true; elide: Text.ElideRight; color: window.ink; font.pixelSize: 12 }
                                        AppButton { text: "編輯"; onClicked: { glossarySource.text = modelData.source; glossaryTw.text = modelData.preferred_zh_tw; glossaryCn.text = modelData.preferred_zh_cn; glossaryAliases.text = modelData.aliases.join(",") } }
                                        AppButton { text: "刪除"; danger: true; onClicked: studio.deleteGlossaryEntry(modelData.source) }
                                    }
                                }
                                DarkField { id: glossaryPath; Layout.fillWidth: true; text: studio.glossaryDefaultExportPath; placeholderText: "匯入／匯出 JSON 檔案完整路徑" }
                                RowLayout {
                                    AppButton { text: "匯入 JSON"; onClicked: studio.importGlossary(glossaryPath.text) }
                                    AppButton { text: "匯出 JSON"; onClicked: studio.exportGlossary(glossaryPath.text) }
                                }
                            }
                        }
                        InfoCard {
                            visible: window.page === "Speakers"
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.max(250, speakerColumn.implicitHeight + 42)
                            ColumnLayout {
                                id: speakerColumn
                                anchors.fill: parent; anchors.margins: 20; spacing: 12
                                Text { text: "Speaker 管理"; color: window.ink; font.pixelSize: 17; font.bold: true }
                                Text { text: "Detected Speaker 為音訊分組；Confirmed Identity 為您手動確認的身分，模型分組不代表人物已確認。"; color: window.muted; font.pixelSize: 11; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                Flow {
                                    Layout.fillWidth: true; spacing: 8
                                    DarkField { id: unknownStart; width: 100; text: "00:00:00"; placeholderText: "開始時間" }
                                    DarkField { id: unknownEnd; width: 100; text: "00:05:00"; placeholderText: "結束時間" }
                                    ComboBox { id: unknownTarget; width: 150; model: studio.speakers; textRole: "display_name"; valueRole: "speaker_id" }
                                    AppButton { text: "指定此範圍 Unknown"; enabled: studio.speakers.length > 0; onClicked: studio.assignUnknownRange(unknownStart.text, unknownEnd.text, String(unknownTarget.currentValue)) }
                                }
                                Text { visible: studio.speakers.length === 0; text: "尚未偵測到說話者。"; color: window.muted; font.pixelSize: 13 }
                                Repeater {
                                    model: studio.speakers
                                    delegate: Rectangle {
                                        required property var modelData
                                        Layout.fillWidth: true; implicitHeight: speakerFields.implicitHeight + 24
                                        radius: 10; color: window.raised; border.color: window.line
                                        ColumnLayout {
                                            id: speakerFields
                                            anchors.fill: parent; anchors.margins: 12; spacing: 7
                                            RowLayout {
                                                Layout.fillWidth: true
                                                Text { text: modelData.speaker_id; color: window.accent; font.pixelSize: 12; font.bold: true }
                                                Item { Layout.fillWidth: true }
                                                Text { text: modelData.segment_count + " segments"; color: window.muted; font.pixelSize: 11 }
                                            }
                                            RowLayout {
                                                Layout.fillWidth: true
                                                DarkField { id: speakerName; Layout.fillWidth: true; text: modelData.display_name; placeholderText: "顯示名稱" }
                                                AppButton { text: "改名"; onClicked: studio.renameSpeaker(modelData.speaker_id, speakerName.text) }
                                            }
                                            RowLayout {
                                                Layout.fillWidth: true
                                                DarkField { id: personId; Layout.fillWidth: true; text: modelData.person_id || ""; placeholderText: "person_id（選填）" }
                                                AppButton { text: "確認身分"; onClicked: studio.mapSpeakerPerson(modelData.speaker_id, personId.text) }
                                            }
                                        }
                                    }
                                }
                                RowLayout {
                                    visible: studio.speakers.length > 1
                                    Text { text: "合併"; color: window.muted; font.pixelSize: 12 }
                                    ComboBox { id: mergeFrom; Layout.preferredWidth: 180; model: studio.speakers.map(s => s.speaker_id) }
                                    Text { text: "→"; color: window.muted }
                                    ComboBox {
                                        id: mergeTo
                                        Layout.preferredWidth: 180
                                        model: ["選擇目標"].concat(studio.speakers.map(s => s.speaker_id))
                                    }
                                    AppButton {
                                        text: "合併 Speaker"
                                        enabled: mergeTo.currentIndex > 0 && mergeFrom.currentText !== mergeTo.currentText
                                        onClicked: studio.mergeSpeakers(mergeFrom.currentText, mergeTo.currentText)
                                    }
                                }
                            }
                        }
                        InfoCard {
                            visible: window.page === "Exports"
                            Layout.fillWidth: true; Layout.preferredHeight: Math.max(310, exportColumn.implicitHeight + 44)
                            ColumnLayout {
                                id: exportColumn
                                anchors.fill: parent; anchors.margins: 22; spacing: 12
                                Text { text: "最終輸出"; color: window.ink; font.pixelSize: 17; font.bold: true }
                                Text { text: "輸出是 SQLite 與 transcript.json 的可重建視圖；Speaker 編輯後可重新產生。"; color: window.muted; font.pixelSize: 12; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text { text: "SRT / VTT 內容"; color: window.ink; font.pixelSize: 12; Layout.fillWidth: true }
                                    ComboBox { model: ["譯文", "原文", "原文＋譯文"]; currentIndex: ["translation", "original", "both"].indexOf(studio.preferences.subtitle_mode); onActivated: studio.setPreference("subtitle_mode", ["translation", "original", "both"][currentIndex]) }
                                }
                                Repeater {
                                    model: [
                                        {label: "Markdown", value: studio.exportPaths.markdown || "尚未選擇 Session"},
                                        {label: "SRT", value: studio.exportPaths.srt || "—"},
                                        {label: "VTT", value: studio.exportPaths.vtt || "—"},
                                        {label: "Source JSON", value: studio.exportPaths.json || "—"}
                                    ]
                                    delegate: RowLayout {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        Text { text: modelData.label; color: window.accent; font.pixelSize: 11; font.bold: true; Layout.preferredWidth: 90 }
                                        Text { text: modelData.value; color: window.muted; font.pixelSize: 11; elide: Text.ElideMiddle; Layout.fillWidth: true }
                                        AppButton { text: "複製路徑"; enabled: !!studio.selectedSession.session_id; onClicked: studio.copyPath(modelData.value) }
                                    }
                                }
                                RowLayout {
                                    AppButton { text: "重新輸出"; primary: true; enabled: !!studio.selectedSession.session_id; onClicked: studio.exportCurrentSession() }
                                    AppButton { text: "開啟 Session 資料夾"; enabled: !!studio.selectedSession.session_id; onClicked: studio.openSessionFolder() }
                                }
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.preferredWidth: 295
                    Layout.fillHeight: true
                    color: "#161c25"
                    border.color: window.line
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 20; spacing: 17
                        Text { text: "Session 詳細資料"; color: window.muted; font.pixelSize: 11; font.bold: true; font.letterSpacing: 1.8 }
                        InfoCard {
                            Layout.fillWidth: true; Layout.preferredHeight: 145
                            ColumnLayout {
                                anchors.fill: parent; anchors.margins: 15; spacing: 7
                                Text { text: "目前 Session"; color: "#78919d"; font.pixelSize: 10; font.bold: true; font.letterSpacing: 1 }
                                Text { text: studio.selectedSession.title || "尚未選擇"; color: window.ink; font.pixelSize: 17; font.bold: true; elide: Text.ElideRight; Layout.fillWidth: true }
                                Text { text: studio.selectedSession.session_id ? "ID  " + studio.selectedSession.session_id.slice(0, 8) : "從 LIVE 建立空白 Session"; color: window.muted; font.pixelSize: 11 }
                                Text { text: studio.selectedSession.status ? studio.selectedSession.status.toUpperCase() : "—"; color: window.accent; font.pixelSize: 10; font.bold: true }
                            }
                        }
                        InfoCard {
                            Layout.fillWidth: true; Layout.preferredHeight: 260
                            ColumnLayout {
                                anchors.fill: parent; anchors.margins: 15; spacing: 10
                                Text { text: "辨識設定"; color: "#78919d"; font.pixelSize: 10; font.bold: true; font.letterSpacing: 1 }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text { text: "來源語言"; color: window.ink; font.pixelSize: 12; Layout.fillWidth: true }
                                    ComboBox {
                                        id: liveLanguagePicker
                                        Layout.preferredWidth: 130
                                        model: ["自動偵測", "日文", "英文"]
                                        currentIndex: ["auto", "ja", "en"].indexOf(studio.preferences.source_language)
                                        onActivated: studio.setPreference("source_language", ["auto", "ja", "en"][currentIndex])
                                    }
                                }
                                Text { visible: studio.preferences.source_language === "auto" && !!studio.detectedLanguage; text: "偵測結果     " + window.languageName(studio.detectedLanguage); color: window.accent; font.pixelSize: 11 }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text { text: "目標語言"; color: window.ink; font.pixelSize: 12; Layout.fillWidth: true }
                                    ComboBox { Layout.preferredWidth: 130; model: ["繁體中文", "简体中文"]; currentIndex: ["zh-TW", "zh-CN"].indexOf(studio.preferences.target_language); onActivated: studio.setPreference("target_language", ["zh-TW", "zh-CN"][currentIndex]) }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text { text: "翻譯風格"; color: window.ink; font.pixelSize: 12; Layout.fillWidth: true }
                                    ComboBox { Layout.preferredWidth: 130; model: ["自然", "忠實", "精簡字幕"]; currentIndex: ["natural", "faithful", "minimal"].indexOf(studio.preferences.translation_style); onActivated: studio.setPreference("translation_style", ["natural", "faithful", "minimal"][currentIndex]) }
                                }
                                Text { text: "音訊來源     " + (studio.audioState === "capturing" ? "監聽中" : "未監聽"); color: window.muted; font.pixelSize: 12 }
                            }
                        }
                        Text { text: "OVERLAY"; color: window.muted; font.pixelSize: 11; font.bold: true; font.letterSpacing: 1.8 }
                        ComboBox {
                            Layout.fillWidth: true
                            model: ["Gaming · 翻譯與 Speaker", "Watching · 翻譯與原文", "Minimal · 只顯示翻譯"]
                            currentIndex: ["gaming", "watching", "minimal"].indexOf(studio.preferences.overlay_mode)
                            onActivated: studio.setPreference("overlay_mode", ["gaming", "watching", "minimal"][currentIndex])
                        }
                        InfoCard {
                            Layout.fillWidth: true; Layout.preferredHeight: 90
                            RowLayout {
                                anchors.fill: parent; anchors.margins: 15
                                Column {
                                    spacing: 5
                                    Text { text: "畫面預覽"; color: window.ink; font.pixelSize: 13; font.bold: true }
                                    Text { text: studio.overlayVisible ? "顯示中 · 滑鼠穿透" : "已隱藏"; color: window.muted; font.pixelSize: 11 }
                                }
                                Item { Layout.fillWidth: true }
                                Switch { checked: studio.overlayVisible; onClicked: studio.toggleOverlay() }
                            }
                        }
                        Item { Layout.fillHeight: true }
                        AppButton { Layout.fillWidth: true; text: "開啟 Session 資料夾"; enabled: !!studio.selectedSession.session_id; onClicked: studio.openSessionFolder() }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true; Layout.preferredHeight: 55
                color: "#171d25"; border.color: window.line
                RowLayout {
                    anchors.fill: parent; anchors.leftMargin: 29; anchors.rightMargin: 23; spacing: 13
                    Rectangle { width: 7; height: 7; radius: 4; color: studio.asrState === "live" ? window.accent : "#e6b865" }
                    Text { text: studio.audioState === "capturing" ? "AUDIO LIVE  ·  ASR " + studio.asrState.toUpperCase() + "  ·  " + studio.asrStatus + "  ·  " + studio.translationStatus + "  ·  " + studio.diarizationStatus + (studio.asrLatency ? "  ·  " + studio.asrLatency : "") + (studio.translationLatency ? "  ·  " + studio.translationLatency : "") : studio.message; color: "#a7b4c3"; font.pixelSize: 11; elide: Text.ElideRight; Layout.fillWidth: true }
                    AppButton { text: studio.finalizing ? "正在完成…" : "結束 Session"; danger: true; enabled: studio.selectedSession.status === "active" && !studio.finalizing; onClicked: studio.finishSession() }
                }
            }
        }
    }

    Rectangle {
        anchors.fill: parent
        visible: !studio.firstRunComplete
        z: 1000
        color: window.bg
        Rectangle {
            width: Math.min(parent.width - 80, 860)
            height: Math.min(parent.height - (parent.height < 650 ? 20 : 70), 680)
            anchors.centerIn: parent
            radius: 22
            color: window.panel
            border.color: window.line
            ColumnLayout {
                anchors.fill: parent; anchors.margins: parent.height < 600 ? 20 : 34; spacing: parent.height < 600 ? 10 : 18
                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "VTUBER LIVE TRANSLATOR"; color: window.accent; font.bold: true; font.pixelSize: 12; font.letterSpacing: 2 }
                    Item { Layout.fillWidth: true }
                    Text { text: (window.firstRunPage + 1) + " / 5"; color: window.muted; font.pixelSize: 12 }
                }
                Rectangle { Layout.fillWidth: true; height: 1; color: window.line }
                ColumnLayout {
                    visible: window.firstRunPage === 0; Layout.fillWidth: true; Layout.fillHeight: true; spacing: 14
                    Item { Layout.fillHeight: true }
                    Text { text: "歡迎使用"; color: window.ink; font.pixelSize: 38; font.bold: true }
                    Text { text: "把指定 Windows 程式的聲音，轉成即時原文與中文字幕。\n音訊只在記憶體中處理，不會保存原始錄音。"; color: window.muted; font.pixelSize: 16; lineHeight: 1.5 }
                    Text { text: "翻譯成"; color: window.ink; font.pixelSize: 14; font.bold: true }
                    RowLayout {
                        AppButton { text: "繁體中文"; primary: studio.preferences.target_language === "zh-TW"; onClicked: studio.setPreference("target_language", "zh-TW") }
                        AppButton { text: "简体中文"; primary: studio.preferences.target_language === "zh-CN"; onClicked: studio.setPreference("target_language", "zh-CN") }
                    }
                    Item { Layout.fillHeight: true }
                }
                ColumnLayout {
                    visible: window.firstRunPage === 1; Layout.fillWidth: true; Layout.fillHeight: true; spacing: 14
                    Text { text: "選擇效能模式"; color: window.ink; font.pixelSize: 28; font.bold: true }
                    Text { text: "已偵測 " + studio.hardwareProfile.logical_cores + " 執行緒 · " + studio.hardwareProfile.ram_gb + " GB RAM\n" + studio.hardwareProfile.gpu; color: window.muted; font.pixelSize: 14; lineHeight: 1.45 }
                    Repeater {
                        model: [{id:"gaming", title:"Gaming", body:"優先保留遊戲效能；2 CPU threads、base ASR、1.5B 翻譯。"}, {id:"balanced", title:"Balanced", body:"日常直播建議；4 CPU threads、自動選擇裝置、1.5B 翻譯。"}, {id:"quality", title:"High Quality", body:"small ASR 在日英測試語料較準；首次監聽另下載約 460 MB，無 GPU 時可能較慢。7B 修正預設關閉；於設定選用額外約需 5 GB RAM。"}]
                        delegate: Rectangle {
                            required property var modelData; Layout.fillWidth: true; height: Math.max(78, presetText.implicitHeight + 28); radius: 12
                            activeFocusOnTab: true
                            Accessible.role: Accessible.Button
                            Accessible.name: modelData.title
                            Keys.onReturnPressed: studio.selectPerformancePreset(modelData.id)
                            Keys.onSpacePressed: studio.selectPerformancePreset(modelData.id)
                            color: studio.preferences.performance_preset === modelData.id ? "#263d3c" : window.raised
                            border.color: activeFocus || studio.preferences.performance_preset === modelData.id ? window.accent : window.line
                            border.width: activeFocus ? 2 : 1
                            Column { id: presetText; anchors.fill: parent; anchors.margins: 14; spacing: 5
                                Text { text: modelData.title + (studio.hardwareProfile.recommended === modelData.id ? "  ·  建議" : ""); color: window.ink; font.pixelSize: 15; font.bold: true }
                                Text { text: modelData.body; color: window.muted; font.pixelSize: 12; width: parent.width; wrapMode: Text.WordWrap }
                            }
                            MouseArea { anchors.fill: parent; onClicked: studio.selectPerformancePreset(modelData.id) }
                        }
                    }
                    Item { Layout.fillHeight: true }
                }
                ColumnLayout {
                    visible: window.firstRunPage === 2; Layout.fillWidth: true; Layout.fillHeight: true; spacing: 13
                    Text { text: "準備 AI 元件"; color: window.ink; font.pixelSize: 28; font.bold: true }
                    Text { text: "模型只需下載一次，可中斷後續傳。開始前會檢查磁碟空間與檔案雜湊。"; color: window.muted; font.pixelSize: 13 }
                    Repeater {
                        model: [{id:"asr", title:"語音辨識", ready:studio.componentState.asr}, {id:"translation", title:"本機中文翻譯", ready:studio.componentState.translation}, {id:"diarization", title:"Speaker 分析", ready:studio.componentState.diarization}]
                        delegate: Rectangle {
                            required property var modelData; Layout.fillWidth: true; height: 68; radius: 11; color: window.raised; border.color: window.line
                            RowLayout { anchors.fill: parent; anchors.margins: 13
                                Text { text: modelData.title; color: window.ink; font.pixelSize: 14; font.bold: true; Layout.fillWidth: true }
                                Text { text: modelData.ready ? "已就緒" : "尚未安裝"; color: modelData.ready ? window.accent : "#dfbd82"; font.pixelSize: 12 }
                                AppButton { text: modelData.ready ? "重新檢查" : "下載"; enabled: !studio.componentState.busy && !studio.audioBusy && studio.audioState !== "capturing"; onClicked: studio.installComponent(modelData.id) }
                            }
                        }
                    }
                    ProgressBar { Layout.fillWidth: true; visible: studio.componentState.busy; value: studio.componentState.percent / 100 }
                    Text { text: studio.componentState.message || "ASR 與翻譯為主要元件；Speaker 分析可稍後安裝。"; color: window.muted; font.pixelSize: 12; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                    Item { Layout.fillHeight: true }
                }
                ColumnLayout {
                    visible: window.firstRunPage === 3; Layout.fillWidth: true; Layout.fillHeight: true; spacing: 14
                    Text { text: "測試程式音訊"; color: window.ink; font.pixelSize: 28; font.bold: true }
                    Text { text: "請先讓瀏覽器或直播程式播放聲音，再選擇來源。"; color: window.muted; font.pixelSize: 13 }
                    ComboBox { Layout.fillWidth: true; model: studio.audioSources; textRole: "display"; onActivated: studio.selectAudioSource(studio.audioSources[currentIndex].id) }
                    RowLayout {
                        AppButton { text: "重新偵測"; onClicked: studio.refreshAudioSources() }
                        AppButton { text: studio.audioState === "capturing" ? "停止測試" : "開始測試"; primary: true; onClicked: studio.audioState === "capturing" ? studio.stopAudioCapture() : studio.startAudioTest() }
                    }
                    Rectangle { Layout.fillWidth: true; height: 18; radius: 9; color: window.raised; Rectangle { height: parent.height; width: parent.width * Math.min(1, studio.audioPeak * 5); radius: 9; color: window.accent } }
                    Text { text: studio.audioStatus; color: window.muted; font.pixelSize: 12 }
                    Item { Layout.fillHeight: true }
                }
                ColumnLayout {
                    visible: window.firstRunPage === 4; Layout.fillWidth: true; Layout.fillHeight: true; spacing: 16
                    Item { Layout.fillHeight: true }
                    Text { text: "準備完成"; color: window.ink; font.pixelSize: 36; font.bold: true }
                    Text { text: "之後可以在設定中切換效能模式、管理快取與開啟診斷記錄。\n建立 Session、選擇音訊來源，便可開始。"; color: window.muted; font.pixelSize: 15; lineHeight: 1.5 }
                    Text { text: "資料位置  " + studio.dataFolder; color: window.accent; font.pixelSize: 12; wrapMode: Text.WrapAnywhere; Layout.fillWidth: true }
                    Item { Layout.fillHeight: true }
                }
                RowLayout {
                    Layout.fillWidth: true
                    AppButton { text: "上一步"; visible: window.firstRunPage > 0; onClicked: window.firstRunPage-- }
                    Item { Layout.fillWidth: true }
                    AppButton { text: window.firstRunPage === 4 ? "開始使用" : "下一步"; primary: true; enabled: !studio.componentState.busy && (window.firstRunPage !== 2 || (studio.componentState.asr && studio.componentState.translation)); onClicked: { if (window.firstRunPage === 4) studio.completeFirstRun(); else window.firstRunPage++ } }
                }
            }
        }
    }
    Rectangle {
        anchors.fill: parent; visible: window.modelRemovalTarget !== ""; z: 1200; color: "#aa080b10"
        Rectangle {
            width: 470; height: 220; anchors.centerIn: parent; radius: 18; color: window.panel; border.color: window.line
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 24; spacing: 13
                Text { text: "移除 AI 元件？"; color: window.ink; font.pixelSize: 18; font.bold: true }
                Text { text: "移除後對應功能會停止，已保存的 Session 與逐字稿不受影響。之後可以重新下載。"; color: window.muted; font.pixelSize: 13; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                Item { Layout.fillHeight: true }
                RowLayout {
                    Layout.fillWidth: true; Item { Layout.fillWidth: true }
                    AppButton { text: "取消"; onClicked: window.modelRemovalTarget = "" }
                    AppButton { text: "移除"; danger: true; onClicked: { var target = window.modelRemovalTarget; window.modelRemovalTarget = ""; studio.removeComponent(target) } }
                }
            }
        }
    }
    Rectangle {
        anchors.fill: parent; visible: window.trayPromptVisible; z: 1100; color: "#aa080b10"
        Rectangle {
            width: 470; height: 210; anchors.centerIn: parent; radius: 18; color: window.panel; border.color: window.line
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 24; spacing: 13
                Text { text: "應用程式仍會在系統匣執行"; color: window.ink; font.pixelSize: 18; font.bold: true }
                Text { text: "音訊與字幕處理會繼續。可從系統匣圖示重新開啟或完整結束。"; color: window.muted; font.pixelSize: 12; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                Item { Layout.fillHeight: true }
                RowLayout {
                    Layout.fillWidth: true
                    AppButton { text: "完整結束"; onClicked: { studio.setPreference("minimize_to_tray", false); studio.quitApplication() } }
                    Item { Layout.fillWidth: true }
                    AppButton { text: "縮小到系統匣"; primary: true; onClicked: { studio.setPreference("tray_prompt_seen", true); window.trayPromptVisible = false; window.hide() } }
                }
            }
        }
    }
}
