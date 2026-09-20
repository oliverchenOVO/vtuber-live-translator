import QtQuick
import QtQuick.Window

Window {
    id: overlay
    width: Math.min(Screen.width * 0.58, 850)
    height: studio.preferences.overlay_mode === "watching" ? 152 : 112
    x: (Screen.width - width) / 2
    y: Screen.height - height - 70
    visible: studio.overlayVisible
    color: "transparent"
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowTransparentForInput | Qt.Tool
    title: "即時翻譯 Overlay"

    Rectangle {
        anchors.fill: parent
        radius: 22
        color: "#e51b202b"
        border.color: "#516475"
        border.width: 1

        Column {
            anchors.centerIn: parent
            width: parent.width - 56
            spacing: 7
            Text {
                visible: studio.preferences.overlay_mode === "gaming"
                text: "speaker_001"
                color: "#62dfc2"
                font.pixelSize: 11
                font.bold: true
                anchors.horizontalCenter: parent.horizontalCenter
            }
            Text {
                text: studio.overlaySegment.translation ? studio.overlaySegment.translation.text : "正在等待翻譯…"
                color: "#f0f3f7"
                font.pixelSize: studio.preferences.overlay_mode === "minimal" ? 25 : 22
                font.bold: true
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                maximumLineCount: 2
                elide: Text.ElideRight
            }
            Text {
                visible: studio.preferences.overlay_mode === "watching" && !!studio.overlaySegment.original
                text: studio.overlaySegment.original || ""
                color: "#afbdca"
                font.pixelSize: 15
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                maximumLineCount: 2
                elide: Text.ElideRight
                anchors.horizontalCenter: parent.horizontalCenter
            }
        }
    }
}
