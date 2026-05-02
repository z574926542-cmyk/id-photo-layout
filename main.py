"""
证件照自动排版工具 v10.0
功能：换背景 + 排版 一体化工作流
- 上传照片 → 自动 U²-Net 抠图 → 选背景色/图 → 选排版类型 → 导出
- 保留 PS 风格裁剪框（四角等比/四边自由/框内移动）
- 支持导出换背景 JPG、透明 PNG、排版 JPG
"""

import sys
import os
from pathlib import Path

from PIL import Image

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QFrame, QSizePolicy,
    QMessageBox, QProgressBar, QGraphicsDropShadowEffect, QDialog,
    QDialogButtonBox, QScrollArea, QColorDialog, QStackedWidget,
    QGridLayout
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize
from PyQt5.QtGui import (
    QPixmap, QImage, QColor, QPalette, QFont, QDragEnterEvent, QDropEvent,
    QIcon, QPainter, QBrush
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
    "warning":     "#fbbf24",
    "preview":     "#0a0a16",
    "nav":         "#10101e",
    "nav_active":  "#1c1c35",
}

# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────
def pil_to_qpixmap(img: Image.Image) -> QPixmap:
    rgb = img.convert("RGB")
    data = rgb.tobytes("raw", "RGB")
    qimg = QImage(data, rgb.width, rgb.height, rgb.width * 3, QImage.Format_RGB888)
    return QPixmap.fromImage(qimg)


def pil_rgba_to_qpixmap(img: Image.Image) -> QPixmap:
    """支持透明通道的 PIL→QPixmap"""
    rgba = img.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimg = QImage(data, rgba.width, rgba.height, rgba.width * 4, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qimg)


def shadow(radius=24, color="#5b6cf9", alpha=60, dy=6):
    e = QGraphicsDropShadowEffect()
    e.setBlurRadius(radius)
    c = QColor(color); c.setAlpha(alpha)
    e.setColor(c); e.setOffset(0, dy)
    return e


def divider():
    f = QFrame(); f.setFrameShape(QFrame.HLine)
    f.setStyleSheet(f"color:{C['border']};background:{C['border']};max-height:1px;")
    return f


def section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"font-size:10px;font-weight:700;color:{C['text2']};"
        f"letter-spacing:2px;text-transform:uppercase;"
    )
    return lbl


# ─────────────────────────────────────────────
# PS 风格裁剪弹窗
# ─────────────────────────────────────────────
HIT_NONE = 0
HIT_MOVE = 1
HIT_TL   = 2
HIT_TR   = 3
HIT_BL   = 4
HIT_BR   = 5
HIT_T    = 6
HIT_B    = 7
HIT_L    = 8
HIT_R    = 9
HANDLE_R = 6


