"""
证件照自动排版工具
本地离线运行 · Python + PyQt5 + Pillow
"""

import os
import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QButtonGroup, QRadioButton, QFileDialog,
    QScrollArea, QFrame, QSizePolicy, QMessageBox, QGroupBox,
    QStatusBar
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QMimeData, QSize
from PyQt5.QtGui import QPixmap, QImage, QFont, QColor, QPalette, QDragEnterEvent, QDropEvent

from PIL import Image
from layout_engine import generate_layout, save_layout, TEMPLATES

# ─────────────────────────────────────────────
# 工作线程（防止 UI 卡顿）
# ─────────────────────────────────────────────

class LayoutWorker(QThread):
    finished = pyqtSignal(object)   # PIL Image
    error    = pyqtSignal(str)

    def __init__(self, img, template_name):
        super().__init__()
        self.img = img
        self.template_name = template_name

    def run(self):
        try:
            result = generate_layout(self.img, self.template_name)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


# ─────────────────────────────────────────────
# 拖拽上传区域
# ─────────────────────────────────────────────

class DropArea(QLabel):
    file_dropped = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignCenter)
        self._set_idle()
        self.setMinimumHeight(120)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("""
            QLabel {
                border: 2px dashed #3B5BDB;
                border-radius: 8px;
                background: #EEF2FF;
                color: #3B5BDB;
                font-size: 13px;
            }
            QLabel:hover {
                background: #D6DCFF;
            }
        """)

    def _set_idle(self):
        self.setText("拖入照片\n或点击选择文件")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            path, _ = QFileDialog.getOpenFileName(
                self, "选择证件照", "",
                "图片文件 (*.jpg *.jpeg *.png *.bmp *.tiff *.webp);;所有文件 (*)"
            )
            if path:
                self.file_dropped.emit(path)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet("""
                QLabel {
                    border: 2px dashed #2F4AC0;
                    border-radius: 8px;
                    background: #D6DCFF;
                    color: #2F4AC0;
                    font-size: 13px;
                }
            """)

    def dragLeaveEvent(self, event):
        self.setStyleSheet("""
            QLabel {
                border: 2px dashed #3B5BDB;
                border-radius: 8px;
                background: #EEF2FF;
                color: #3B5BDB;
                font-size: 13px;
            }
            QLabel:hover {
                background: #D6DCFF;
            }
        """)

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if os.path.isfile(path):
                self.file_dropped.emit(path)
        self.dragLeaveEvent(None)


