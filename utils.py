"""
utils.py — 证件照便捷工具 公共工具模块
提供：颜色主题、安全图片加载、通用 UI 组件、画笔光标生成
"""
from __future__ import annotations
import sys
from pathlib import Path
from PIL import Image
from PyQt5.QtCore    import Qt
from PyQt5.QtGui     import (QColor, QImage, QPainter, QPen, QPixmap, QCursor)
from PyQt5.QtWidgets import (QLabel, QFrame, QPushButton, QSizePolicy)

# ─────────────────────────────────────────────
# 颜色主题（深色专业工具风格）
# ─────────────────────────────────────────────
C = {
    "bg":         "#1a1b1e",
    "panel":      "#1e1f23",
    "card":       "#25262b",
    "card_hover": "#2c2d33",
    "preview":    "#16171a",
    "accent":     "#4c6ef5",
    "success":    "#40c057",
    "warn":       "#fab005",
    "danger":     "#fa5252",
    "text":       "#c1c2c5",
    "text2":      "#868e96",
    "border":     "#373a40",
}

# ─────────────────────────────────────────────
# 安全图片加载
# ─────────────────────────────────────────────
MAX_LONG_SIDE   = 4000
MAX_TOTAL_PIXEL = 20_000_000

def safe_load_image(path: str):
    """
    安全加载图片：
    - 检测损坏文件
    - 超大图自动等比缩小
    返回 (img: Image.Image, was_resized: bool, orig_size: tuple)
    """
    try:
        with Image.open(path) as probe:
            probe.verify()
    except Exception as e:
        raise ValueError(f"图片损坏或格式不支持：{e}")
    img = Image.open(path).convert("RGB")
    orig_size = img.size
    ow, oh = orig_size
    total = ow * oh
    long_side = max(ow, oh)
    need_resize = long_side > MAX_LONG_SIDE or total > MAX_TOTAL_PIXEL
    if need_resize:
        ratio = min(MAX_LONG_SIDE / long_side, (MAX_TOTAL_PIXEL / total) ** 0.5)
        nw = max(1, int(ow * ratio))
        nh = max(1, int(oh * ratio))
        img = img.resize((nw, nh), Image.LANCZOS)
    return img, need_resize, orig_size

# ─────────────────────────────────────────────
# PIL ↔ Qt 转换
# ─────────────────────────────────────────────
def pil_to_qpixmap(img: Image.Image) -> QPixmap:
    """PIL RGB → QPixmap（带 copy() 防止缓冲区释放）"""
    if img.mode != "RGB":
        img = img.convert("RGB")
    data = img.tobytes("raw", "RGB")
    qi = QImage(data, img.width, img.height, img.width * 3, QImage.Format_RGB888)
    return QPixmap.fromImage(qi.copy())

def pil_rgba_to_qpixmap(img: Image.Image) -> QPixmap:
    """PIL RGBA → QPixmap（带 copy() 防止缓冲区释放）"""
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qi = QImage(data, img.width, img.height, img.width * 4, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qi.copy())

# ─────────────────────────────────────────────
# 画笔光标生成（跨平台可见）
# ─────────────────────────────────────────────
def make_brush_cursor(size_px: int) -> QCursor:
    """
    生成 PS 风格圆形画笔光标。
    使用 QImage（ARGB32）确保 macOS/Windows 跨平台可见。
    """
    d = max(12, size_px)
    img_size = d + 6  # 留边距
    qi = QImage(img_size, img_size, QImage.Format_ARGB32)
    qi.fill(Qt.transparent)

    painter = QPainter(qi)
    painter.setRenderHint(QPainter.Antialiasing)

    cx = img_size // 2
    cy = img_size // 2
    r  = d // 2

    # 黑色外框（增强对比度，在浅色背景上可见）
    painter.setPen(QPen(QColor(0, 0, 0, 200), 3))
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(cx - r, cy - r, r * 2, r * 2)

    # 白色内圆（在深色背景上可见）
    painter.setPen(QPen(QColor(255, 255, 255, 255), 1.5))
    painter.drawEllipse(cx - r + 1, cy - r + 1, (r - 1) * 2, (r - 1) * 2)

    # 中心十字（4px 短线）
    painter.setPen(QPen(QColor(255, 255, 255, 230), 1))
    painter.drawLine(cx - 4, cy, cx + 4, cy)
    painter.drawLine(cx, cy - 4, cx, cy + 4)
    painter.setPen(QPen(QColor(0, 0, 0, 180), 1))
    painter.drawLine(cx - 3, cy, cx - 1, cy)
    painter.drawLine(cx + 1, cy, cx + 3, cy)
    painter.drawLine(cx, cy - 3, cx, cy - 1)
    painter.drawLine(cx, cy + 1, cx, cy + 3)

    painter.end()

    pm = QPixmap.fromImage(qi)
    return QCursor(pm, cx, cy)

# ─────────────────────────────────────────────
# 通用 UI 组件
# ─────────────────────────────────────────────
def make_btn(text: str, primary=False, small=False, danger=False) -> QPushButton:
    b = QPushButton(text)
    h = 28 if small else 36
    b.setFixedHeight(h)
    if primary:
        bg = C['accent']; fg = "#fff"; hover = "#3b5bdb"
    elif danger:
        bg = "#3a1c1c"; fg = C['danger']; hover = "#4a2020"
    else:
        bg = C['card']; fg = C['text']; hover = C['card_hover']
    fs = "11px" if small else "12px"
    b.setStyleSheet(
        f"QPushButton{{background:{bg};color:{fg};border:1px solid {C['border']};"
        f"border-radius:6px;font-size:{fs};padding:0 12px;font-weight:500;}}"
        f"QPushButton:hover{{background:{hover};}}"
        f"QPushButton:disabled{{opacity:0.4;}}")
    return b

def section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"font-size:10px;font-weight:700;color:{C['text2']};"
        f"letter-spacing:1.5px;text-transform:uppercase;background:transparent;")
    return lbl

def divider() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setFixedHeight(1)
    f.setStyleSheet(f"background:{C['border']};border:none;")
    return f

class StatusLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setStyleSheet(f"font-size:11px;color:{C['text2']};background:transparent;")
    def set_info(self, t): self.setText(t); self.setStyleSheet(f"font-size:11px;color:{C['text2']};background:transparent;")
    def set_ok(self, t):   self.setText(t); self.setStyleSheet(f"font-size:11px;color:{C['success']};background:transparent;")
    def set_warn(self, t): self.setText(t); self.setStyleSheet(f"font-size:11px;color:{C['warn']};background:transparent;")
    def set_err(self, t):  self.setText(t); self.setStyleSheet(f"font-size:11px;color:{C['danger']};background:transparent;")

class PreviewLabel(QLabel):
    """只读预览标签，自动缩放 PIL 图片"""
    def __init__(self, placeholder="", parent=None):
        super().__init__(placeholder, parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet(
            f"background:{C['preview']};color:{C['text2']};font-size:12px;"
            f"border:1px solid {C['border']};border-radius:8px;")
        self._img: Image.Image | None = None

    def show_img(self, img: Image.Image):
        self._img = img
        self._refresh_pixmap()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._img:
            self._refresh_pixmap()

    def _refresh_pixmap(self):
        if not self._img: return
        w = self.width(); h = self.height()
        if w <= 0 or h <= 0: return
        t = self._img.copy()
        t.thumbnail((w, h), Image.LANCZOS)
        if t.mode == "RGBA":
            pm = pil_rgba_to_qpixmap(t)
        else:
            pm = pil_to_qpixmap(t)
        self.setPixmap(pm)
