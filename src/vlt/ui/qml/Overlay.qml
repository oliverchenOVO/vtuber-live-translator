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
    minimumWidth: 320
    minimumHeight: 100
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool |
           (studio.preferences.overlay_locked ? Qt.WindowTransparentForInput : 0)
    title: "即時翻譯 Overlay"

    Rectangle {
        anchors.fill: parent
        radius: 22
        color: Qt.rgba(0.106, 0.125, 0.169, studio.preferences.overlay_opacity)
        border.color: "#516475"
        border.width: 1

        Column {
            anchors.centerIn: parent
            width: parent.width - 56
            spacing: 7
            Text {
                visible: studio.preferences.overlay_mode !== "minimal" && !!studio.overlaySegment.show_speaker
                text: studio.overlaySegment.speaker_display_name + (studio.overlaySegment.speaker_new ? "  ·  NEW" : "")
                color: studio.overlaySegment.speaker_color || "#62dfc2"
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
    MouseArea {
        anchors.fill: parent
        enabled: !studio.preferences.overlay_locked
        cursorShape: Qt.SizeAllCursor
        onPressed: overlay.startSystemMove()
    }
    Rectangle {
        visible: !studio.preferences.overlay_locked
        anchors.right: parent.right; anchors.bottom: parent.bottom
        width: 24; height: 24; radius: 4; color: "#6ce2c5"
        MouseArea {
            anchors.fill: parent; cursorShape: Qt.SizeFDiagCursor
            onPressed: overlay.startSystemResize(Qt.RightEdge | Qt.BottomEdge)
        }
    }
    Shortcut {
        sequence: "Escape"
        enabled: !studio.preferences.overlay_locked
        onActivated: studio.setPreference("overlay_locked", true)
    }
}