# ─────────────────────────────────────────────
# 主窗口
# ─────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("证件照自动排版工具")
        self.resize(1000, 680)
        self.setMinimumSize(860, 580)

        self.source_image = None
        self.result_image = None
        self.worker = None

        self._build_ui()
        self._apply_styles()

    # ─────────────────────────────────────────
    # UI 构建
    # ─────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 顶部标题栏
        header = QWidget()
        header.setObjectName("header")
        header.setFixedHeight(52)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(20, 0, 20, 0)
        title = QLabel("证件照自动排版工具")
        title.setObjectName("headerTitle")
        subtitle = QLabel("本地离线 · 免费使用")
        subtitle.setObjectName("headerSub")
        h_layout.addWidget(title)
        h_layout.addStretch()
        h_layout.addWidget(subtitle)
        root_layout.addWidget(header)

        # 主体
        body = QWidget()
        body.setObjectName("body")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(16, 14, 16, 14)
        body_layout.setSpacing(14)
        root_layout.addWidget(body, 1)

        # 左侧面板
        left = self._build_left_panel()
        left.setFixedWidth(280)
        body_layout.addWidget(left)

        # 右侧预览
        right = self._build_preview_panel()
        body_layout.addWidget(right, 1)

        # 状态栏
        self.status_bar = QStatusBar()
        self.status_bar.showMessage("请先上传一张证件照")
        self.setStatusBar(self.status_bar)

    def _build_left_panel(self):
        panel = QWidget()
        panel.setObjectName("leftPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # ── 上传区域 ──
        upload_group = QGroupBox("第一步：上传照片")
        upload_layout = QVBoxLayout(upload_group)
        upload_layout.setSpacing(6)

        self.drop_area = DropArea()
        self.drop_area.file_dropped.connect(self._load_image)
        upload_layout.addWidget(self.drop_area)

        self.file_label = QLabel("未选择文件")
        self.file_label.setObjectName("fileLabel")
        self.file_label.setAlignment(Qt.AlignCenter)
        self.file_label.setWordWrap(True)
        upload_layout.addWidget(self.file_label)

        layout.addWidget(upload_group)

        # ── 排版类型 ──
        tmpl_group = QGroupBox("第二步：选择排版类型")
        tmpl_layout = QVBoxLayout(tmpl_group)
        tmpl_layout.setSpacing(4)

        self.btn_group = QButtonGroup(self)
        self.radio_buttons = {}
        for i, name in enumerate(TEMPLATES.keys()):
            rb = QRadioButton(name)
            rb.setObjectName("templateRadio")
            self.btn_group.addButton(rb, i)
            self.radio_buttons[name] = rb
            tmpl_layout.addWidget(rb)

        layout.addWidget(tmpl_group)

        # ── 操作按钮 ──
        self.btn_generate = QPushButton("▶  生成排版")
        self.btn_generate.setObjectName("btnGenerate")
        self.btn_generate.setCursor(Qt.PointingHandCursor)
        self.btn_generate.clicked.connect(self._generate)
        layout.addWidget(self.btn_generate)

        self.btn_export = QPushButton("⬇  导出图片 (JPG · 300DPI)")
        self.btn_export.setObjectName("btnExport")
        self.btn_export.setCursor(Qt.PointingHandCursor)
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._export)
        layout.addWidget(self.btn_export)

        layout.addStretch()
        return panel

    def _build_preview_panel(self):
        panel = QFrame()
        panel.setObjectName("previewPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        title = QLabel("排版预览")
        title.setObjectName("previewTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setAlignment(Qt.AlignCenter)
        scroll.setObjectName("scrollArea")

        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setObjectName("previewLabel")
        self.preview_label.setText("生成排版后，预览将显示在此处")
        self.preview_label.setMinimumSize(400, 300)
        scroll.setWidget(self.preview_label)

        layout.addWidget(scroll, 1)
        return panel

    # ─────────────────────────────────────────
    # 样式
    # ─────────────────────────────────────────

    def _apply_styles(self):
        self.setStyleSheet("""
            QMainWindow, QWidget#body {
                background: #F5F6F8;
            }
            QWidget#header {
                background: #3B5BDB;
            }
            QLabel#headerTitle {
                color: white;
                font-size: 18px;
                font-weight: bold;
            }
            QLabel#headerSub {
                color: #A5B4FC;
                font-size: 11px;
            }
            QWidget#leftPanel {
                background: transparent;
            }
            QGroupBox {
                font-size: 11px;
                font-weight: bold;
                color: #1A1A2E;
                border: 1px solid #E0E3EB;
                border-radius: 6px;
                background: white;
                margin-top: 8px;
                padding-top: 6px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 6px;
                left: 10px;
            }
            QRadioButton#templateRadio {
                font-size: 11px;
                color: #1A1A2E;
                padding: 4px 2px;
                spacing: 8px;
            }
            QRadioButton#templateRadio::indicator {
                width: 14px;
                height: 14px;
            }
            QRadioButton#templateRadio:checked {
                color: #3B5BDB;
                font-weight: bold;
            }
            QLabel#fileLabel {
                font-size: 10px;
                color: #6B7280;
            }
            QPushButton#btnGenerate {
                background: #3B5BDB;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton#btnGenerate:hover {
                background: #2F4AC0;
            }
            QPushButton#btnGenerate:pressed {
                background: #2340A0;
            }
            QPushButton#btnGenerate:disabled {
                background: #9CA3AF;
            }
            QPushButton#btnExport {
                background: #2E7D32;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton#btnExport:hover {
                background: #1B5E20;
            }
            QPushButton#btnExport:pressed {
                background: #145214;
            }
            QPushButton#btnExport:disabled {
                background: #9CA3AF;
            }
            QFrame#previewPanel {
                background: white;
                border: 1px solid #E0E3EB;
                border-radius: 8px;
            }
            QLabel#previewTitle {
                font-size: 12px;
                font-weight: bold;
                color: #1A1A2E;
            }
            QScrollArea#scrollArea {
                border: none;
                background: #E8EAF0;
                border-radius: 4px;
            }
            QLabel#previewLabel {
                color: #9CA3AF;
                font-size: 13px;
                background: #E8EAF0;
            }
            QStatusBar {
                background: #F0F1F5;
                color: #6B7280;
                font-size: 10px;
            }
        """)

    # ─────────────────────────────────────────
    # 业务逻辑
    # ─────────────────────────────────────────

    def _load_image(self, path: str):
        try:
            img = Image.open(path).convert("RGB")
            self.source_image = img
            fname = os.path.basename(path)
            if len(fname) > 30:
                fname = fname[:27] + "..."
            self.file_label.setText(f"✓ {fname}")
            self.file_label.setStyleSheet("color: #2E7D32; font-size: 10px;")
            self.drop_area.setText(f"已加载\n{img.width} × {img.height} px")
            self.result_image = None
            self.btn_export.setEnabled(False)
            self.preview_label.setText("照片已加载，请选择排版类型后点击生成")
            self.preview_label.setPixmap(QPixmap())
            self.status_bar.showMessage(f"照片已加载：{fname}  ({img.width}×{img.height} px)")
        except Exception as e:
            QMessageBox.critical(self, "加载失败", f"无法读取图片：\n{e}")

    def _get_selected_template(self):
        for name, rb in self.radio_buttons.items():
            if rb.isChecked():
                return name
        return None

    def _generate(self):
        if self.source_image is None:
            QMessageBox.warning(self, "提示", "请先上传一张证件照")
            return
        template = self._get_selected_template()
        if not template:
            QMessageBox.warning(self, "提示", "请选择一种排版类型")
            return

        self.btn_generate.setEnabled(False)
        self.btn_generate.setText("生成中…")
        self.status_bar.showMessage("正在生成排版，请稍候…")

        self.worker = LayoutWorker(self.source_image, template)
        self.worker.finished.connect(self._on_layout_done)
        self.worker.error.connect(self._on_layout_error)
        self.worker.start()

    def _on_layout_done(self, result: Image.Image):
        self.result_image = result
        self._show_preview(result)
        self.btn_export.setEnabled(True)
        self.btn_generate.setEnabled(True)
        self.btn_generate.setText("▶  生成排版")
        template = self._get_selected_template()
        self.status_bar.showMessage(
            f"✓ 排版完成：{template}  |  画布：{result.width}×{result.height} px  |  300 DPI")

    def _on_layout_error(self, msg: str):
        QMessageBox.critical(self, "生成失败", f"排版出错：\n{msg}")
        self.btn_generate.setEnabled(True)
        self.btn_generate.setText("▶  生成排版")
        self.status_bar.showMessage("生成失败，请重试")

    def _export(self):
        if self.result_image is None:
            QMessageBox.warning(self, "提示", "请先生成排版")
            return
        template = (self._get_selected_template() or "排版").replace("+", "加")
        default_name = f"证件照排版_{template}.jpg"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出排版图片", default_name,
            "JPEG 图片 (*.jpg);;所有文件 (*)"
        )
        if path:
            try:
                save_layout(self.result_image, path)
                self.status_bar.showMessage(f"✓ 已导出：{os.path.basename(path)}")
                QMessageBox.information(
                    self, "导出成功",
                    f"排版图片已保存至：\n{path}\n\n分辨率：300 DPI · 格式：JPG"
                )
            except Exception as e:
                QMessageBox.critical(self, "导出失败", f"保存失败：\n{e}")

    def _show_preview(self, img: Image.Image):
        # 转换 PIL → QPixmap
        data = img.tobytes("raw", "RGB")
        qimg = QImage(data, img.width, img.height, img.width * 3,
                      QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg)

        # 缩放适应预览区域（保持比例）
        preview_w = self.preview_label.parent().width() - 20
        preview_h = self.preview_label.parent().height() - 20
        if preview_w < 100:
            preview_w = 640
        if preview_h < 100:
            preview_h = 480

        scaled = pixmap.scaled(
            preview_w, preview_h,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.preview_label.setPixmap(scaled)
        self.preview_label.resize(scaled.size())


# ─────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────

def main():
    # 高 DPI 支持
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei", 10))

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
