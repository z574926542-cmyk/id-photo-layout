"""
证件照自动排版工具 v5.0
UI 风格：深色专业风 · 现代高级感
- 深色背景 + 蓝紫渐变强调色
- 左侧控制面板 + 右侧大预览区
- 点击排版按钮即时生成，无需额外操作
"""

import sys
import os
from pathlib import Path

from PIL import Image

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QFrame, QSizePolicy,
    QMessageBox, QProgressBar, QGraphicsDropShadowEffect
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import (
    QPixmap, QImage, QColor, QPalette, QFont, QDragEnterEvent, QDropEvent, QIcon
)

from layout_engine import generate_layout, save_layout, TEMPLATE_DESC

# ─────────────────────────────────────────────
# 颜色主题
# ─────────────────────────────────────────────
C = {
    "bg":          "#0f0f1a",
    "panel":       "#15152a",
    "card":        "#1c1c35",
    "card_hover":  "#22223e",
    "border":      "#2c2c50",
    "border_hi":   "#5b6cf9",
    "accent":      "#5b6cf9",
    "accent2":     "#8b5cf6",
    "accent_text": "#a5b4fc",
    "text":        "#e8e8ff",
    "text2":       "#8888bb",
    "muted":       "#44446a",
    "success":     "#34d399",
    "preview":     "#0a0a16",
}

# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────
def pil_to_qpixmap(img: Image.Image) -> QPixmap:
    rgb = img.convert("RGB")
    data = rgb.tobytes("raw", "RGB")
    qimg = QImage(data, rgb.width, rgb.height, rgb.width * 3, QImage.Format_RGB888)
    return QPixmap.fromImage(qimg)

def shadow(radius=24, color="#5b6cf9", alpha=60, dy=6):
    e = QGraphicsDropShadowEffect()
    e.setBlurRadius(radius)
    c = QColor(color); c.setAlpha(alpha)
    e.setColor(c); e.setOffset(0, dy)
    return e

# ─────────────────────────────────────────────
# 后台排版线程
# ─────────────────────────────────────────────
class Worker(QThread):
    done  = pyqtSignal(object, str)
    fail  = pyqtSignal(str)

    def __init__(self, img, name):
        super().__init__()
        self.img, self.name = img, name

    def run(self):
        try:
            self.done.emit(generate_layout(self.img, self.name), self.name)
        except Exception as e:
            self.fail.emit(str(e))

# ─────────────────────────────────────────────
# 上传区域
# ─────────────────────────────────────────────
class UploadZone(QLabel):
    loaded = pyqtSignal(object)   # PIL Image

    _IDLE = f"""
        QLabel {{
            background: {C['card']};
            border: 2px dashed {C['border_hi']};
            border-radius: 14px;
            color: {C['text2']};
            font-size: 13px;
        }}
        QLabel:hover {{
            background: {C['card_hover']};
            border-color: #818cf8;
        }}
    """
    _ACTIVE = f"""
        QLabel {{
            background: {C['card']};
            border: 2px solid {C['accent']};
            border-radius: 14px;
        }}
    """

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._pil = None
        self._idle()

    def _idle(self):
        self.setText("拖入照片\n\n点击选择文件\n\nJPG · PNG · BMP")
        self.setStyleSheet(self._IDLE)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            p, _ = QFileDialog.getOpenFileName(self, "选择证件照", "",
                "图片 (*.jpg *.jpeg *.png *.bmp *.tiff *.webp)")
            if p: self._load(p)

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls(): e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent):
        urls = e.mimeData().urls()
        if urls: self._load(urls[0].toLocalFile())

    def _load(self, path: str):
        try:
            img = Image.open(path).convert("RGB")
            self._pil = img
            thumb = img.copy()
            thumb.thumbnail((280, 160), Image.LANCZOS)
            self.setPixmap(pil_to_qpixmap(thumb))
            self.setStyleSheet(self._ACTIVE)
            self.setToolTip(f"{Path(path).name}  {img.width}×{img.height}px")
            self.loaded.emit(img)
        except Exception as ex:
            QMessageBox.warning(self, "加载失败", str(ex))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._pil:
            thumb = self._pil.copy()
            thumb.thumbnail((self.width()-20, self.height()-20), Image.LANCZOS)
            self.setPixmap(pil_to_qpixmap(thumb))

