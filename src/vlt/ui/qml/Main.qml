import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    visible: true
    width: 1380
    height: 830
    minimumWidth: 1050
    minimumHeight: 680
    title: "Vtuber Live Translator — Transcript Studio"
    color: "#101319"

    property string page: "LIVE"
    property color bg: "#101319"
    property color panel: "#181d26"
    property color raised: "#202733"
    property color line: "#303947"
    property color muted: "#8e9bab"
    property color ink: "#eef2f6"
    property color accent: "#6ce2c5"

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
            border.color: control.primary ? "transparent" : window.line
            Behavior on color { ColorAnimation { duration: 140 } }
        }
    }

    component InfoCard: Rectangle {
        radius: 17
        color: window.panel
        border.color: window.line
        border.width: 1
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
                Text { text: "WORKSPACE"; color: "#68788d"; font.pixelSize: 10; font.bold: true; font.letterSpacing: 1.7; Layout.bottomMargin: 7 }
                Repeater {
                    model: [
                        {name: "LIVE", icon: "◉"}, {name: "History", icon: "▤"},
                        {name: "Speakers", icon: "◌"}, {name: "Dictionary", icon: "▦"},
                        {name: "Exports", icon: "↗"}, {name: "Settings", icon: "⚙"}
                    ]
                    delegate: Rectangle {
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.maximumWidth: 178
                        height: 43
                        radius: 10
                        color: window.page === modelData.name ? "#263d3c" : navMouse.containsMouse ? "#222b37" : "transparent"
                        border.color: window.page === modelData.name ? "#3d6961" : "transparent"
                        Behavior on color { ColorAnimation { duration: 130 } }
                        Row {
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.left: parent.left
                            anchors.leftMargin: 13
                            spacing: 13
                            Text { text: modelData.icon; color: window.page === modelData.name ? window.accent : window.muted; font.pixelSize: 18; width: 19 }
                            Text { text: modelData.name; color: window.page === modelData.name ? window.ink : "#adbac8"; font.pixelSize: 13; font.bold: window.page === modelData.name }
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
                        Text { text: "●  PHASE 1"; color: window.accent; font.pixelSize: 11; font.bold: true; font.letterSpacing: 1 }
                        Text { text: "Studio 基礎版本"; color: window.ink; font.pixelSize: 13; font.bold: true }
                        Text { text: "音訊與翻譯功能開發中"; color: window.muted; font.pixelSize: 11; width: 150; wrapMode: Text.WordWrap }
                    }
                }
                Text { text: "v0.1.0  ·  Windows preview"; color: "#647185"; font.pixelSize: 10; Layout.topMargin: 9 }
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
                Rectangle { width: 7; height: 7; radius: 4; color: "#e6b865" }
                Text { text: "功能建置中"; color: "#d7c298"; font.pixelSize: 12 }
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
                                text: window.page === "LIVE" ? "Live transcript" : window.page
                                color: window.ink; font.pixelSize: 29; font.bold: true
                            }
                            Item { Layout.fillWidth: true }
                            Text {
                                visible: window.page === "LIVE"
                                text: "●  OFFLINE"
                                color: "#dfbd82"; font.pixelSize: 11; font.bold: true; font.letterSpacing: 1
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            text: window.page === "LIVE" ? "一切對話，清楚留下。" :
                                  window.page === "History" ? "查看已建立的直播記錄。" :
                                  window.page === "Settings" ? "設定字幕顯示與未來的翻譯偏好。" :
                                  "此區域將隨後續階段開放。"
                            color: window.muted; font.pixelSize: 13
                        }

                        InfoCard {
                            visible: window.page === "LIVE"
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
                                    Text { text: "目前可建立與管理空白 Session，預覽字幕 Overlay。"; color: "#a5b8ba"; font.pixelSize: 12; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                    Text { text: "指定程式音訊、辨識與翻譯將於後續階段提供。"; color: "#82a19f"; font.pixelSize: 11; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                }
                            }
                        }

                        RowLayout {
                            visible: window.page === "LIVE"
                            spacing: 10
                            AppButton { text: "＋  建立空白 Session"; primary: true; onClicked: studio.createSession() }
                            AppButton { text: studio.overlayVisible ? "隱藏 Overlay" : "預覽 Overlay"; onClicked: studio.toggleOverlay() }
                        }

                        InfoCard {
                            visible: window.page === "LIVE"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 290
                            ColumnLayout {
                                anchors.fill: parent; anchors.margins: 24; spacing: 13
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text { text: "逐字稿"; color: window.ink; font.pixelSize: 16; font.bold: true }
                                    Item { Layout.fillWidth: true }
                                    Text { text: "SESSION VIEW"; color: "#607287"; font.pixelSize: 10; font.bold: true; font.letterSpacing: 1.4 }
                                }
                                Rectangle { Layout.fillWidth: true; height: 1; color: window.line }
                                Item { Layout.fillHeight: true }
                                Rectangle {
                                    Layout.alignment: Qt.AlignHCenter
                                    width: 58; height: 58; radius: 18; color: "#26313e"
                                    Text { anchors.centerIn: parent; text: "≋"; color: "#728b9a"; font.pixelSize: 33 }
                                }
                                Text { Layout.alignment: Qt.AlignHCenter; text: "尚無對話內容"; color: window.ink; font.pixelSize: 15; font.bold: true }
                                Text { Layout.alignment: Qt.AlignHCenter; text: "即時辨識功能完成後，內容將依時間出現在這裡。"; color: window.muted; font.pixelSize: 12 }
                                Item { Layout.fillHeight: true }
                            }
                        }

                        InfoCard {
                            visible: window.page === "History"
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.max(150, historyColumn.implicitHeight + 38)
                            ColumnLayout {
                                id: historyColumn
                                anchors.fill: parent; anchors.margins: 18; spacing: 9
                                Text { visible: studio.history.length === 0; text: "尚未建立 Session。可從 LIVE 建立空白 Session。"; color: window.muted; font.pixelSize: 13 }
                                Repeater {
                                    model: studio.history
                                    delegate: Rectangle {
                                        required property var modelData
                                        Layout.fillWidth: true; height: 65; radius: 10
                                        color: historyMouse.containsMouse ? "#293443" : window.raised
                                        border.color: window.line
                                        RowLayout {
                                            anchors.fill: parent; anchors.margins: 14
                                            ColumnLayout {
                                                Layout.fillWidth: true; spacing: 5
                                                Text { text: modelData.title; color: window.ink; font.pixelSize: 14; font.bold: true }
                                                Text { text: modelData.created_at + "  ·  " + modelData.session_id.slice(0, 8); color: window.muted; font.pixelSize: 11 }
                                            }
                                            Text { text: modelData.status.toUpperCase(); color: modelData.status === "completed" ? window.accent : "#e6bc79"; font.pixelSize: 10; font.bold: true }
                                        }
                                        MouseArea { id: historyMouse; anchors.fill: parent; hoverEnabled: true; onClicked: studio.selectSession(modelData.session_id) }
                                    }
                                }
                            }
                        }

                        InfoCard {
                            visible: window.page === "Settings"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 335
                            ColumnLayout {
                                anchors.fill: parent; anchors.margins: 24; spacing: 17
                                Text { text: "偏好設定"; color: window.ink; font.pixelSize: 17; font.bold: true }
                                Text { text: "設定會立即保存在本機。"; color: window.muted; font.pixelSize: 12 }
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
                                Rectangle { Layout.fillWidth: true; height: 1; color: window.line }
                                Text { text: "原始音訊預設不保存。音訊設定將於擷取功能完成後開放。"; color: window.muted; font.pixelSize: 11; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                Item { Layout.fillHeight: true }
                            }
                        }

                        InfoCard {
                            visible: window.page === "Speakers" || window.page === "Dictionary" || window.page === "Exports"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 220
                            Column {
                                anchors.centerIn: parent; spacing: 12
                                Text { text: "◌"; anchors.horizontalCenter: parent.horizontalCenter; color: window.accent; font.pixelSize: 35 }
                                Text { text: "此功能尚未開放"; anchors.horizontalCenter: parent.horizontalCenter; color: window.ink; font.pixelSize: 17; font.bold: true }
                                Text { text: "完成核心資料與音訊管線後會在這裡提供。"; color: window.muted; font.pixelSize: 12 }
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
                        Text { text: "SESSION DETAILS"; color: window.muted; font.pixelSize: 11; font.bold: true; font.letterSpacing: 1.8 }
                        InfoCard {
                            Layout.fillWidth: true; Layout.preferredHeight: 145
                            ColumnLayout {
                                anchors.fill: parent; anchors.margins: 15; spacing: 7
                                Text { text: "CURRENT SESSION"; color: "#78919d"; font.pixelSize: 10; font.bold: true; font.letterSpacing: 1 }
                                Text { text: studio.selectedSession.title || "尚未選擇"; color: window.ink; font.pixelSize: 17; font.bold: true; elide: Text.ElideRight; Layout.fillWidth: true }
                                Text { text: studio.selectedSession.session_id ? "ID  " + studio.selectedSession.session_id.slice(0, 8) : "從 LIVE 建立空白 Session"; color: window.muted; font.pixelSize: 11 }
                                Text { text: studio.selectedSession.status ? studio.selectedSession.status.toUpperCase() : "—"; color: window.accent; font.pixelSize: 10; font.bold: true }
                            }
                        }
                        InfoCard {
                            Layout.fillWidth: true; Layout.preferredHeight: 183
                            ColumnLayout {
                                anchors.fill: parent; anchors.margins: 15; spacing: 10
                                Text { text: "TRANSLATION SETUP"; color: "#78919d"; font.pixelSize: 10; font.bold: true; font.letterSpacing: 1 }
                                Text { text: "來源語言     " + (studio.preferences.source_language === "ja" ? "日文" : studio.preferences.source_language === "en" ? "英文" : "自動偵測"); color: window.ink; font.pixelSize: 12 }
                                Text { text: "目標語言     " + (studio.preferences.target_language === "zh-TW" ? "繁體中文" : "简体中文"); color: window.ink; font.pixelSize: 12 }
                                Text { text: "翻譯模式     " + studio.preferences.translation_style; color: window.ink; font.pixelSize: 12 }
                                Text { text: "音訊來源     尚未接入"; color: window.muted; font.pixelSize: 12 }
                            }
                        }
                        Text { text: "OVERLAY"; color: window.muted; font.pixelSize: 11; font.bold: true; font.letterSpacing: 1.8 }
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
                    Rectangle { width: 7; height: 7; radius: 4; color: "#e6b865" }
                    Text { text: studio.message; color: "#a7b4c3"; font.pixelSize: 11; elide: Text.ElideRight; Layout.fillWidth: true }
                    AppButton { text: "結束 Session"; danger: true; enabled: studio.selectedSession.status === "active"; onClicked: studio.finishSession() }
                }
            }
        }
    }
}
