"""
证件照自动排版工具 v2.0
本地离线运行 · Python + PyQt5 + Pillow

修复：
  - 上传照片后立即显示缩略图预览
  - 点击排版类型按钮立即生成排版（无需额外点击"生成"）
  - 现代卡片式 UI
  - 照片间距极小，紧密排列
  - 三寸横排、一寸+二寸混排9+4、驾驶证5×2
"""

import os
import sys
import tempfile

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QScrollArea, QFrame,
    QStatusBar, QSizePolicy, QSpacerItem, QMessageBox
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize, QTimer
from PyQt5.QtGui import QPixmap, QImage, QFont, QIcon, QColor, QPainter

from PIL import Image
from layout_engine import generate_layout, save_layout, TEMPLATES, TEMPLATE_DESC


# ─────────────────────────────────────────────
# PIL Image → QPixmap
# ─────────────────────────────────────────────

def pil_to_pixmap(pil_img: Image.Image) -> QPixmap:
    """将 PIL Image 转换为 QPixmap（用于 Qt 显示）。"""
    if pil_img.mode != "RGB":
        pil_img = pil_img.convert("RGB")
    data = pil_img.tobytes("raw", "RGB")
    qimg = QImage(data, pil_img.width, pil_img.height, pil_img.width * 3, QImage.Format_RGB888)
    return QPixmap.fromImage(qimg)


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

    IDLE_STYLE = """
        QLabel {
            border: 2px dashed #4A90D9;
            border-radius: 10px;
            background: #F0F7FF;
            color: #4A90D9;
            font-size: 14px;
        }
        QLabel:hover {
            background: #E0F0FF;
            border-color: #2272C3;
        }
    """
    HOVER_STYLE = """
        QLabel {
            border: 2px dashed #2272C3;
            border-radius: 10px;
            background: #D6EAFF;
            color: #2272C3;
            font-size: 14px;
        }
    """
    LOADED_STYLE = """
        QLabel {
            border: 2px solid #22C55E;
            border-radius: 10px;
            background: #F0FFF4;
        }
    """

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(160)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(self.IDLE_STYLE)
        self._show_idle()

    def _show_idle(self):
        self.setText("📂  拖入照片\n或点击此处选择文件\n\n支持 JPG / PNG / BMP")

    def show_preview(self, pil_img: Image.Image):
        """显示上传照片的缩略图。"""
        self.setStyleSheet(self.LOADED_STYLE)
        pixmap = pil_to_pixmap(pil_img)
        scaled = pixmap.scaled(
            self.width() - 16, self.height() - 16,
            Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.setPixmap(scaled)

    def reset(self):
        self.setStyleSheet(self.IDLE_STYLE)
        self.setPixmap(QPixmap())
        self._show_idle()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            path, _ = QFileDialog.getOpenFileName(
                self, "选择证件照", "",
                "图片文件 (*.jpg *.jpeg *.png *.bmp *.tiff *.webp);;所有文件 (*)"
            )
            if path:
                self.file_dropped.emit(path)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet(self.HOVER_STYLE)

    def dragLeaveEvent(self, event):
        if self.pixmap() and not self.pixmap().isNull():
            self.setStyleSheet(self.LOADED_STYLE)
        else:
            self.setStyleSheet(self.IDLE_STYLE)

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if os.path.isfile(path):
                self.file_dropped.emit(path)
        self.dragLeaveEvent(None)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 如果已有图片，重新缩放
        if hasattr(self, '_loaded_img') and self._loaded_img:
            self.show_preview(self._loaded_img)


# ─────────────────────────────────────────────
# 排版类型按钮（卡片式）
# ─────────────────────────────────────────────

class TemplateButton(QPushButton):
    NORMAL_STYLE = """
        QPushButton {{
            background: white;
            border: 1.5px solid #E0E6F0;
            border-radius: 10px;
            text-align: left;
            padding: 10px 14px;
            color: #1A2340;
        }}
        QPushButton:hover {{
            background: #F0F7FF;
            border-color: #4A90D9;
            color: #2272C3;
        }}
        QPushButton:pressed {{
            background: #E0F0FF;
        }}
    """
    ACTIVE_STYLE = """
        QPushButton {{
            background: #2272C3;
            border: 1.5px solid #2272C3;
            border-radius: 10px;
            text-align: left;
            padding: 10px 14px;
            color: white;
        }}
    """

    def __init__(self, name: str, desc: str):
        super().__init__()
        self.template_name = name
        self._active = False
        self._update_text(name, desc)
        self.setStyleSheet(self.NORMAL_STYLE)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(52)

    def _update_text(self, name, desc):
        self.setText(f"  {name}\n  {desc}")
        font = self.font()
        font.setPointSize(10)
        self.setFont(font)

    def set_active(self, active: bool):
        self._active = active
        if active:
            self.setStyleSheet(self.ACTIVE_STYLE)
        else:
            self.setStyleSheet(self.NORMAL_STYLE)


# ─────────────────────────────────────────────
# 主窗口
# ─────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("证件照自动排版工具")
        self.resize(1100, 720)
        self.setMinimumSize(900, 600)

        self.source_image = None    # PIL Image（原始上传）
        self.result_image = None    # PIL Image（排版结果）
        self.worker = None
        self.active_template_btn = None

        self._build_ui()
        self._apply_global_styles()

    # ─────────────────────────────────────────
    # UI 构建
    # ─────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 顶部标题栏
        root.addWidget(self._build_header())

        # 主体（左右分栏）
        body = QWidget()
        body.setObjectName("body")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(18, 16, 18, 16)
        body_layout.setSpacing(16)

        left = self._build_left_panel()
        left.setFixedWidth(300)
        body_layout.addWidget(left)

        right = self._build_preview_panel()
        body_layout.addWidget(right, 1)

        root.addWidget(body, 1)

        # 状态栏
        self.status_bar = QStatusBar()
        self.status_bar.setObjectName("statusBar")
        self.status_bar.showMessage("请上传一张证件照，然后点击排版类型即可生成排版")
        self.setStatusBar(self.status_bar)

    def _build_header(self):
        header = QWidget()
        header.setObjectName("header")
        header.setFixedHeight(56)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 0, 24, 0)

        title = QLabel("证件照自动排版工具")
        title.setObjectName("headerTitle")

        badge = QLabel("本地离线 · 免费使用")
        badge.setObjectName("headerBadge")

        layout.addWidget(title)
        layout.addStretch()
        layout.addWidget(badge)
        return header

    def _build_left_panel(self):
        panel = QWidget()
        panel.setObjectName("leftPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        # ── 上传区域 ──
        upload_card = self._make_card("上传照片")
        upload_inner = QVBoxLayout()
        upload_inner.setSpacing(8)

        self.drop_area = DropArea()
        self.drop_area.file_dropped.connect(self._load_image)
        upload_inner.addWidget(self.drop_area)

        self.file_info_label = QLabel("")
        self.file_info_label.setObjectName("fileInfo")
        self.file_info_label.setAlignment(Qt.AlignCenter)
        self.file_info_label.setWordWrap(True)
        upload_inner.addWidget(self.file_info_label)

        upload_card.layout().addLayout(upload_inner)
        layout.addWidget(upload_card)

        # ── 排版类型 ──
        tmpl_card = self._make_card("选择排版类型（点击即生成）")
        self.template_buttons = {}
        for name, _ in TEMPLATES.items():
            desc = TEMPLATE_DESC.get(name, "")
            btn = TemplateButton(name, desc)
            btn.clicked.connect(lambda checked, n=name: self._on_template_clicked(n))
            self.template_buttons[name] = btn
            tmpl_card.layout().addWidget(btn)

        layout.addWidget(tmpl_card)

        # ── 导出按钮 ──
        self.btn_export = QPushButton("⬇  导出图片  (JPG · 300 DPI)")
        self.btn_export.setObjectName("btnExport")
        self.btn_export.setCursor(Qt.PointingHandCursor)
        self.btn_export.setEnabled(False)
        self.btn_export.setMinimumHeight(46)
        self.btn_export.clicked.connect(self._export)
        layout.addWidget(self.btn_export)

        layout.addStretch()
        return panel

    def _make_card(self, title: str) -> QFrame:
        """创建带标题的白色卡片容器。"""
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 14)
        card_layout.setSpacing(10)

        title_label = QLabel(title)
        title_label.setObjectName("cardTitle")
        card_layout.addWidget(title_label)

        return card

    def _build_preview_panel(self):
        panel = QFrame()
        panel.setObjectName("previewPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(8)

        # 标题行
        title_row = QHBoxLayout()
        self.preview_title = QLabel("排版预览")
        self.preview_title.setObjectName("previewTitle")
        title_row.addWidget(self.preview_title)
        title_row.addStretch()
        self.preview_info = QLabel("")
        self.preview_info.setObjectName("previewInfo")
        title_row.addWidget(self.preview_info)
        layout.addLayout(title_row)

        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setAlignment(Qt.AlignCenter)
        scroll.setObjectName("scrollArea")

        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setObjectName("previewLabel")
        self.preview_label.setText("上传照片后，点击左侧排版类型即可生成预览")
        self.preview_label.setMinimumSize(500, 400)
        scroll.setWidget(self.preview_label)

        layout.addWidget(scroll, 1)
        return panel

    # ─────────────────────────────────────────
    # 全局样式
    # ─────────────────────────────────────────

    def _apply_global_styles(self):
        self.setStyleSheet("""
            QMainWindow {
                background: #F2F4F8;
            }
            QWidget#body {
                background: #F2F4F8;
            }
            /* 顶部标题栏 */
            QWidget#header {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1A56DB, stop:1 #2272C3);
            }
            QLabel#headerTitle {
                color: white;
                font-size: 20px;
                font-weight: bold;
                letter-spacing: 1px;
            }
            QLabel#headerBadge {
                color: rgba(255,255,255,0.75);
                font-size: 11px;
                background: rgba(255,255,255,0.15);
                border-radius: 10px;
                padding: 3px 10px;
            }
            /* 卡片 */
            QFrame#card {
                background: white;
                border-radius: 12px;
                border: 1px solid #E8ECF4;
            }
            QLabel#cardTitle {
                font-size: 12px;
                font-weight: bold;
                color: #374151;
                padding-bottom: 2px;
                border-bottom: 1px solid #F0F2F8;
            }
            /* 文件信息 */
            QLabel#fileInfo {
                font-size: 11px;
                color: #22C55E;
            }
            /* 预览面板 */
            QFrame#previewPanel {
                background: white;
                border-radius: 12px;
                border: 1px solid #E8ECF4;
            }
            QLabel#previewTitle {
                font-size: 13px;
                font-weight: bold;
                color: #374151;
            }
            QLabel#previewInfo {
                font-size: 11px;
                color: #6B7280;
            }
            QLabel#previewLabel {
                color: #9CA3AF;
                font-size: 13px;
                background: #FAFBFC;
                border-radius: 8px;
            }
            QScrollArea#scrollArea {
                border: none;
                background: #FAFBFC;
                border-radius: 8px;
            }
            /* 导出按钮 */
            QPushButton#btnExport {
                background: #22C55E;
                color: white;
                border: none;
                border-radius: 10px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton#btnExport:hover {
                background: #16A34A;
            }
            QPushButton#btnExport:pressed {
                background: #15803D;
            }
            QPushButton#btnExport:disabled {
                background: #D1D5DB;
                color: #9CA3AF;
            }
            /* 状态栏 */
            QStatusBar#statusBar {
                background: #F8FAFF;
                color: #6B7280;
                font-size: 11px;
                border-top: 1px solid #E8ECF4;
            }
        """)

    # ─────────────────────────────────────────
    # 事件处理
    # ─────────────────────────────────────────

    def _load_image(self, path: str):
        """加载并显示上传的照片。"""
        try:
            img = Image.open(path)
            # 处理 EXIF 旋转
            try:
                from PIL import ImageOps
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass
            img = img.convert("RGB")
            self.source_image = img

            # 在上传区域显示缩略图
            self.drop_area._loaded_img = img
            self.drop_area.show_preview(img)

            # 显示文件信息
            fname = os.path.basename(path)
            w, h = img.size
            self.file_info_label.setText(f"✓  {fname}  ({w}×{h} px)")

            self.status_bar.showMessage(f"已加载：{fname}  —  请点击左侧排版类型生成排版")

            # 如果已有选中的排版类型，自动重新生成
            if self.active_template_btn:
                self._generate(self.active_template_btn.template_name)

        except Exception as e:
            QMessageBox.critical(self, "加载失败", f"无法读取图片：\n{e}")

    def _on_template_clicked(self, template_name: str):
        """点击排版类型按钮 → 立即生成排版。"""
        # 更新按钮状态
        for btn in self.template_buttons.values():
            btn.set_active(False)
        self.template_buttons[template_name].set_active(True)
        self.active_template_btn = self.template_buttons[template_name]

        if self.source_image is None:
            self.status_bar.showMessage("请先上传一张证件照")
            return

        self._generate(template_name)

    def _generate(self, template_name: str):
        """启动排版工作线程。"""
        if self.source_image is None:
            return

        # 禁用导出按钮，显示进度
        self.btn_export.setEnabled(False)
        self.preview_label.setText("正在生成排版，请稍候…")
        self.status_bar.showMessage(f"正在生成「{template_name}」…")

        # 停止旧线程
        if self.worker and self.worker.isRunning():
            self.worker.quit()
            self.worker.wait()

        self.worker = LayoutWorker(self.source_image, template_name)
        self.worker.finished.connect(lambda img: self._on_layout_done(img, template_name))
        self.worker.error.connect(self._on_layout_error)
        self.worker.start()

    def _on_layout_done(self, result_img: Image.Image, template_name: str):
        """排版完成，显示预览。"""
        self.result_image = result_img

        # 转为 QPixmap 并缩放到预览区域
        pixmap = pil_to_pixmap(result_img)
        preview_w = self.preview_label.width() - 20
        preview_h = self.preview_label.height() - 20
        if preview_w < 100:
            preview_w = 600
        if preview_h < 100:
            preview_h = 500

        scaled = pixmap.scaled(
            preview_w, preview_h,
            Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.preview_label.setPixmap(scaled)

        # 更新信息
        w, h = result_img.size
        self.preview_info.setText(f"{w}×{h} px · 300 DPI")
        self.btn_export.setEnabled(True)
        self.status_bar.showMessage(f"「{template_name}」排版完成，点击「导出图片」保存")

    def _on_layout_error(self, msg: str):
        self.preview_label.setText(f"排版失败：{msg}")
        self.status_bar.showMessage(f"排版出错：{msg}")

    def _export(self):
        """导出排版图片。"""
        if self.result_image is None:
            return

        # 获取当前排版名称
        tmpl_name = ""
        if self.active_template_btn:
            tmpl_name = self.active_template_btn.template_name.replace("+", "_").replace(" ", "")

        default_name = f"排版_{tmpl_name}.jpg"
        path, _ = QFileDialog.getSaveFileName(
            self, "保存排版图片", default_name,
            "JPEG 图片 (*.jpg *.jpeg);;所有文件 (*)"
        )
        if path:
            try:
                save_layout(self.result_image, path)
                self.status_bar.showMessage(f"已导出：{path}")
                QMessageBox.information(self, "导出成功", f"排版图片已保存至：\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "导出失败", f"保存失败：\n{e}")

    def resizeEvent(self, event):
        """窗口缩放时更新预览。"""
        super().resizeEvent(event)
        if self.result_image:
            pixmap = pil_to_pixmap(self.result_image)
            preview_w = self.preview_label.width() - 20
            preview_h = self.preview_label.height() - 20
            if preview_w > 50 and preview_h > 50:
                scaled = pixmap.scaled(
                    preview_w, preview_h,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                self.preview_label.setPixmap(scaled)


# ─────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────

def main():
    # 高 DPI 支持
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)

    # 设置字体（Windows 用微软雅黑，macOS 用苹方，Linux 用 Noto Sans）
    font = QFont()
    import platform
    if platform.system() == "Windows":
        font.setFamily("Microsoft YaHei")
    elif platform.system() == "Darwin":
        font.setFamily("PingFang SC")
    else:
        font.setFamily("Noto Sans CJK SC")
    font.setPointSize(10)
    app.setFont(font)

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