# ─────────────────────────────────────────────
# 排版按钮
# ─────────────────────────────────────────────
class LayoutBtn(QPushButton):
    _N = f"""
        QPushButton {{
            background: {C['card']};
            border: 1px solid {C['border']};
            border-radius: 10px;
            padding: 0;
        }}
        QPushButton:hover {{
            background: {C['card_hover']};
            border-color: {C['border_hi']};
        }}
        QPushButton:pressed {{ background: {C['card']}; }}
    """
    _A = f"""
        QPushButton {{
            background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                stop:0 {C['accent']}, stop:1 {C['accent2']});
            border: none;
            border-radius: 10px;
            padding: 0;
        }}
    """

    def __init__(self, name, desc):
        super().__init__()
        self.name = name
        lo = QVBoxLayout(self)
        lo.setContentsMargins(12, 10, 12, 10)
        lo.setSpacing(3)

        self._t = QLabel(name)
        self._t.setStyleSheet(f"font-size:14px;font-weight:600;color:{C['text']};background:transparent;")
        self._t.setAlignment(Qt.AlignCenter)

        self._d = QLabel(desc)
        self._d.setStyleSheet(f"font-size:10px;color:{C['text2']};background:transparent;")
        self._d.setAlignment(Qt.AlignCenter)

        lo.addWidget(self._t)
        lo.addWidget(self._d)
        self.setFixedHeight(68)
        self.setStyleSheet(self._N)

    def activate(self, on: bool):
        if on:
            self.setStyleSheet(self._A)
            self._t.setStyleSheet("font-size:14px;font-weight:600;color:#fff;background:transparent;")
            self._d.setStyleSheet("font-size:10px;color:rgba(255,255,255,0.7);background:transparent;")
        else:
            self.setStyleSheet(self._N)
            self._t.setStyleSheet(f"font-size:14px;font-weight:600;color:{C['text']};background:transparent;")
            self._d.setStyleSheet(f"font-size:10px;color:{C['text2']};background:transparent;")

# ─────────────────────────────────────────────
# 预览区
# ─────────────────────────────────────────────
class Preview(QLabel):
    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._img = None
        self._idle()

    def _idle(self):
        self.setText("选择排版类型后，预览将在此显示")
        self.setStyleSheet(f"""
            QLabel {{
                background:{C['preview']};
                border:1px solid {C['border']};
                border-radius:16px;
                color:{C['muted']};
                font-size:14px;
            }}
        """)

    def show(self, img: Image.Image):
        self._img = img
        self._render()
        self.setStyleSheet(f"""
            QLabel {{
                background:{C['preview']};
                border:1px solid {C['border']};
                border-radius:16px;
                padding:12px;
            }}
        """)

    def _render(self):
        if not self._img: return
        w = max(self.width()-32, 100)
        h = max(self.height()-32, 100)
        t = self._img.copy()
        t.thumbnail((w, h), Image.LANCZOS)
        self.setPixmap(pil_to_qpixmap(t))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._img: self._render()

    def result(self): return self._img

# ─────────────────────────────────────────────
# 分隔线
# ─────────────────────────────────────────────
def divider():
    f = QFrame(); f.setFrameShape(QFrame.HLine)
    f.setStyleSheet(f"color:{C['border']};background:{C['border']};max-height:1px;")
    return f