class CropCanvas(QWidget):
    def __init__(self, pil_img: Image.Image):
        super().__init__()
        self.setMouseTracking(True)
        self.setMinimumSize(560, 420)
        self.setStyleSheet(f"background:{C['preview']};")
        self._orig = pil_img
        iw, ih = pil_img.size
        self._cx0, self._cy0 = 0.0, 0.0
        self._cx1, self._cy1 = float(iw), float(ih)
        self._hit = HIT_NONE
        self._drag_start = None
        self._drag_box   = None

    def _img_rect_on_widget(self):
        iw, ih = self._orig.size
        ww, wh = self.width(), self.height()
        scale = min(ww / iw, wh / ih)
        dw, dh = iw * scale, ih * scale
        wx0 = (ww - dw) / 2; wy0 = (wh - dh) / 2
        return wx0, wy0, wx0 + dw, wy0 + dh, scale

    def _img_to_widget(self, ix, iy):
        wx0, wy0, _, _, scale = self._img_rect_on_widget()
        return wx0 + ix * scale, wy0 + iy * scale

    def _crop_box_widget(self):
        x0, y0 = self._img_to_widget(self._cx0, self._cy0)
        x1, y1 = self._img_to_widget(self._cx1, self._cy1)
        return x0, y0, x1, y1

    def _hit_test(self, mx, my):
        x0, y0, x1, y1 = self._crop_box_widget()
        r = HANDLE_R
        cx, cy = (x0+x1)/2, (y0+y1)/2
        if abs(mx-x0)<=r and abs(my-y0)<=r: return HIT_TL
        if abs(mx-x1)<=r and abs(my-y0)<=r: return HIT_TR
        if abs(mx-x0)<=r and abs(my-y1)<=r: return HIT_BL
        if abs(mx-x1)<=r and abs(my-y1)<=r: return HIT_BR
        if abs(mx-cx)<=r and abs(my-y0)<=r: return HIT_T
        if abs(mx-cx)<=r and abs(my-y1)<=r: return HIT_B
        if abs(mx-x0)<=r and abs(my-cy)<=r: return HIT_L
        if abs(mx-x1)<=r and abs(my-cy)<=r: return HIT_R
        if x0 < mx < x1 and y0 < my < y1:   return HIT_MOVE
        return HIT_NONE

    def _cursor_for_hit(self, hit):
        m = {
            HIT_TL: Qt.SizeFDiagCursor, HIT_BR: Qt.SizeFDiagCursor,
            HIT_TR: Qt.SizeBDiagCursor, HIT_BL: Qt.SizeBDiagCursor,
            HIT_T:  Qt.SizeVerCursor,   HIT_B:  Qt.SizeVerCursor,
            HIT_L:  Qt.SizeHorCursor,   HIT_R:  Qt.SizeHorCursor,
            HIT_MOVE: Qt.SizeAllCursor,
        }
        return m.get(hit, Qt.ArrowCursor)

    def _clamp_box(self):
        iw, ih = self._orig.size
        MIN_SZ = 20.0
        self._cx0 = max(0.0, min(self._cx0, self._cx1 - MIN_SZ))
        self._cy0 = max(0.0, min(self._cy0, self._cy1 - MIN_SZ))
        self._cx1 = min(float(iw), max(self._cx1, self._cx0 + MIN_SZ))
        self._cy1 = min(float(ih), max(self._cy1, self._cy0 + MIN_SZ))

    def get_cropped(self) -> Image.Image:
        self._clamp_box()
        return self._orig.crop((int(self._cx0), int(self._cy0),
                                int(self._cx1), int(self._cy1)))

    def reset(self):
        iw, ih = self._orig.size
        self._cx0, self._cy0 = 0.0, 0.0
        self._cx1, self._cy1 = float(iw), float(ih)
        self.update()

    def paintEvent(self, e):
        from PyQt5.QtCore import QRectF
        iw, ih = self._orig.size
        wx0, wy0, wx1, wy1, _ = self._img_rect_on_widget()
        thumb = self._orig.resize((int(wx1-wx0), int(wy1-wy0)), Image.LANCZOS)
        px = pil_to_qpixmap(thumb)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(C['preview']))
        p.drawPixmap(int(wx0), int(wy0), px)
        bx0, by0, bx1, by1 = self._crop_box_widget()
        overlay = QColor(0, 0, 0, 120)
        p.fillRect(QRectF(wx0, wy0, wx1-wx0, by0-wy0), overlay)
        p.fillRect(QRectF(wx0, by1, wx1-wx0, wy1-by1), overlay)
        p.fillRect(QRectF(wx0, by0, bx0-wx0, by1-by0), overlay)
        p.fillRect(QRectF(bx1, by0, wx1-bx1, by1-by0), overlay)
        p.setPen(QColor(255, 255, 255, 220))
        p.drawRect(QRectF(bx0, by0, bx1-bx0, by1-by0))
        p.setPen(QColor(255, 255, 255, 60))
        for i in (1, 2):
            gx = bx0 + (bx1-bx0)*i/3; gy = by0 + (by1-by0)*i/3
            p.drawLine(int(gx), int(by0), int(gx), int(by1))
            p.drawLine(int(bx0), int(gy), int(bx1), int(gy))
        p.setPen(QColor(255, 255, 255, 255))
        p.setBrush(QColor(255, 255, 255, 220))
        cx, cy = (bx0+bx1)/2, (by0+by1)/2
        r = HANDLE_R
        for hx, hy in [(bx0,by0),(bx1,by0),(bx0,by1),(bx1,by1),
                       (cx,by0),(cx,by1),(bx0,cy),(bx1,cy)]:
            p.drawRect(int(hx-r), int(hy-r), r*2, r*2)
        p.setPen(QColor(255, 255, 255, 100))
        p.setFont(QFont("Arial", 9))
        p.drawText(self.rect().adjusted(0,0,-8,-6),
                   Qt.AlignBottom | Qt.AlignRight,
                   "拖动框内移动  ·  拖角等比  ·  拖边自由")
        p.end()

    def mouseMoveEvent(self, e):
        mx, my = e.pos().x(), e.pos().y()
        if self._hit == HIT_NONE:
            self.setCursor(self._cursor_for_hit(self._hit_test(mx, my)))
            return
        dx_w = mx - self._drag_start[0]; dy_w = my - self._drag_start[1]
        _, _, _, _, scale = self._img_rect_on_widget()
        dx, dy = dx_w / scale, dy_w / scale
        cx0, cy0, cx1, cy1 = self._drag_box
        iw, ih = self._orig.size
        if self._hit == HIT_MOVE:
            w, h = cx1-cx0, cy1-cy0
            nx0 = max(0.0, min(cx0+dx, iw-w)); ny0 = max(0.0, min(cy0+dy, ih-h))
            self._cx0, self._cy0, self._cx1, self._cy1 = nx0, ny0, nx0+w, ny0+h
        elif self._hit == HIT_TL:
            self._cx0 = max(0.0, min(cx0+dx, cx1-20))
            self._cy0 = max(0.0, min(cy0+dy, cy1-20))
        elif self._hit == HIT_TR:
            self._cx1 = min(float(iw), max(cx1+dx, cx0+20))
            self._cy0 = max(0.0, min(cy0+dy, cy1-20))
        elif self._hit == HIT_BL:
            self._cx0 = max(0.0, min(cx0+dx, cx1-20))
            self._cy1 = min(float(ih), max(cy1+dy, cy0+20))
        elif self._hit == HIT_BR:
            self._cx1 = min(float(iw), max(cx1+dx, cx0+20))
            self._cy1 = min(float(ih), max(cy1+dy, cy0+20))
        elif self._hit == HIT_T:  self._cy0 = max(0.0, min(cy0+dy, cy1-20))
        elif self._hit == HIT_B:  self._cy1 = min(float(ih), max(cy1+dy, cy0+20))
        elif self._hit == HIT_L:  self._cx0 = max(0.0, min(cx0+dx, cx1-20))
        elif self._hit == HIT_R:  self._cx1 = min(float(iw), max(cx1+dx, cx0+20))
        self.update()

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton: return
        mx, my = e.pos().x(), e.pos().y()
        self._hit = self._hit_test(mx, my)
        if self._hit != HIT_NONE:
            self._drag_start = (mx, my)
            self._drag_box   = (self._cx0, self._cy0, self._cx1, self._cy1)
            self.setCursor(self._cursor_for_hit(self._hit))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._hit = HIT_NONE
            self._drag_start = None; self._drag_box = None
            self.setCursor(self._cursor_for_hit(self._hit_test(e.pos().x(), e.pos().y())))


