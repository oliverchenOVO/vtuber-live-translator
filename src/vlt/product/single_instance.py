from __future__ import annotations

import re
import tempfile
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance(QObject):
    activateRequested = Signal()

    def __init__(self, name: str = "VtuberLiveTranslator-1"):
        super().__init__()
        self.name = name
        safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
        self.lock = QLockFile(str(Path(tempfile.gettempdir()) / f"{safe_name}.lock"))
        self.lock.setStaleLockTime(0)
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._activated)

    def acquire(self) -> bool:
        if self.lock.tryLock(0):
            QLocalServer.removeServer(self.name)
            if self.server.listen(self.name):
                return True
            self.lock.unlock()
            return False
        probe = QLocalSocket()
        probe.connectToServer(self.name)
        if probe.waitForConnected(500):
            probe.write(b"activate")
            probe.waitForBytesWritten(500)
            probe.disconnectFromServer()
            return False
        return False

    def _activated(self) -> None:
        while connection := self.server.nextPendingConnection():
            connection.readAll()
            connection.disconnectFromServer()
        self.activateRequested.emit()
