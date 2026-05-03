"""
证件照便捷工具 v21.0
多功能 Tab 架构：Tab1=证件照处理，Tab2=透视矫正
"""
import sys
import os

# PyInstaller frozen 环境路径修正
if getattr(sys, "frozen", False):
    _base = sys._MEIPASS
    sys.path.insert(0, _base)

from PyQt5.QtWidgets import (QApplication, QMainWindow, QTabWidget,
                              QWidget, QVBoxLayout)
from PyQt5.QtCore    import Qt
from PyQt5.QtGui     import QFont, QPalette, QColor

from utils               import C
from module_id_photo     import IDPhotoModule
from module_perspective  import PerspectiveModule

APP_NAME    = "证件照便捷工具"
APP_VERSION = "v21.0"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME}  {APP_VERSION}")
        self.resize(1280, 820)
        self.setMinimumSize(1100, 700)
        self._build()

    def _build(self):
        central = QWidget()
        central.setStyleSheet(f"background:{C['bg']};")
        self.setCentralWidget(central)
        vl = QVBoxLayout(central)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: none;
                background: {C['bg']};
            }}
            QTabBar::tab {{
                background: {C['panel']};
                color: {C['text2']};
                padding: 10px 24px;
                font-size: 13px;
                font-weight: 500;
                border: none;
                border-bottom: 2px solid transparent;
                margin-right: 2px;
            }}
            QTabBar::tab:selected {{
                color: {C['text']};
                border-bottom: 2px solid {C['accent']};
                background: {C['bg']};
            }}
            QTabBar::tab:hover {{
                color: {C['text']};
                background: {C['card']};
            }}
        """)

        # Tab 1：证件照处理
        self.id_photo_module = IDPhotoModule()
        self.tabs.addTab(self.id_photo_module, "📷  证件照处理")

        # Tab 2：透视矫正
        self.perspective_module = PerspectiveModule()
        self.tabs.addTab(self.perspective_module, "📐  透视矫正")

        vl.addWidget(self.tabs)

    def closeEvent(self, e):
        # 通知各模块清理线程
        for mod in [self.id_photo_module, self.perspective_module]:
            if hasattr(mod, "cleanup"):
                mod.cleanup()
        e.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("ZJZPhoto")

    # 全局深色主题
    palette = QPalette()
    palette.setColor(QPalette.Window,          QColor(C['bg'].lstrip('#')))
    palette.setColor(QPalette.WindowText,      QColor(C['text'].lstrip('#')))
    palette.setColor(QPalette.Base,            QColor(C['card'].lstrip('#')))
    palette.setColor(QPalette.AlternateBase,   QColor(C['panel'].lstrip('#')))
    palette.setColor(QPalette.Text,            QColor(C['text'].lstrip('#')))
    palette.setColor(QPalette.Button,          QColor(C['panel'].lstrip('#')))
    palette.setColor(QPalette.ButtonText,      QColor(C['text'].lstrip('#')))
    palette.setColor(QPalette.Highlight,       QColor(C['accent'].lstrip('#')))
    palette.setColor(QPalette.HighlightedText, QColor('#ffffff'))
    app.setPalette(palette)

    font = QFont("PingFang SC", 11)
    font.setFallbackFamilies(["Microsoft YaHei", "Helvetica Neue", "Arial"])
    app.setFont(font)

    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