class CropDialog(QDialog):
    def __init__(self, pil_img: Image.Image, parent=None):
        super().__init__(parent)
        self.setWindowTitle("调整裁剪区域")
        self.setModal(True); self.setMinimumSize(620, 540)
        self.setStyleSheet(f"QDialog{{background:{C['panel']};}}")
        lo = QVBoxLayout(self); lo.setContentsMargins(20,16,20,16); lo.setSpacing(10)
        tip = QLabel("拖动框内移动裁剪框  ·  拖动四角等比缩放  ·  拖动四边自由拉伸")
        tip.setStyleSheet(f"font-size:11px;color:{C['text2']};")
        lo.addWidget(tip)
        self.canvas = CropCanvas(pil_img)
        lo.addWidget(self.canvas, 1)
        reset_btn = QPushButton("重置裁剪框")
        reset_btn.setFixedHeight(34)
        reset_btn.setStyleSheet(f"""
            QPushButton{{background:{C['card']};color:{C['text2']};
                border:1px solid {C['border']};border-radius:8px;
                min-width:100px;font-size:13px;}}
            QPushButton:hover{{background:{C['card_hover']};}}""")
        reset_btn.clicked.connect(self.canvas.reset)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok_btn = btns.button(QDialogButtonBox.Ok); ok_btn.setText("应用裁剪")
        cancel_btn = btns.button(QDialogButtonBox.Cancel); cancel_btn.setText("取消")
        for btn in [ok_btn, cancel_btn]:
            btn.setFixedHeight(34); btn.setMinimumWidth(90)
        ok_btn.setStyleSheet(f"""QPushButton{{
            background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 {C['accent']},stop:1 {C['accent2']});
            color:#fff;border:none;border-radius:8px;font-size:13px;font-weight:600;}}""")
        cancel_btn.setStyleSheet(f"""QPushButton{{
            background:{C['card']};color:{C['text2']};
            border:1px solid {C['border']};border-radius:8px;font-size:13px;}}
            QPushButton:hover{{background:{C['card_hover']};}}""")
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        btn_row = QHBoxLayout()
        btn_row.addWidget(reset_btn); btn_row.addStretch(); btn_row.addWidget(btns)
        lo.addLayout(btn_row)

    def get_cropped(self) -> Image.Image:
        return self.canvas.get_cropped()


# ─────────────────────────────────────────────
# 后台抠图线程
# ─────────────────────────────────────────────
class RemoveBgWorker(QThread):
    done = pyqtSignal(object)   # RGBA PIL Image
    fail = pyqtSignal(str)

    def __init__(self, img: Image.Image):
        super().__init__()
        self._img = img

    def run(self):
        try:
            from u2net_engine import remove_background
            rgba = remove_background(self._img)
            self.done.emit(rgba)
        except Exception as e:
            self.fail.emit(str(e))


