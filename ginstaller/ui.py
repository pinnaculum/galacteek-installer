import asyncio
import inspect
from asyncqt import QThreadExecutor

from PyQt5.QtWidgets import QSizePolicy
from PyQt5.QtWidgets import QDialog
from PyQt5.QtWidgets import QDesktopWidget
from PyQt5.QtWidgets import QLabel
from PyQt5.QtWidgets import QSpacerItem
from PyQt5.QtWidgets import QProgressBar
from PyQt5.QtWidgets import QVBoxLayout

from PyQt5.QtCore import Qt
from PyQt5.QtCore import QTimer

from PyQt5.QtGui import QPixmap
from PyQt5.QtGui import QIcon

from ginstaller.ginstaller_rc import *  # noqa


def getIcon(iconName):
    iconPath = ':/share/icons/{}'.format(iconName)
    return QIcon(QPixmap(iconPath))


async def threadExec(fn, *args):
    loop = asyncio.get_event_loop()

    with QThreadExecutor(1) as texec:
        return await loop.run_in_executor(texec, fn, *args)


async def runDialogAsync(dlgarg, *args, **kw):
    title = kw.pop('title', None)

    if inspect.isclass(dlgarg):
        dlgW = dlgarg(*args, **kw)
    else:
        dlgW = dlgarg

    if hasattr(dlgW, 'initDialog') and asyncio.iscoroutinefunction(
            dlgW.initDialog):
        await dlgW.initDialog()

    if title:
        dlgW.setWindowTitle(title)

    dlgW.show()
    await threadExec(dlgW.exec_)
    return dlgW


class CountDownDialog(QDialog):
    def __init__(self, countdown=10, parent=None):
        super().__init__(parent, Qt.WindowStaysOnTopHint)

        self.initCountdown = countdown
        self.countdown = countdown

        self.timer = QTimer()
        self.timer.timeout.connect(self.onTimerOut)
        self.timer.start(1000)

    def enterEvent(self, ev):
        self.timer.stop()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self.timer.stop()
        self.countdown = self.initCountdown / 2
        self.timer.start(1000)

        super().leaveEvent(ev)

    def onTimerOut(self):
        self.countdown -= 1

        if self.countdown == 0:
            self.accept()


# class DefaultProgressDialog(QWidget):
class DefaultProgressDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.Dialog | Qt.WindowStaysOnTopHint)

        dGeometry = QDesktopWidget().screenGeometry()
        self.vl = QVBoxLayout(self)
        self.pBar = QProgressBar()
        self.status = QLabel()
        self.status.setObjectName('statusProgressLabel')
        self.setLayout(self.vl)
        self.vl.addItem(
            QSpacerItem(10, 50, QSizePolicy.Expanding, QSizePolicy.Expanding))
        self.vl.addWidget(self.status, 0, Qt.AlignCenter)
        self.vl.addWidget(self.pBar, 0, Qt.AlignCenter)
        self.vl.addItem(
            QSpacerItem(10, 50, QSizePolicy.Expanding, QSizePolicy.Expanding))

        self.setMaximumSize(
            dGeometry.width() / 2,
            dGeometry.height() / 3
        )

        center = dGeometry.center()

        if 0:
            self.move(
                center.x() - self.width(),
                center.y() - self.height()
            )

    def spin(self):
        self.cube.startClip()

    def stop(self):
        self.cube.stopClip()

    def log(self, text):
        self.status.setText(text)

    def progress(self, p: int):
        self.pBar.setValue(p)