# ─────────────────────────────────────────────
# 主窗口
# ─────────────────────────────────────────────
class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("证件照排版工具")
        self.resize(1180, 780)
        self.setMinimumSize(960, 640)
        # 设置窗口图标
        _ico = Path(__file__).parent / "icon.ico"
        if not _ico.exists(): _ico = Path(__file__).parent / "icon.png"
        if _ico.exists(): self.setWindowIcon(QIcon(str(_ico)))
        self.setStyleSheet(f"QMainWindow,QWidget{{background:{C['bg']};color:{C['text']};font-family:'PingFang SC','Microsoft YaHei',Arial,sans-serif;}}")

        self._src = None
        self._res = None
        self._cur = None
        self._worker = None
        self._build()

    def _build(self):
        root = QWidget(); self.setCentralWidget(root)
        hl = QHBoxLayout(root); hl.setContentsMargins(0,0,0,0); hl.setSpacing(0)

        # ── 左侧面板 ──
        left = QWidget()
        left.setFixedWidth(340)
        left.setStyleSheet(f"background:{C['panel']};border-right:1px solid {C['border']};")
        ll = QVBoxLayout(left); ll.setContentsMargins(22,26,22,22); ll.setSpacing(16)

        # 品牌标题
        brand = QLabel("证件照排版")
        brand.setStyleSheet(f"font-size:20px;font-weight:700;color:{C['text']};letter-spacing:1px;")
        sub = QLabel("ID PHOTO LAYOUT  ·  本地离线")
        sub.setStyleSheet(f"font-size:10px;color:{C['muted']};letter-spacing:2px;margin-top:-4px;")
        ll.addWidget(brand); ll.addWidget(sub)
        ll.addWidget(divider())

        # 上传区
        lbl_up = QLabel("上传照片")
        lbl_up.setStyleSheet(f"font-size:11px;font-weight:600;color:{C['text2']};letter-spacing:1px;")
        ll.addWidget(lbl_up)

        self.upload = UploadZone()
        self.upload.loaded.connect(self._on_load)
        ll.addWidget(self.upload)

        self.info = QLabel("未选择照片")
        self.info.setAlignment(Qt.AlignCenter)
        self.info.setStyleSheet(f"font-size:11px;color:{C['muted']};")
        ll.addWidget(self.info)

        ll.addWidget(divider())

        # 排版按钮
        lbl_tp = QLabel("选择排版类型")
        lbl_tp.setStyleSheet(f"font-size:11px;font-weight:600;color:{C['text2']};letter-spacing:1px;")
        ll.addWidget(lbl_tp)

        TEMPLATES = [
            ("一寸排版",      "3×3 · 9张 · 5寸竖版"),
            ("二寸排版",      "2×2 · 4张 · 5寸竖版"),
            ("小二寸排版",    "2×2 · 4张 · 5寸竖版"),
            ("三寸排版",      "1×2 · 2张 · 5寸竖版"),
            ("驾驶证排版",    "5×2 · 10张 · 5寸横版"),
            ("一寸+二寸排版", "9+4张 · 7寸横版"),
        ]
        self._btns = {}
        for i in range(0, len(TEMPLATES), 2):
            row = QWidget(); row.setStyleSheet("background:transparent;")
            rl = QHBoxLayout(row); rl.setContentsMargins(0,0,0,0); rl.setSpacing(8)
            for j in range(2):
                if i+j < len(TEMPLATES):
                    n, d = TEMPLATES[i+j]
                    b = LayoutBtn(n, d)
                    b.clicked.connect(lambda _, name=n: self._on_tmpl(name))
                    self._btns[n] = b
                    rl.addWidget(b)
            ll.addWidget(row)

        # 进度条
        self.prog = QProgressBar()
        self.prog.setRange(0,0); self.prog.setFixedHeight(3); self.prog.setVisible(False)
        self.prog.setStyleSheet(f"""
            QProgressBar{{background:{C['border']};border:none;border-radius:2px;}}
            QProgressBar::chunk{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 {C['accent']},stop:1 {C['accent2']});border-radius:2px;}}
        """)
        ll.addWidget(self.prog)
        ll.addStretch()

        # 导出按钮
        self.btn_exp = QPushButton("导出 JPG  ·  300 DPI")
        self.btn_exp.setEnabled(False)
        self.btn_exp.setFixedHeight(46)
        self.btn_exp.setStyleSheet(f"""
            QPushButton{{
                background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {C['accent']},stop:1 {C['accent2']});
                color:#fff;font-size:14px;font-weight:600;
                border:none;border-radius:11px;letter-spacing:1px;
            }}
            QPushButton:hover{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 #818cf8,stop:1 #a78bfa);}}
            QPushButton:disabled{{background:{C['card']};color:{C['muted']};}}
            QPushButton:pressed{{background:{C['accent']};}}
        """)
        self.btn_exp.clicked.connect(self._export)
        ll.addWidget(self.btn_exp)

        # ── 右侧预览 ──
        right = QWidget(); right.setStyleSheet(f"background:{C['bg']};")
        rl2 = QVBoxLayout(right); rl2.setContentsMargins(24,24,24,24); rl2.setSpacing(10)

        ph = QHBoxLayout()
        ptitle = QLabel("排版预览")
        ptitle.setStyleSheet(f"font-size:13px;font-weight:600;color:{C['text2']};letter-spacing:1px;")
        self.pinfo = QLabel("")
        self.pinfo.setStyleSheet(f"font-size:11px;color:{C['muted']};")
        ph.addWidget(ptitle); ph.addStretch(); ph.addWidget(self.pinfo)
        rl2.addLayout(ph)

        self.preview = Preview()
        rl2.addWidget(self.preview)

        hl.addWidget(left)
        hl.addWidget(right, 1)

    # ── 事件 ──
    def _on_load(self, img):
        self._src = img
        w, h = img.size
        self.info.setText(f"{w} × {h} px")
        self.info.setStyleSheet(f"font-size:11px;color:{C['success']};text-align:center;")
        if self._cur:
            self._on_tmpl(self._cur)

    def _on_tmpl(self, name):
        for n, b in self._btns.items(): b.activate(n == name)
        self._cur = name
        if not self._src:
            self.pinfo.setText("请先上传照片")
            return
        self.prog.setVisible(True)
        self.btn_exp.setEnabled(False)
        self.pinfo.setText("生成中...")
        self.pinfo.setStyleSheet(f"font-size:11px;color:{C['text2']};")
        self._worker = Worker(self._src, name)
        self._worker.done.connect(self._on_done)
        self._worker.fail.connect(self._on_fail)
        self._worker.start()

    def _on_done(self, img, name):
        self._res = img
        self.prog.setVisible(False)
        self.preview.show(img)
        self.btn_exp.setEnabled(True)
        w, h = img.size
        self.pinfo.setText(f"{name}  ·  {w}×{h}px  ·  300 DPI")
        self.pinfo.setStyleSheet(f"font-size:11px;color:{C['success']};")

    def _on_fail(self, msg):
        self.prog.setVisible(False)
        self.pinfo.setText(f"失败：{msg}")
        self.pinfo.setStyleSheet("font-size:11px;color:#f87171;")

    def _export(self):
        if not self._res: return
        name = f"{self._cur or '排版'}.jpg"
        path, _ = QFileDialog.getSaveFileName(self, "导出排版图片", name, "JPEG (*.jpg *.jpeg)")
        if path:
            if not path.lower().endswith(('.jpg','.jpeg')): path += '.jpg'
            try:
                save_layout(self._res, path)
                self.pinfo.setText(f"已导出：{Path(path).name}")
                self.pinfo.setStyleSheet(f"font-size:11px;color:{C['success']};")
            except Exception as e:
                QMessageBox.critical(self, "导出失败", str(e))

# ─────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("证件照排版工具")
    app.setStyle("Fusion")

    # 加载应用图标
    _icon_path = Path(__file__).parent / "icon.ico"
    if not _icon_path.exists():
        _icon_path = Path(__file__).parent / "icon.png"
    if _icon_path.exists():
        app.setWindowIcon(QIcon(str(_icon_path)))

    pal = QPalette()
    pal.setColor(QPalette.Window,          QColor(C['bg']))
    pal.setColor(QPalette.WindowText,      QColor(C['text']))
    pal.setColor(QPalette.Base,            QColor(C['card']))
    pal.setColor(QPalette.Text,            QColor(C['text']))
    pal.setColor(QPalette.Button,          QColor(C['card']))
    pal.setColor(QPalette.ButtonText,      QColor(C['text']))
    pal.setColor(QPalette.Highlight,       QColor(C['accent']))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    app.setPalette(pal)

    w = App(); w.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