# ─────────────────────────────────────────────
# 后台排版线程
# ─────────────────────────────────────────────
class LayoutWorker(QThread):
    done = pyqtSignal(object, str)
    fail = pyqtSignal(str)

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
    loaded = pyqtSignal(object)  # PIL Image

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
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._pil = None
        self._idle()

    def _idle(self):
        self.setText("拖入照片\n\n点击选择文件\n\nJPG · PNG · BMP")
        self.setStyleSheet(self._IDLE)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            p, _ = QFileDialog.getOpenFileName(
                self, "选择证件照", "",
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
            self._update_thumb(img)
            self.setStyleSheet(self._ACTIVE)
            self.setToolTip(f"{Path(path).name}  {img.width}×{img.height}px")
            self.loaded.emit(img)
        except Exception as ex:
            QMessageBox.warning(self, "加载失败", str(ex))

    def _update_thumb(self, img: Image.Image):
        thumb = img.copy()
        thumb.thumbnail((self.width()-20 or 260, self.height()-20 or 140), Image.LANCZOS)
        self.setPixmap(pil_to_qpixmap(thumb))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._pil: self._update_thumb(self._pil)


# ─────────────────────────────────────────────
# 背景色选择按钮
# ─────────────────────────────────────────────
class BgColorBtn(QPushButton):
    """单个背景色圆形按钮"""
    selected = pyqtSignal(tuple)  # (r,g,b)

    def __init__(self, color: tuple, label: str = "", is_custom: bool = False):
        super().__init__()
        self._color = color
        self._label = label
        self._is_custom = is_custom
        self._active = False
        self.setFixedSize(44, 44)
        self.setToolTip(label)
        self._update_style()
        self.clicked.connect(self._on_click)

    def _update_style(self):
        r, g, b = self._color
        border = f"3px solid {C['accent']}" if self._active else f"2px solid {C['border']}"
        if self._is_custom:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                        stop:0 #ff6b6b, stop:0.33 #ffd93d,
                        stop:0.66 #6bcb77, stop:1 #4d96ff);
                    border: {border};
                    border-radius: 22px;
                    font-size: 18px;
                    color: white;
                }}
                QPushButton:hover {{ border-color: #818cf8; }}
            """)
            self.setText("+")
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: rgb({r},{g},{b});
                    border: {border};
                    border-radius: 22px;
                }}
                QPushButton:hover {{ border-color: #818cf8; }}
            """)

    def set_active(self, on: bool):
        self._active = on
        self._update_style()

    def set_color(self, color: tuple):
        self._color = color
        self._update_style()

    def _on_click(self):
        if self._is_custom:
            c = QColorDialog.getColor(
                QColor(*self._color), self.window(), "选择自定义背景色")
            if c.isValid():
                self._color = (c.red(), c.green(), c.blue())
                self._update_style()
        self.selected.emit(self._color)


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
        lo = QVBoxLayout(self); lo.setContentsMargins(10,8,10,8); lo.setSpacing(2)
        self._t = QLabel(name)
        self._t.setStyleSheet(f"font-size:13px;font-weight:600;color:{C['text']};background:transparent;")
        self._t.setAlignment(Qt.AlignCenter)
        self._d = QLabel(desc)
        self._d.setStyleSheet(f"font-size:9px;color:{C['text2']};background:transparent;")
        self._d.setAlignment(Qt.AlignCenter)
        lo.addWidget(self._t); lo.addWidget(self._d)
        self.setFixedHeight(60)
        self.setStyleSheet(self._N)

    def activate(self, on: bool):
        if on:
            self.setStyleSheet(self._A)
            self._t.setStyleSheet("font-size:13px;font-weight:600;color:#fff;background:transparent;")
            self._d.setStyleSheet("font-size:9px;color:rgba(255,255,255,0.7);background:transparent;")
        else:
            self.setStyleSheet(self._N)
            self._t.setStyleSheet(f"font-size:13px;font-weight:600;color:{C['text']};background:transparent;")
            self._d.setStyleSheet(f"font-size:9px;color:{C['text2']};background:transparent;")


# ─────────────────────────────────────────────
# 预览区
# ─────────────────────────────────────────────
class Preview(QLabel):
    def __init__(self, placeholder="预览将在此显示"):
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._img = None
        self._placeholder = placeholder
        self._idle()

    def _idle(self):
        self.setText(self._placeholder)
        self.setStyleSheet(f"""
            QLabel {{
                background:{C['preview']};
                border:1px solid {C['border']};
                border-radius:16px;
                color:{C['muted']};
                font-size:13px;
            }}
        """)

    def show_img(self, img: Image.Image):
        self._img = img
        self._render()
        self.setStyleSheet(f"""
            QLabel {{
                background:{C['preview']};
                border:1px solid {C['border']};
                border-radius:16px;
                padding:8px;
            }}
        """)

    def _render(self):
        if not self._img: return
        w = max(self.width()-24, 100); h = max(self.height()-24, 100)
        t = self._img.copy(); t.thumbnail((w, h), Image.LANCZOS)
        if self._img.mode == "RGBA":
            self.setPixmap(pil_rgba_to_qpixmap(t))
        else:
            self.setPixmap(pil_to_qpixmap(t))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._img: self._render()

    def result(self): return self._img


# ─────────────────────────────────────────────
# 状态标签
# ─────────────────────────────────────────────
class StatusLabel(QLabel):
    def set_info(self, text):
        self.setText(text)
        self.setStyleSheet(f"font-size:11px;color:{C['text2']};")

    def set_ok(self, text):
        self.setText(text)
        self.setStyleSheet(f"font-size:11px;color:{C['success']};")

    def set_warn(self, text):
        self.setText(text)
        self.setStyleSheet(f"font-size:11px;color:{C['warning']};")

    def set_err(self, text):
        self.setText(text)
        self.setStyleSheet("font-size:11px;color:#f87171;")


# ─────────────────────────────────────────────
# 主窗口
# ─────────────────────────────────────────────
class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("证件照排版工具")
        self.resize(1280, 820)
        self.setMinimumSize(1000, 680)
        _ico = Path(__file__).parent / "icon.ico"
        if not _ico.exists(): _ico = Path(__file__).parent / "icon.png"
        if _ico.exists(): self.setWindowIcon(QIcon(str(_ico)))
        self.setStyleSheet(
            f"QMainWindow,QWidget{{background:{C['bg']};color:{C['text']};"
            f"font-family:'PingFang SC','Microsoft YaHei',Arial,sans-serif;}}"
        )

        # ── 状态变量 ──
        self._orig_img   = None   # 原始上传图
        self._src_img    = None   # 裁剪后图（用于处理）
        self._fg_rgba    = None   # 抠图结果（RGBA）
        self._composed   = None   # 换背景后合成图（RGB）
        self._layout_img = None   # 排版结果
        self._cur_tmpl   = None   # 当前排版模板名
        self._bg_color   = (255, 255, 255)  # 当前背景色
        self._bg_image   = None   # 当前背景图
        self._use_bg_img = False  # 是否使用图片背景
        self._rm_worker  = None
        self._ly_worker  = None

        self._build()

    # ─── UI 构建 ───
    def _build(self):
        root = QWidget(); self.setCentralWidget(root)
        main_h = QHBoxLayout(root)
        main_h.setContentsMargins(0, 0, 0, 0)
        main_h.setSpacing(0)

        # ══ 左侧控制面板 ══
        left = QWidget()
        left.setFixedWidth(360)
        left.setStyleSheet(f"background:{C['panel']};border-right:1px solid {C['border']};")
        scroll = QScrollArea()
        scroll.setWidget(left)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"QScrollArea{{border:none;background:{C['panel']};}} QScrollBar:vertical{{width:4px;background:{C['bg']};}} QScrollBar::handle:vertical{{background:{C['border']};border-radius:2px;}}")
        scroll.setFixedWidth(360)

        ll = QVBoxLayout(left)
        ll.setContentsMargins(22, 24, 22, 24)
        ll.setSpacing(14)

        # 品牌
        brand = QLabel("证件照排版工具")
        brand.setStyleSheet(f"font-size:18px;font-weight:700;color:{C['text']};letter-spacing:1px;")
        sub = QLabel("换背景  ·  自动排版  ·  本地离线")
        sub.setStyleSheet(f"font-size:9px;color:{C['muted']};letter-spacing:2px;margin-top:-4px;")
        ll.addWidget(brand); ll.addWidget(sub)
        ll.addWidget(divider())

        # ── STEP 1: 上传 ──
        ll.addWidget(section_label("STEP 1  ·  上传照片"))
        self.upload = UploadZone()
        self.upload.loaded.connect(self._on_load)
        ll.addWidget(self.upload)

        info_row = QHBoxLayout()
        self.info_lbl = StatusLabel("未选择照片")
        self.info_lbl.set_info("未选择照片")
        self.btn_crop = QPushButton("✂  调整裁剪")
        self.btn_crop.setEnabled(False)
        self.btn_crop.setFixedHeight(28)
        self.btn_crop.setStyleSheet(f"""
            QPushButton{{background:{C['card']};color:{C['accent_text']};
                border:1px solid {C['border_hi']};border-radius:7px;
                font-size:11px;font-weight:600;padding:0 10px;}}
            QPushButton:hover{{background:{C['card_hover']};}}
            QPushButton:disabled{{color:{C['muted']};border-color:{C['border']};}}""")
        self.btn_crop.clicked.connect(self._open_crop)
        info_row.addWidget(self.info_lbl); info_row.addStretch(); info_row.addWidget(self.btn_crop)
        ll.addLayout(info_row)

        # 抠图进度
        self.rm_prog = QProgressBar()
        self.rm_prog.setRange(0, 0); self.rm_prog.setFixedHeight(3); self.rm_prog.setVisible(False)
        self.rm_prog.setStyleSheet(f"""
            QProgressBar{{background:{C['border']};border:none;border-radius:2px;}}
            QProgressBar::chunk{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 {C['accent']},stop:1 {C['accent2']});border-radius:2px;}}""")
        ll.addWidget(self.rm_prog)

        self.rm_status = StatusLabel("")
        ll.addWidget(self.rm_status)

        ll.addWidget(divider())

        # ── STEP 2: 换背景 ──
        ll.addWidget(section_label("STEP 2  ·  选择背景"))

        # 预设颜色
        bg_colors = [
            ((255,255,255), "白色"),
            ((67,  114, 196), "蓝色"),
            ((220, 50,  50),  "红色"),
            ((100, 180, 100), "绿色"),
            ((240, 240, 240), "浅灰"),
        ]
        color_row = QHBoxLayout(); color_row.setSpacing(8)
        self._bg_btns = []
        for color, label in bg_colors:
            btn = BgColorBtn(color, label)
            btn.selected.connect(self._on_bg_color)
            color_row.addWidget(btn)
            self._bg_btns.append(btn)
        # 自定义颜色按钮
        self._custom_btn = BgColorBtn((200, 200, 200), "自定义颜色", is_custom=True)
        self._custom_btn.selected.connect(self._on_bg_color)
        color_row.addWidget(self._custom_btn)
        color_row.addStretch()
        ll.addLayout(color_row)
        # 默认选中白色
        self._bg_btns[0].set_active(True)

        # 背景图片上传
        bg_img_row = QHBoxLayout()
        self.btn_bg_img = QPushButton("🖼  上传背景图片")
        self.btn_bg_img.setFixedHeight(32)
        self.btn_bg_img.setStyleSheet(f"""
            QPushButton{{background:{C['card']};color:{C['text2']};
                border:1px solid {C['border']};border-radius:8px;
                font-size:12px;padding:0 12px;}}
            QPushButton:hover{{background:{C['card_hover']};border-color:{C['border_hi']};color:{C['text']};}}""")
        self.btn_bg_img.clicked.connect(self._pick_bg_image)
        self.btn_clear_bg = QPushButton("× 清除")
        self.btn_clear_bg.setFixedHeight(32)
        self.btn_clear_bg.setEnabled(False)
        self.btn_clear_bg.setStyleSheet(f"""
            QPushButton{{background:{C['card']};color:{C['muted']};
                border:1px solid {C['border']};border-radius:8px;
                font-size:12px;padding:0 10px;}}
            QPushButton:hover{{color:#f87171;border-color:#f87171;}}
            QPushButton:disabled{{color:{C['muted']};}}""")
        self.btn_clear_bg.clicked.connect(self._clear_bg_image)
        bg_img_row.addWidget(self.btn_bg_img); bg_img_row.addWidget(self.btn_clear_bg)
        bg_img_row.addStretch()
        ll.addLayout(bg_img_row)

        self.bg_status = StatusLabel("当前背景：白色")
        self.bg_status.set_info("当前背景：白色")
        ll.addWidget(self.bg_status)

        ll.addWidget(divider())

        # ── STEP 3: 排版 ──
        ll.addWidget(section_label("STEP 3  ·  选择排版"))

        TEMPLATES = [
            ("一寸排版",      "3×3 · 9张 · 5寸竖"),
            ("二寸排版",      "2×2 · 4张 · 5寸竖"),
            ("小二寸排版",    "2×2 · 4张 · 5寸竖"),
            ("三寸排版",      "1×2 · 2张 · 5寸竖"),
            ("驾驶证排版",    "5×2 · 10张 · 5寸横"),
            ("一寸+二寸排版", "9+4张 · 7寸横"),
            ("结婚照排版",    "2×2 · 4张 · 5寸横"),
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

        # 排版进度
        self.ly_prog = QProgressBar()
        self.ly_prog.setRange(0,0); self.ly_prog.setFixedHeight(3); self.ly_prog.setVisible(False)
        self.ly_prog.setStyleSheet(f"""
            QProgressBar{{background:{C['border']};border:none;border-radius:2px;}}
            QProgressBar::chunk{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 {C['accent']},stop:1 {C['accent2']});border-radius:2px;}}""")
        ll.addWidget(self.ly_prog)

        ll.addStretch()
        ll.addWidget(divider())

        # ── 导出按钮组 ──
        ll.addWidget(section_label("导出"))

        self.btn_exp_layout = QPushButton("导出排版图  ·  JPG 300DPI")
        self.btn_exp_layout.setEnabled(False)
        self.btn_exp_layout.setFixedHeight(44)
        self.btn_exp_layout.setStyleSheet(f"""
            QPushButton{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 {C['accent']},stop:1 {C['accent2']});
                color:#fff;font-size:13px;font-weight:600;
                border:none;border-radius:10px;letter-spacing:0.5px;}}
            QPushButton:hover{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 #818cf8,stop:1 #a78bfa);}}
            QPushButton:disabled{{background:{C['card']};color:{C['muted']};}}""")
        self.btn_exp_layout.clicked.connect(self._export_layout)
        ll.addWidget(self.btn_exp_layout)

        exp2_row = QHBoxLayout(); exp2_row.setSpacing(8)
        self.btn_exp_jpg = QPushButton("保存换背景 JPG")
        self.btn_exp_png = QPushButton("保存透明 PNG")
        for btn in [self.btn_exp_jpg, self.btn_exp_png]:
            btn.setEnabled(False)
            btn.setFixedHeight(36)
            btn.setStyleSheet(f"""
                QPushButton{{background:{C['card']};color:{C['text2']};
                    border:1px solid {C['border']};border-radius:9px;
                    font-size:12px;}}
                QPushButton:hover{{background:{C['card_hover']};border-color:{C['border_hi']};color:{C['text']};}}
                QPushButton:disabled{{color:{C['muted']};}}""")
        self.btn_exp_jpg.clicked.connect(self._export_composed)
        self.btn_exp_png.clicked.connect(self._export_transparent)
        exp2_row.addWidget(self.btn_exp_jpg); exp2_row.addWidget(self.btn_exp_png)
        ll.addLayout(exp2_row)

        # ══ 右侧预览区 ══
        right = QWidget(); right.setStyleSheet(f"background:{C['bg']};")
        rl = QVBoxLayout(right); rl.setContentsMargins(24, 24, 24, 24); rl.setSpacing(10)

        # 预览标题行
        ph = QHBoxLayout()
        ptitle = QLabel("预览")
        ptitle.setStyleSheet(f"font-size:13px;font-weight:600;color:{C['text2']};letter-spacing:1px;")
        self.pinfo = StatusLabel("")
        ph.addWidget(ptitle); ph.addStretch(); ph.addWidget(self.pinfo)
        rl.addLayout(ph)

        # 双预览区：左=换背景结果，右=排版结果
        preview_h = QHBoxLayout(); preview_h.setSpacing(16)

        left_pv = QVBoxLayout()
        lbl_pv1 = QLabel("换背景效果")
        lbl_pv1.setStyleSheet(f"font-size:10px;color:{C['muted']};letter-spacing:1px;")
        lbl_pv1.setAlignment(Qt.AlignCenter)
        self.preview_bg = Preview("上传照片后\n自动显示换背景效果")
        left_pv.addWidget(lbl_pv1); left_pv.addWidget(self.preview_bg)

        right_pv = QVBoxLayout()
        lbl_pv2 = QLabel("排版效果")
        lbl_pv2.setStyleSheet(f"font-size:10px;color:{C['muted']};letter-spacing:1px;")
        lbl_pv2.setAlignment(Qt.AlignCenter)
        self.preview_layout = Preview("选择排版类型后\n自动显示排版效果")
        right_pv.addWidget(lbl_pv2); right_pv.addWidget(self.preview_layout)

        preview_h.addLayout(left_pv, 1)
        preview_h.addLayout(right_pv, 2)
        rl.addLayout(preview_h, 1)

        main_h.addWidget(scroll)
        main_h.addWidget(right, 1)

    # ─── 事件处理 ───

    def _on_load(self, img: Image.Image):
        """照片上传后：保存原图，启动抠图"""
        self._orig_img = img
        self._src_img  = img
        w, h = img.size
        self.info_lbl.set_ok(f"{w} × {h} px")
        self.btn_crop.setEnabled(True)
        # 清空旧结果
        self._fg_rgba = None
        self._composed = None
        self._layout_img = None
        self.btn_exp_jpg.setEnabled(False)
        self.btn_exp_png.setEnabled(False)
        self.btn_exp_layout.setEnabled(False)
        # 启动抠图
        self._start_remove_bg()

    def _stop_worker(self, worker):
        """安全停止并销毁 QThread，防止 macOS 崩溃"""
        if worker is not None:
            try:
                worker.quit()
                worker.wait(3000)  # 最多等 3 秒
            except Exception:
                pass
        return None

    def _start_remove_bg(self):
        if self._src_img is None: return
        self._rm_worker = self._stop_worker(self._rm_worker)
        self.rm_prog.setVisible(True)
        self.rm_status.set_info("正在抠图（U²-Net）...")
        self._rm_worker = RemoveBgWorker(self._src_img)
        self._rm_worker.done.connect(self._on_rm_done)
        self._rm_worker.fail.connect(self._on_rm_fail)
        self._rm_worker.finished.connect(self._rm_worker.deleteLater)
        self._rm_worker.start()

    def _on_rm_done(self, rgba: Image.Image):
        self.rm_prog.setVisible(False)
        self._fg_rgba = rgba
        self.rm_status.set_ok("抠图完成 ✓")
        # 合成当前背景
        self._compose_and_show()
        # 如果已有排版模板选中，重新生成排版
        if self._cur_tmpl:
            self._on_tmpl(self._cur_tmpl)

    def _on_rm_fail(self, msg: str):
        self.rm_prog.setVisible(False)
        self.rm_status.set_err(f"抠图失败：{msg}")
        # 抠图失败时，用原图继续排版
        self._composed = self._src_img
        self.preview_bg.show_img(self._src_img)
        self.btn_exp_jpg.setEnabled(True)
        if self._cur_tmpl:
            self._on_tmpl(self._cur_tmpl)

    def _compose_and_show(self):
        """用当前背景设置合成图像并更新预览"""
        if self._fg_rgba is None: return
        from u2net_engine import compose_background
        if self._use_bg_img and self._bg_image:
            composed = compose_background(self._fg_rgba, bg_image=self._bg_image)
        else:
            composed = compose_background(self._fg_rgba, bg_color=self._bg_color)
        self._composed = composed
        self.preview_bg.show_img(composed)
        self.btn_exp_jpg.setEnabled(True)
        self.btn_exp_png.setEnabled(True)
        # 如果有排版模板，重新生成排版
        if self._cur_tmpl:
            self._on_tmpl(self._cur_tmpl)

    def _on_bg_color(self, color: tuple):
        """切换纯色背景"""
        self._bg_color   = color
        self._use_bg_img = False
        # 更新按钮激活状态
        for btn in self._bg_btns:
            btn.set_active(btn._color == color)
        self._custom_btn.set_active(False)
        # 如果是自定义颜色，激活自定义按钮
        preset_colors = [btn._color for btn in self._bg_btns]
        if color not in preset_colors:
            self._custom_btn.set_active(True)
            self._custom_btn.set_color(color)
        r, g, b = color
        self.bg_status.set_info(f"当前背景：RGB({r},{g},{b})")
        self._compose_and_show()

    def _pick_bg_image(self):
        """选择背景图片"""
        p, _ = QFileDialog.getOpenFileName(
            self, "选择背景图片", "",
            "图片 (*.jpg *.jpeg *.png *.bmp *.tiff *.webp)")
        if not p: return
        try:
            self._bg_image   = Image.open(p).convert("RGB")
            self._use_bg_img = True
            # 取消颜色按钮激活
            for btn in self._bg_btns: btn.set_active(False)
            self._custom_btn.set_active(False)
            self.btn_clear_bg.setEnabled(True)
            self.bg_status.set_ok(f"背景图：{Path(p).name}")
            self._compose_and_show()
        except Exception as ex:
            QMessageBox.warning(self, "加载失败", str(ex))

    def _clear_bg_image(self):
        """清除背景图片，恢复纯色"""
        self._bg_image   = None
        self._use_bg_img = False
        self.btn_clear_bg.setEnabled(False)
        # 恢复白色激活
        self._bg_btns[0].set_active(True)
        self._bg_color = (255, 255, 255)
        self.bg_status.set_info("当前背景：白色")
        self._compose_and_show()

    def _open_crop(self):
        if not self._orig_img: return
        dlg = CropDialog(self._orig_img, self)
        if dlg.exec_() == QDialog.Accepted:
            cropped = dlg.get_cropped()
            self._src_img = cropped
            w, h = cropped.size
            self.info_lbl.set_ok(f"已裁剪  {w} × {h} px")
            # 更新上传区缩略图
            thumb = cropped.copy()
            thumb.thumbnail((320, 160), Image.LANCZOS)
            self.upload.setPixmap(pil_to_qpixmap(thumb))
            # 重新抠图
            self._fg_rgba = None
            self._start_remove_bg()

    def _on_tmpl(self, name: str):
        """选择排版模板：用换背景后的图生成排版"""
        for n, b in self._btns.items(): b.activate(n == name)
        self._cur_tmpl = name
        # 确定用于排版的图像
        src = self._composed if self._composed else self._src_img
        if src is None:
            self.pinfo.set_info("请先上传照片")
            return
        self.ly_prog.setVisible(True)
        self.btn_exp_layout.setEnabled(False)
        self.pinfo.set_info("排版生成中...")
        self._ly_worker = self._stop_worker(self._ly_worker)
        self._ly_worker = LayoutWorker(src, name)
        self._ly_worker.done.connect(self._on_ly_done)
        self._ly_worker.fail.connect(self._on_ly_fail)
        self._ly_worker.finished.connect(self._ly_worker.deleteLater)
        self._ly_worker.start()

    def _on_ly_done(self, img: Image.Image, name: str):
        self._layout_img = img
        self.ly_prog.setVisible(False)
        self.preview_layout.show_img(img)
        self.btn_exp_layout.setEnabled(True)
        w, h = img.size
        self.pinfo.set_ok(f"{name}  ·  {w}×{h}px  ·  300 DPI")

    def _on_ly_fail(self, msg: str):
        self.ly_prog.setVisible(False)
        self.pinfo.set_err(f"排版失败：{msg}")

    # ─── 导出 ───
    def _export_layout(self):
        if not self._layout_img: return
        name = f"{self._cur_tmpl or '排版'}.jpg"
        path, _ = QFileDialog.getSaveFileName(self, "导出排版图片", name, "JPEG (*.jpg *.jpeg)")
        if path:
            if not path.lower().endswith(('.jpg','.jpeg')): path += '.jpg'
            try:
                save_layout(self._layout_img, path)
                self.pinfo.set_ok(f"已导出：{Path(path).name}")
            except Exception as e:
                QMessageBox.critical(self, "导出失败", str(e))

    def _export_composed(self):
        if not self._composed: return
        path, _ = QFileDialog.getSaveFileName(
            self, "保存换背景图片", "换背景.jpg", "JPEG (*.jpg *.jpeg)")
        if path:
            if not path.lower().endswith(('.jpg','.jpeg')): path += '.jpg'
            try:
                self._composed.convert("RGB").save(path, "JPEG", quality=95, dpi=(300,300))
                self.pinfo.set_ok(f"已保存：{Path(path).name}")
            except Exception as e:
                QMessageBox.critical(self, "保存失败", str(e))

    def _export_transparent(self):
        if not self._fg_rgba: return
        path, _ = QFileDialog.getSaveFileName(
            self, "保存透明 PNG", "透明抠图.png", "PNG (*.png)")
        if path:
            if not path.lower().endswith('.png'): path += '.png'
            try:
                self._fg_rgba.save(path, "PNG")
                self.pinfo.set_ok(f"已保存：{Path(path).name}")
            except Exception as e:
                QMessageBox.critical(self, "保存失败", str(e))


    def closeEvent(self, event):
        """关闭窗口时确保所有后台线程安全退出"""
        self._rm_worker = self._stop_worker(self._rm_worker)
        self._ly_worker = self._stop_worker(self._ly_worker)
        event.accept()
# ─────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("证件照排版工具")
    app.setStyle("Fusion")

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
