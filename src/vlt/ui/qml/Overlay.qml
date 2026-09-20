import QtQuick
import QtQuick.Window

Window {
    id: overlay
    width: Math.min(Screen.width * 0.58, 850)
    height: 112
    x: (Screen.width - width) / 2
    y: Screen.height - height - 70
    visible: studio.overlayVisible
    color: "transparent"
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowTransparentForInput | Qt.Tool
    title: "字幕 Overlay 預覽"

    Rectangle {
        anchors.fill: parent
        radius: 22
        color: "#e51b202b"
        border.color: "#516475"
        border.width: 1

        Column {
            anchors.centerIn: parent
            spacing: 8
            Text {
                text: "OVERLAY PREVIEW"
                color: "#62dfc2"
                font.pixelSize: 11
                font.bold: true
                font.letterSpacing: 2
                anchors.horizontalCenter: parent.horizontalCenter
            }
            Text {
                text: "即時字幕會顯示在這裡"
                color: "#f0f3f7"
                font.pixelSize: 23
                font.bold: true
                anchors.horizontalCenter: parent.horizontalCenter
            }
        }
    }
}

