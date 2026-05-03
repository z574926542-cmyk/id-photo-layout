"""
证件照便捷工具 v20.0
修复清单（相对 v19.0）：
  F1  软件名称：build.yml 中 --name 改为 ZJZPhoto，mv 后为「证件照便捷工具.app」，
      同时修改 CFBundleExecutable 字段，彻底解决 macOS Finder 显示旧名问题
  F2  画笔颜色跟随背景：换背景后 preview_bg._img 同步更新为新合成图，
      并同步 _bg_color 和 _use_bg_img 状态到 PaintablePreview
  F3  画笔圆形光标：画笔模式下用 QBitmap 生成圆形 QCursor，大小跟随 brush_size
  F4  画笔羽化边缘：_draw_at 使用 Gaussian 渐变 alpha 实现软边画笔（feather 参数）
  F5  _compose_and_show 调用 preview_bg.sync_img(composed) 同步 _img，
      防止画笔操作后 result() 返回旧图
继承 v19.0 全部 R1-R15 稳定性修复
"""
from __future__ import annotations
import sys
import traceback
from pathlib import Path
from PyQt5.QtCore    import Qt, QTimer, pyqtSignal
from PyQt5.QtGui     import (QColor, QImage, QIcon, QPalette, QPainter,
                              QPen, QBrush, QPixmap, QBitmap, QCursor)
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel,
                              QVBoxLayout, QHBoxLayout, QPushButton,
                              QFileDialog, QMessageBox, QFrame, QSlider,
                              QSizePolicy, QProgressBar, QDialog,
                              QDialogButtonBox, QScrollArea, QCheckBox)
from PIL import Image, ImageFilter
import numpy as np

# ─────────────────────────────────────────────
# 延迟导入（PyInstaller frozen 环境兼容）
# ─────────────────────────────────────────────
def _rmbg_remove_background(img):
    from u2net_engine import remove_background
    return remove_background(img)

def _rmbg_compose(fg_rgba, bg_color, bg_image):
    from u2net_engine import compose_background
    return compose_background(fg_rgba, bg_color=bg_color, bg_image=bg_image)

from layout_engine import generate_layout, save_layout

# ─────────────────────────────────────────────
# 颜色主题（深色专业工具风格）
# ─────────────────────────────────────────────
C = {
    "bg":         "#1a1b1e",
    "panel":      "#1e1f23",
    "card":       "#25262b",
    "card_hover": "#2c2d33",
    "preview":    "#16171a",
    "border":     "#2e2f35",
    "border_hi":  "#4a4b55",
    "text":       "#e8e9ed",
    "text2":      "#9ca3af",
    "muted":      "#6b7280",
    "accent":     "#6366f1",
    "accent2":    "#8b5cf6",
    "success":    "#34d399",
    "warning":    "#fbbf24",
}

# ─────────────────────────────────────────────
# 安全图片加载
# ─────────────────────────────────────────────
MAX_LONG_EDGE = 4000
MAX_PIXELS    = 20_000_000

def safe_load_image(path: str):
    """
    安全加载图片：
    - 检测文件损坏
    - 超大图等比缩小（最长边 4000px 或总像素 2000 万）
    返回 (img: Image.Image, was_resized: bool, orig_size: tuple)
    """
    # Step 1: 检测文件是否损坏（verify 会关闭文件句柄）
    try:
        with Image.open(path) as probe:
            probe.verify()
    except Exception as e:
        raise IOError(f"图片文件损坏或格式不支持：{e}") from e
    # Step 2: 重新打开并转 RGB（verify 后文件已关闭，必须重新 open）
    try:
        img = Image.open(path).convert("RGB")
    except Exception as e:
        raise IOError(f"图片读取失败：{e}") from e
    orig_size = img.size
    was_resized = False
    orig_w, orig_h = orig_size
    if orig_w <= 0 or orig_h <= 0:
        raise IOError("图片尺寸异常（宽或高为 0）")
    long_edge = max(orig_w, orig_h)
    total_px  = orig_w * orig_h
    if long_edge > MAX_LONG_EDGE or total_px > MAX_PIXELS:
        scale = min(MAX_LONG_EDGE / long_edge,
                    (MAX_PIXELS / total_px) ** 0.5)
        new_w = max(1, round(orig_w * scale))
        new_h = max(1, round(orig_h * scale))
        img = img.resize((new_w, new_h), Image.LANCZOS)
        was_resized = True
    return img, was_resized, orig_size

# ─────────────────────────────────────────────
# PIL ↔ QPixmap（.copy() 防 GC 悬空）
# ─────────────────────────────────────────────
def pil_to_qpixmap(img: Image.Image) -> QPixmap:
    if img.mode != "RGB":
        img = img.convert("RGB")
    data = img.tobytes("raw", "RGB")
    qi = QImage(data, img.width, img.height, img.width * 3, QImage.Format_RGB888)
    return QPixmap.fromImage(qi.copy())

def pil_rgba_to_qpixmap(img: Image.Image) -> QPixmap:
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qi = QImage(data, img.width, img.height, img.width * 4, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qi.copy())

# ─────────────────────────────────────────────
# 画笔圆形光标生成（F3）
# ─────────────────────────────────────────────
def make_brush_cursor(size_px: int) -> QCursor:
    """
    生成圆形画笔光标，size_px 为显示直径（像素）。
    光标中心为圆心，圆形轮廓为白色描边+黑色外框，类似 PS 画笔光标。
    """
    d = max(8, size_px)
    # 创建透明 QPixmap
    pm = QPixmap(d + 2, d + 2)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    cx = (d + 2) // 2
    cy = (d + 2) // 2
    r  = d // 2 - 1
    # 黑色外框（2px）
    painter.setPen(QPen(QColor(0, 0, 0, 180), 2))
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(cx - r - 1, cy - r - 1, (r + 1) * 2, (r + 1) * 2)
    # 白色内圆（1px）
    painter.setPen(QPen(QColor(255, 255, 255, 220), 1))
    painter.drawEllipse(cx - r, cy - r, r * 2, r * 2)
    # 中心十字（小）
    painter.setPen(QPen(QColor(255, 255, 255, 180), 1))
    painter.drawLine(cx - 3, cy, cx + 3, cy)
    painter.drawLine(cx, cy - 3, cx, cy + 3)
    painter.end()
    return QCursor(pm, cx, cy)

# ─────────────────────────────────────────────
# 辅助组件
# ─────────────────────────────────────────────
def divider() -> QFrame:
    f = QFrame(); f.setFrameShape(QFrame.HLine); f.setFixedHeight(1)
    f.setStyleSheet(f"background:{C['border']};border:none;"); return f

def section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"font-size:10px;font-weight:700;color:{C['muted']};"
                      f"letter-spacing:1.5px;padding:2px 0;")
    return lbl

class StatusLabel(QLabel):
    def __init__(self, text=""):
        super().__init__(text); self.setWordWrap(True)
        self.setStyleSheet(f"font-size:11px;color:{C['text2']};")
    def set_info(self, t): self.setText(t); self.setStyleSheet(f"font-size:11px;color:{C['text2']};")
    def set_ok(self,   t): self.setText(t); self.setStyleSheet(f"font-size:11px;color:{C['success']};")
    def set_warn(self, t): self.setText(t); self.setStyleSheet(f"font-size:11px;color:{C['warning']};")
    def set_err(self,  t): self.setText(t); self.setStyleSheet("font-size:11px;color:#f87171;")

def make_btn(text, primary=False, danger=False, small=False) -> QPushButton:
    b = QPushButton(text)
    h = 30 if small else 36; fs = 11 if small else 12
    b.setFixedHeight(h)
    if primary:
        b.setStyleSheet(f"""
            QPushButton{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 {C['accent']},stop:1 {C['accent2']});
                color:#fff;font-size:{fs}px;font-weight:600;border:none;border-radius:8px;}}
            QPushButton:hover{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 #818cf8,stop:1 #a78bfa);}}
            QPushButton:disabled{{background:{C['card']};color:{C['muted']};}}""")
    elif danger:
        b.setStyleSheet(f"""
            QPushButton{{background:{C['card']};color:{C['muted']};
                border:1px solid {C['border']};border-radius:8px;font-size:{fs}px;}}
            QPushButton:hover{{color:#f87171;border-color:#f87171;}}
            QPushButton:disabled{{color:{C['muted']};}}""")
    else:
        b.setStyleSheet(f"""
            QPushButton{{background:{C['card']};color:{C['text2']};
                border:1px solid {C['border']};border-radius:8px;font-size:{fs}px;}}
            QPushButton:hover{{background:{C['card_hover']};border-color:{C['border_hi']};color:{C['text']};}}
            QPushButton:disabled{{color:{C['muted']};}}""")
    return b

# ─────────────────────────────────────────────
# 上传区
# ─────────────────────────────────────────────
class UploadZone(QLabel):
    loaded = pyqtSignal(object)
    _IDLE   = (f"QLabel{{background:{C['card']};border:2px dashed {C['border_hi']};"
               f"border-radius:10px;color:{C['text2']};font-size:12px;}}"
               f"QLabel:hover{{background:{C['card_hover']};border-color:#818cf8;}}")
    _ACTIVE = f"QLabel{{background:{C['card']};border:2px solid {C['accent']};border-radius:10px;}}"

    def __init__(self):
        super().__init__(); self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignCenter); self.setFixedHeight(110)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._pil = None; self._idle()

    def _idle(self):
        self.setText("拖入照片 · 点击选择\nJPG · PNG · BMP"); self.setStyleSheet(self._IDLE)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            p, _ = QFileDialog.getOpenFileName(self, "选择证件照", "",
                "图片 (*.jpg *.jpeg *.png *.bmp *.tiff *.webp)")
            if p: self._load(p)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()

    def dropEvent(self, e):
        urls = e.mimeData().urls()
        if urls: self._load(urls[0].toLocalFile())

    def _load(self, path):
        try:
            img, was_resized, orig_size = safe_load_image(path)
        except IOError as ex:
            QMessageBox.warning(self, "图片加载失败",
                f"无法打开图片：\n{ex}\n\n请检查文件是否损坏或格式是否支持。")
            return
        self._pil = img
        self.setStyleSheet(self._ACTIVE)
        t = img.copy()
        t.thumbnail((self.width() - 16 or 260, self.height() - 16 or 90), Image.LANCZOS)
        px = pil_to_qpixmap(t)
        self.setPixmap(px)
        self.setToolTip(f"{Path(path).name}  {img.width}×{img.height}px")
        self.loaded.emit((img, was_resized, orig_size))

# ─────────────────────────────────────────────
# 普通预览标签
# ─────────────────────────────────────────────
class PreviewLabel(QLabel):
    def __init__(self, placeholder=""):
        super().__init__(); self._ph = placeholder; self._img = None
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(200, 200)
        self.setStyleSheet(f"background:{C['preview']};border:1px solid {C['border']};"
                           f"border-radius:8px;color:{C['text2']};font-size:12px;")
        if placeholder: self.setText(placeholder)

    def show_img(self, pil_img):
        self._img = pil_img; self._refresh_pixmap()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._img: self._refresh_pixmap()

    def _refresh_pixmap(self):
        if not self._img: return
        w = self.width() - 4
        h = self.height() - 4
        if w <= 0 or h <= 0: return
        t = self._img.copy()
        t.thumbnail((w, h), Image.LANCZOS)
        if self._img.mode == "RGBA":
            px = pil_rgba_to_qpixmap(t)
        else:
            px = pil_to_qpixmap(t)
        self.setPixmap(px)

# ─────────────────────────────────────────────
# 可绘制预览（画笔工具）
# ─────────────────────────────────────────────
class PaintablePreview(PreviewLabel):
    painted = pyqtSignal()   # 鼠标松开时 emit 一次

    def __init__(self, placeholder=""):
        super().__init__(placeholder)
        self._paint_mode  = False
        self._brush_size  = 20     # 显示像素直径
        self._feather     = True   # 羽化开关
        self._bg_color    = None   # None = 透明擦除，(r,g,b) = 填色
        self._use_bg_img  = False  # 是否使用背景图模式
        self._drawing     = False
        self._brush_cursor = None  # 缓存当前画笔光标

    # ─── F2: 同步内部 _img（换背景后必须调用）───
    def sync_img(self, pil_img):
        """同步内部图片（不刷新显示，仅更新 _img 用于画笔操作）"""
        self._img = pil_img

    # ─── F3: 画笔模式切换（更新圆形光标）───
    def set_paint_mode(self, v: bool):
        self._paint_mode = v
        if v:
            self._update_cursor()
        else:
            self.setCursor(Qt.ArrowCursor)

    def _update_cursor(self):
        """根据当前 brush_size 更新圆形光标"""
        self._brush_cursor = make_brush_cursor(self._brush_size)
        self.setCursor(self._brush_cursor)

    def set_brush_size(self, s: int):
        self._brush_size = s
        if self._paint_mode:
            self._update_cursor()

    def set_bg_color(self, color):
        """
        F2: 设置画笔颜色，跟随当前背景状态：
        - color = None：透明擦除模式
        - color = (r,g,b)：填充背景色
        """
        self._bg_color = color

    def set_bg_img_mode(self, use_img: bool):
        """F2: 背景图模式时，画笔画白色（不透明遮盖）"""
        self._use_bg_img = use_img

    def result(self) -> Image.Image | None:
        return self._img

    # ─── 鼠标事件 ───
    def mousePressEvent(self, e):
        if self._paint_mode and e.button() == Qt.LeftButton and self._img:
            self._drawing = True
            self._draw_at(e.pos())

    def mouseMoveEvent(self, e):
        if self._paint_mode and self._drawing and self._img:
            self._draw_at(e.pos())

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            if self._paint_mode and self._img and self._drawing:
                self._drawing = False
                self.painted.emit()   # 只在松开时 emit 一次

    # ─── 核心绘制（F4: 羽化边缘）───
    def _draw_at(self, pos):
        if not self._img: return
        img = self._img
        disp_w = self.width()
        disp_h = self.height()
        img_w, img_h = img.size
        # R1: scale=0 除零保护
        if img_w <= 0 or img_h <= 0 or disp_w <= 0 or disp_h <= 0:
            return
        scale = min(disp_w / img_w, disp_h / img_h)
        if scale <= 0:
            return
        off_x = (disp_w - img_w * scale) / 2
        off_y = (disp_h - img_h * scale) / 2
        ix = int((pos.x() - off_x) / scale)
        iy = int((pos.y() - off_y) / scale)
        r  = max(1, int(self._brush_size / scale / 2))

        # 确保图片是 RGBA 模式
        if img.mode != "RGBA":
            img = img.convert("RGBA")
            self._img = img

        arr = np.array(img, dtype=np.float32)
        img_h_arr, img_w_arr = arr.shape[:2]

        # 边界裁剪
        y0 = max(0, iy - r); y1 = min(img_h_arr, iy + r + 1)
        x0 = max(0, ix - r); x1 = min(img_w_arr, ix + r + 1)
        if y0 >= y1 or x0 >= x1:
            return

        # 生成距离场（用于羽化）
        cy_range = np.arange(y0, y1) - iy
        cx_range = np.arange(x0, x1) - ix
        cx_grid, cy_grid = np.meshgrid(cx_range, cy_range)
        dist2 = cx_grid.astype(np.float32)**2 + cy_grid.astype(np.float32)**2
        r2 = float(r * r)
        inside = dist2 <= r2

        if self._feather and r > 2:
            # 羽化：从圆心到边缘 alpha 线性渐变（内 80% 满，外 20% 渐变）
            feather_start = (r * 0.7) ** 2
            strength = np.where(
                dist2 <= feather_start,
                1.0,
                np.where(inside,
                         1.0 - (dist2 - feather_start) / max(1.0, r2 - feather_start),
                         0.0)
            ).astype(np.float32)
        else:
            strength = inside.astype(np.float32)

        # R2: 确保 mask 形状与切片一致
        if strength.shape != arr[y0:y1, x0:x1, 0].shape:
            return

        # F2: 画笔颜色跟随背景
        if self._use_bg_img:
            # 背景图模式：画白色不透明
            paint_color = np.array([255.0, 255.0, 255.0], dtype=np.float32)
            target_alpha = 255.0
        elif self._bg_color is not None:
            # 纯色背景：画背景色
            paint_color = np.array([float(self._bg_color[0]),
                                    float(self._bg_color[1]),
                                    float(self._bg_color[2])], dtype=np.float32)
            target_alpha = 255.0
        else:
            # 透明模式：擦除（alpha → 0）
            paint_color = None
            target_alpha = 0.0

        sub = arr[y0:y1, x0:x1]
        if paint_color is not None:
            # 用 strength 做插值：原色 → 目标色
            for c in range(3):
                sub[:, :, c] = sub[:, :, c] * (1.0 - strength) + paint_color[c] * strength
            sub[:, :, 3] = sub[:, :, 3] * (1.0 - strength) + target_alpha * strength
        else:
            # 擦除：alpha 乘以 (1 - strength)
            sub[:, :, 3] = sub[:, :, 3] * (1.0 - strength)

        arr[y0:y1, x0:x1] = sub
        self._img = Image.fromarray(arr.astype(np.uint8), "RGBA")
        self._refresh_pixmap()

# ─────────────────────────────────────────────
# PS 风格裁剪框
# ─────────────────────────────────────────────
HIT_NONE=0; HIT_MOVE=1; HIT_TL=2; HIT_TR=3; HIT_BL=4; HIT_BR=5
HIT_T=6; HIT_B=7; HIT_L=8; HIT_R=9
HANDLE=10

class CropCanvas(QLabel):
    def __init__(self, pil_img):
        super().__init__(); self._pil = pil_img
        self._iw, self._ih = pil_img.size
        self._cx0 = self._iw * 0.1; self._cy0 = self._ih * 0.1
        self._cx1 = self._iw * 0.9; self._cy1 = self._ih * 0.9
        self._hit = HIT_NONE; self._drag_start = None; self._drag_box = None
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)

    def reset(self):
        self._cx0=self._iw*0.1; self._cy0=self._ih*0.1
        self._cx1=self._iw*0.9; self._cy1=self._ih*0.9
        self.update()

    def _scale(self):
        """返回 (scale, off_x, off_y)，R3: 除零保护"""
        iw, ih = self._iw, self._ih
        dw, dh = self.width(), self.height()
        if iw <= 0 or ih <= 0 or dw <= 0 or dh <= 0:
            return 1.0, 0.0, 0.0
        s = min(dw / iw, dh / ih)
        ox = (dw - iw * s) / 2
        oy = (dh - ih * s) / 2
        return s, ox, oy

    def _img2disp(self, ix, iy):
        s, ox, oy = self._scale()
        return ox + ix * s, oy + iy * s

    def _disp2img(self, dx, dy):
        s, ox, oy = self._scale()
        if s == 0: return 0.0, 0.0
        return (dx - ox) / s, (dy - oy) / s

    def _hit_test(self, dx, dy):
        x0d, y0d = self._img2disp(self._cx0, self._cy0)
        x1d, y1d = self._img2disp(self._cx1, self._cy1)
        H = HANDLE
        def near(a, b): return abs(a - b) < H
        if near(dx, x0d) and near(dy, y0d): return HIT_TL
        if near(dx, x1d) and near(dy, y0d): return HIT_TR
        if near(dx, x0d) and near(dy, y1d): return HIT_BL
        if near(dx, x1d) and near(dy, y1d): return HIT_BR
        if near(dy, y0d) and x0d < dx < x1d: return HIT_T
        if near(dy, y1d) and x0d < dx < x1d: return HIT_B
        if near(dx, x0d) and y0d < dy < y1d: return HIT_L
        if near(dx, x1d) and y0d < dy < y1d: return HIT_R
        if x0d < dx < x1d and y0d < dy < y1d: return HIT_MOVE
        return HIT_NONE

    def paintEvent(self, e):
        super().paintEvent(e)
        s, ox, oy = self._scale()
        if s <= 0: return
        # 绘制图片
        t = self._pil.copy()
        dw, dh = self.width(), self.height()
        if dw <= 0 or dh <= 0: return
        t.thumbnail((dw, dh), Image.LANCZOS)
        px = pil_to_qpixmap(t)
        p = QPainter(self)
        p.drawPixmap(int(ox), int(oy), px)
        # 半透明遮罩
        x0d, y0d = self._img2disp(self._cx0, self._cy0)
        x1d, y1d = self._img2disp(self._cx1, self._cy1)
        p.fillRect(int(ox), int(oy), int(self._iw * s), int(self._ih * s),
                   QColor(0, 0, 0, 100))
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.fillRect(int(x0d), int(y0d), int(x1d - x0d), int(y1d - y0d),
                   QColor(0, 0, 0, 255))
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        # 裁剪框边线
        p.setPen(QPen(QColor(255, 255, 255, 200), 1))
        p.drawRect(int(x0d), int(y0d), int(x1d - x0d), int(y1d - y0d))
        # 三等分辅助线
        p.setPen(QPen(QColor(255, 255, 255, 80), 1))
        for i in (1, 2):
            xg = x0d + (x1d - x0d) * i / 3
            yg = y0d + (y1d - y0d) * i / 3
            p.drawLine(int(xg), int(y0d), int(xg), int(y1d))
            p.drawLine(int(x0d), int(yg), int(x1d), int(yg))
        # 角点控制柄
        p.setPen(QPen(QColor(255, 255, 255), 2))
        for hx, hy in [(x0d, y0d), (x1d, y0d), (x0d, y1d), (x1d, y1d)]:
            p.drawRect(int(hx) - HANDLE//2, int(hy) - HANDLE//2, HANDLE, HANDLE)
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._hit = self._hit_test(e.x(), e.y())
            self._drag_start = (e.x(), e.y())
            self._drag_box = (self._cx0, self._cy0, self._cx1, self._cy1)

    def mouseMoveEvent(self, e):
        if self._drag_start is None:
            cursors = {
                HIT_TL: Qt.SizeFDiagCursor, HIT_BR: Qt.SizeFDiagCursor,
                HIT_TR: Qt.SizeBDiagCursor, HIT_BL: Qt.SizeBDiagCursor,
                HIT_T:  Qt.SizeVerCursor,   HIT_B:  Qt.SizeVerCursor,
                HIT_L:  Qt.SizeHorCursor,   HIT_R:  Qt.SizeHorCursor,
                HIT_MOVE: Qt.SizeAllCursor,
            }
            self.setCursor(cursors.get(self._hit_test(e.x(), e.y()), Qt.ArrowCursor))
            return
        s, ox, oy = self._scale()
        if s <= 0: return
        dx = (e.x() - self._drag_start[0]) / s
        dy = (e.y() - self._drag_start[1]) / s
        x0, y0, x1, y1 = self._drag_box
        h = self._hit
        if h == HIT_MOVE:
            w_ = x1 - x0; h_ = y1 - y0
            x0 = max(0, min(self._iw - w_, x0 + dx))
            y0 = max(0, min(self._ih - h_, y0 + dy))
            x1 = x0 + w_; y1 = y0 + h_
        else:
            if h in (HIT_TL, HIT_BL, HIT_L): x0 = max(0, min(x1 - 10, x0 + dx))
            if h in (HIT_TR, HIT_BR, HIT_R): x1 = min(self._iw, max(x0 + 10, x1 + dx))
            if h in (HIT_TL, HIT_TR, HIT_T): y0 = max(0, min(y1 - 10, y0 + dy))
            if h in (HIT_BL, HIT_BR, HIT_B): y1 = min(self._ih, max(y0 + 10, y1 + dy))
        self._cx0, self._cy0, self._cx1, self._cy1 = x0, y0, x1, y1
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_start = None; self._drag_box = None

    def get_cropped(self) -> Image.Image:
        """R4: 坐标规范化，防止反转/相等导致 crop 崩溃"""
        x0 = min(self._cx0, self._cx1)
        y0 = min(self._cy0, self._cy1)
        x1 = max(self._cx0, self._cx1)
        y1 = max(self._cy0, self._cy1)
        if x1 - x0 < 4 or y1 - y0 < 4:
            return self._pil.copy()
        return self._pil.crop((int(x0), int(y0), int(x1), int(y1)))

# ─────────────────────────────────────────────
# 裁剪对话框
# ─────────────────────────────────────────────
class CropDialog(QDialog):
    def __init__(self, pil_img, parent=None):
        super().__init__(parent)
        self.setWindowTitle("调整裁剪区域")
        self.setMinimumSize(700, 560)
        vl = QVBoxLayout(self)
        self._canvas = CropCanvas(pil_img)
        vl.addWidget(self._canvas)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Reset |
                                QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        btns.button(QDialogButtonBox.Reset).clicked.connect(self._canvas.reset)
        vl.addWidget(btns)

    def get_result(self) -> Image.Image:
        return self._canvas.get_cropped()

# ─────────────────────────────────────────────
# 后台线程
# ─────────────────────────────────────────────
from PyQt5.QtCore import QThread

class RemoveBgWorker(QThread):
    done = pyqtSignal(object)
    fail = pyqtSignal(str)

    def __init__(self, img: Image.Image, parent=None):
        super().__init__(parent)
        self._img = img

    def run(self):
        try:
            result = _rmbg_remove_background(self._img)
            self.done.emit(result)
        except Exception:
            self.fail.emit(traceback.format_exc())

class LayoutWorker(QThread):
    done = pyqtSignal(object)
    fail = pyqtSignal(str)

    def __init__(self, img: Image.Image, tmpl: str, parent=None):
        super().__init__(parent)
        self._img  = img
        self._tmpl = tmpl

    def run(self):
        try:
            result = generate_layout(self._img, self._tmpl)
            self.done.emit(result)
        except Exception:
            self.fail.emit(traceback.format_exc())

# ─────────────────────────────────────────────
# 主窗口
# ─────────────────────────────────────────────
class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("证件照便捷工具")
        self.setMinimumSize(1100, 680)
        self.setStyleSheet(f"QMainWindow{{background:{C['bg']};}}")
        # 状态变量
        self._orig_img   = None
        self._src_img    = None
        self._fg_rgba    = None
        self._composed   = None
        self._layout_img = None
        self._bg_color   = (255, 255, 255)
        self._use_bg_img = False
        self._bg_image   = None
        self._cur_tmpl   = None
        self._rm_worker  = None
        self._ly_worker  = None
        self._is_removing  = False
        self._is_layouting = False
        # 画笔防抖定时器
        self._paint_debounce = QTimer(self)
        self._paint_debounce.setSingleShot(True)
        self._paint_debounce.setInterval(200)
        self._paint_debounce.timeout.connect(self._trigger_layout_after_paint)
        self._build()

    # ─── 线程状态管理 ───
    def _set_removing(self, v: bool):
        self._is_removing = v
        if hasattr(self, 'btn_remove_bg'):
            self.btn_remove_bg.setEnabled(not v)

    def _set_layouting(self, v: bool):
        self._is_layouting = v

    def _stop_worker(self, w):
        """安全停止 worker，R13: 超时后 terminate"""
        if w is None: return None
        try:
            w.done.disconnect()
        except Exception: pass
        try:
            w.fail.disconnect()
        except Exception: pass
        try:
            w.finished.disconnect()
        except Exception: pass
        if w.isRunning():
            w.quit()
            if not w.wait(3000):
                w.terminate()
                w.wait(1000)
        return None

    # ─── UI 构建 ───
    def _build(self):
        root = QWidget(); self.setCentralWidget(root)
        hl = QHBoxLayout(root); hl.setContentsMargins(0, 0, 0, 0); hl.setSpacing(0)

        # ── 左侧控制面板 ──
        panel = QWidget(); panel.setFixedWidth(295)
        panel.setStyleSheet(f"background:{C['panel']};")
        ll = QVBoxLayout(panel); ll.setContentsMargins(12, 12, 12, 12); ll.setSpacing(8)

        title = QLabel("证件照便捷工具"); title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"font-size:15px;font-weight:700;color:{C['text']};padding:4px 0;")
        ll.addWidget(title); ll.addWidget(divider())

        # 上传区
        ll.addWidget(section_label("上传照片"))
        self.upload_zone = UploadZone()
        self.upload_zone.loaded.connect(self._on_upload)
        ll.addWidget(self.upload_zone)

        # 裁剪按钮
        self.btn_crop = make_btn("✂  调整裁剪区域")
        self.btn_crop.setEnabled(False)
        self.btn_crop.clicked.connect(self._on_crop)
        ll.addWidget(self.btn_crop)

        ll.addWidget(divider())

        # 抠图区
        ll.addWidget(section_label("AI 抠图"))
        self.btn_remove_bg = make_btn("🔮  一键抠图", primary=True)
        self.btn_remove_bg.setEnabled(False)
        self.btn_remove_bg.clicked.connect(self._start_remove_bg)
        ll.addWidget(self.btn_remove_bg)
        self.rm_prog = QProgressBar(); self.rm_prog.setRange(0, 0)
        self.rm_prog.setFixedHeight(4); self.rm_prog.setVisible(False)
        self.rm_prog.setStyleSheet(
            f"QProgressBar{{background:{C['border']};border:none;border-radius:2px;}}"
            f"QProgressBar::chunk{{background:{C['accent']};border-radius:2px;}}")
        ll.addWidget(self.rm_prog)
        self.rm_status = StatusLabel("上传照片后点击抠图")
        ll.addWidget(self.rm_status)

        ll.addWidget(divider())

        # 背景颜色选择
        ll.addWidget(section_label("背景颜色"))
        bg_colors = [
            ("白色", (255, 255, 255)), ("红色", (220, 35, 35)),
            ("蓝色", (67, 114, 196)), ("深蓝", (0, 51, 153)),
            ("浅蓝", (173, 216, 230)), ("灰色", (192, 192, 192)),
        ]
        bg_grid = QWidget()
        bg_gl = QHBoxLayout(bg_grid); bg_gl.setContentsMargins(0, 0, 0, 0); bg_gl.setSpacing(4)
        for name, rgb in bg_colors:
            b = QPushButton()
            b.setFixedSize(36, 28)
            b.setToolTip(name)
            r, g, bv = rgb
            b.setStyleSheet(
                f"QPushButton{{background:rgb({r},{g},{bv});border:2px solid {C['border']};"
                f"border-radius:4px;}}"
                f"QPushButton:hover{{border-color:#fff;}}")
            b.clicked.connect(lambda checked, c=rgb, n=name: self._set_bg_color(c, n))
            bg_gl.addWidget(b)
        bg_gl.addStretch()
        ll.addWidget(bg_grid)

        # 背景图按钮
        bg_img_row = QHBoxLayout(); bg_img_row.setSpacing(6)
        self.btn_bg_img = make_btn("🖼  选择背景图", small=True)
        self.btn_bg_img.clicked.connect(self._pick_bg_image)
        self.btn_bg_clear = make_btn("✕  清除背景图", small=True, danger=True)
        self.btn_bg_clear.setEnabled(False)
        self.btn_bg_clear.clicked.connect(self._clear_bg_image)
        bg_img_row.addWidget(self.btn_bg_img); bg_img_row.addWidget(self.btn_bg_clear)
        ll.addLayout(bg_img_row)
        self.bg_status = StatusLabel("当前：白色背景")
        ll.addWidget(self.bg_status)

        ll.addWidget(divider())

        # 排版模板
        ll.addWidget(section_label("排版模板"))
        tmpls = ["一寸排版", "二寸排版", "小二寸排版", "三寸排版",
                 "驾驶证排版", "一寸+二寸排版", "结婚照排版"]
        self._btns = {}
        tmpl_grid = QWidget()
        tgl = QVBoxLayout(tmpl_grid); tgl.setContentsMargins(0, 0, 0, 0); tgl.setSpacing(4)
        row = None
        for i, name in enumerate(tmpls):
            if i % 2 == 0:
                row = QHBoxLayout(); row.setSpacing(4); tgl.addLayout(row)
            b = QPushButton(name); b.setCheckable(True); b.setFixedHeight(30)
            b.setStyleSheet(
                f"QPushButton{{background:{C['card']};color:{C['text2']};"
                f"border:1px solid {C['border']};border-radius:6px;font-size:11px;padding:0 8px;}}"
                f"QPushButton:checked{{background:{C['accent']};color:#fff;border-color:{C['accent']};}}") 
            b.clicked.connect(lambda checked, n=name: self._on_tmpl(n))
            self._btns[name] = b
            row.addWidget(b)
        if len(tmpls) % 2 == 1:
            row.addStretch()
        ll.addWidget(tmpl_grid)

        # 排版进度
        self.ly_prog = QProgressBar(); self.ly_prog.setRange(0, 0)
        self.ly_prog.setFixedHeight(4); self.ly_prog.setVisible(False)
        self.ly_prog.setStyleSheet(
            f"QProgressBar{{background:{C['border']};border:none;border-radius:2px;}}"
            f"QProgressBar::chunk{{background:{C['success']};border-radius:2px;}}")
        ll.addWidget(self.ly_prog)
        self.pinfo = StatusLabel("上传照片后选择排版模板")
        ll.addWidget(self.pinfo)

        ll.addStretch()
        hl.addWidget(panel)

        # ── 右侧预览区（左：换背景，右：排版）──
        preview_area = QWidget()
        preview_area.setStyleSheet(f"background:{C['bg']};")
        pl = QHBoxLayout(preview_area); pl.setContentsMargins(12, 12, 12, 12); pl.setSpacing(12)

        # 换背景预览列
        bg_vl = QVBoxLayout(); bg_vl.setSpacing(6)
        bg_title = QLabel("换背景预览")
        bg_title.setStyleSheet(f"font-size:11px;font-weight:600;color:{C['text2']};letter-spacing:1px;")
        bg_vl.addWidget(bg_title)
        self.preview_bg = PaintablePreview("抠图后在此预览\n换背景效果")
        self.preview_bg.painted.connect(self._on_painted)
        bg_vl.addWidget(self.preview_bg, 1)

        # 画笔工具栏
        paint_bar = QWidget()
        paint_hl = QHBoxLayout(paint_bar)
        paint_hl.setContentsMargins(0, 0, 0, 0); paint_hl.setSpacing(6)
        self.btn_paint = QPushButton("✏  画笔"); self.btn_paint.setCheckable(True)
        self.btn_paint.setFixedHeight(28)
        self.btn_paint.setStyleSheet(
            f"QPushButton{{background:{C['card']};color:{C['text2']};"
            f"border:1px solid {C['border']};border-radius:6px;font-size:11px;padding:0 8px;}}"
            f"QPushButton:checked{{background:{C['accent']};color:#fff;border-color:{C['accent']};}}") 
        self.btn_paint.toggled.connect(self._on_paint_toggle)
        paint_hl.addWidget(self.btn_paint)

        brush_lbl = QLabel("大小:")
        brush_lbl.setStyleSheet(f"font-size:11px;color:{C['text2']};background:transparent;")
        paint_hl.addWidget(brush_lbl)

        self.brush_slider = QSlider(Qt.Horizontal)
        self.brush_slider.setRange(4, 80); self.brush_slider.setValue(20)
        self.brush_slider.setFixedWidth(90)
        self.brush_slider.setStyleSheet(
            f"QSlider::groove:horizontal{{height:4px;background:{C['border']};border-radius:2px;}}"
            f"QSlider::handle:horizontal{{width:12px;height:12px;margin:-4px 0;"
            f"background:{C['accent']};border-radius:6px;}}"
            f"QSlider::sub-page:horizontal{{background:{C['accent']};border-radius:2px;}}")
        self.brush_slider.valueChanged.connect(self._on_brush_size)
        paint_hl.addWidget(self.brush_slider)

        self.brush_size_lbl = QLabel("20px"); self.brush_size_lbl.setFixedWidth(32)
        self.brush_size_lbl.setStyleSheet(f"font-size:11px;color:{C['text2']};background:transparent;")
        paint_hl.addWidget(self.brush_size_lbl)

        # 羽化开关
        self.chk_feather = QCheckBox("羽化")
        self.chk_feather.setChecked(True)
        self.chk_feather.setStyleSheet(f"font-size:11px;color:{C['text2']};background:transparent;")
        self.chk_feather.toggled.connect(self._on_feather_toggle)
        paint_hl.addWidget(self.chk_feather)

        paint_hl.addStretch()
        bg_vl.addWidget(paint_bar)

        # 换背景导出按钮
        bg_exp_row = QHBoxLayout(); bg_exp_row.setSpacing(8)
        self.btn_save_jpg = make_btn("💾  保存换背景 JPG", primary=True)
        self.btn_save_jpg.setEnabled(False)
        self.btn_save_jpg.clicked.connect(self._export_composed)
        self.btn_save_png = make_btn("🔲  保存透明 PNG")
        self.btn_save_png.setEnabled(False)
        self.btn_save_png.clicked.connect(self._export_transparent)
        bg_exp_row.addWidget(self.btn_save_jpg); bg_exp_row.addWidget(self.btn_save_png)
        bg_vl.addLayout(bg_exp_row)
        self.pinfo_bg = StatusLabel(""); bg_vl.addWidget(self.pinfo_bg)

        pl.addLayout(bg_vl, 1)

        # 排版预览列
        ly_vl = QVBoxLayout(); ly_vl.setSpacing(6)
        ly_title = QLabel("排版预览")
        ly_title.setStyleSheet(f"font-size:11px;font-weight:600;color:{C['text2']};letter-spacing:1px;")
        ly_vl.addWidget(ly_title)
        self.preview_ly = PreviewLabel("选择排版模板后\n在此预览排版效果")
        ly_vl.addWidget(self.preview_ly, 1)

        # 排版导出按钮
        self.btn_exp_layout = make_btn("📐  导出排版图 JPG 300DPI", primary=True)
        self.btn_exp_layout.setEnabled(False)
        self.btn_exp_layout.clicked.connect(self._export_layout)
        ly_vl.addWidget(self.btn_exp_layout)
        pl.addLayout(ly_vl, 1)

        hl.addWidget(preview_area, 1)

    # ─── 上传处理 ───
    def _on_upload(self, payload):
        try:
            img, was_resized, orig_size = payload
        except (TypeError, ValueError):
            QMessageBox.warning(self, "错误", "图片加载异常，请重试")
            return
        self._orig_img = img
        self._src_img  = img
        self._fg_rgba  = None
        self._composed = None
        self._layout_img = None
        self.btn_crop.setEnabled(True)
        self.btn_remove_bg.setEnabled(True)
        self.btn_save_png.setEnabled(False)
        self.btn_save_jpg.setEnabled(False)
        self.btn_exp_layout.setEnabled(False)
        self.rm_status.set_info("照片已加载，点击「一键抠图」开始")
        if was_resized:
            ow, oh = orig_size
            nw, nh = img.size
            self.rm_status.set_warn(
                f"图片较大（{ow}×{oh}），已自动优化为 {nw}×{nh}，不影响证件照和 A4 排版使用。")

    # ─── 裁剪 ───
    def _on_crop(self):
        if not self._src_img: return
        dlg = CropDialog(self._src_img, self)
        if dlg.exec_() == QDialog.Accepted:
            cropped = dlg.get_result()
            if cropped and cropped.size[0] > 0 and cropped.size[1] > 0:
                self._src_img = cropped
                self._fg_rgba = None
                self._composed = None
                self.rm_status.set_info("裁剪完成，请重新抠图")
                self.btn_save_png.setEnabled(False)
                self.btn_save_jpg.setEnabled(False)

    # ─── 抠图 ───
    def _start_remove_bg(self):
        if self._is_removing: return
        if not self._src_img:
            self.rm_status.set_warn("请先上传照片"); return
        self.rm_prog.setVisible(True)
        self.rm_status.set_info("AI 抠图中...")
        self._set_removing(True)
        self._rm_worker = self._stop_worker(self._rm_worker)
        self._rm_worker = RemoveBgWorker(self._src_img, parent=self)
        self._rm_worker.done.connect(self._on_rm_done)
        self._rm_worker.fail.connect(self._on_rm_fail)
        self._rm_worker.finished.connect(lambda: self._set_removing(False))
        self._rm_worker.start()

    def _on_rm_done(self, fg_rgba):
        if fg_rgba is None:
            self._on_rm_fail("抠图返回空结果")
            return
        if fg_rgba.mode != "RGBA":
            fg_rgba = fg_rgba.convert("RGBA")
        self._fg_rgba = fg_rgba
        self.rm_prog.setVisible(False)
        self.rm_status.set_ok("抠图完成 ✓")
        self.btn_save_png.setEnabled(True)
        self._compose_and_show()

    def _on_rm_fail(self, msg):
        self.rm_prog.setVisible(False)
        self.rm_status.set_err(f"抠图失败：{msg.split(chr(10))[0]}")

    # ─── 合成背景并显示（F2: 同步 preview_bg._img）───
    def _compose_and_show(self):
        if not self._fg_rgba: return
        fg = self._fg_rgba
        if self._bg_image is not None and self._use_bg_img:
            bw, bh = self._bg_image.size
            fw, fh = fg.size
            if bw <= 0 or bh <= 0 or fw <= 0 or fh <= 0:
                self.pinfo_bg.set_err("背景图尺寸异常，已切换为白色背景")
                self._use_bg_img = False
                bg = Image.new("RGBA", fg.size, (*self._bg_color, 255))
            else:
                bg = self._bg_image.convert("RGBA").resize(fg.size, Image.LANCZOS)
        else:
            bg = Image.new("RGBA", fg.size, (*self._bg_color, 255))

        composed = Image.alpha_composite(bg, fg)
        self._composed = composed

        # F2: 同步 preview_bg._img，让画笔操作基于最新合成图
        self.preview_bg.show_img(composed)
        self.preview_bg.sync_img(composed)

        # F2: 同步画笔颜色和背景模式
        if self._use_bg_img:
            self.preview_bg.set_bg_color(None)
            self.preview_bg.set_bg_img_mode(True)
        else:
            self.preview_bg.set_bg_color(self._bg_color)
            self.preview_bg.set_bg_img_mode(False)

        self.btn_save_jpg.setEnabled(True)
        if self._cur_tmpl:
            self._on_tmpl(self._cur_tmpl)

    # ─── 背景设置 ───
    def _set_bg_color(self, rgb, name):
        self._bg_color = rgb
        self._use_bg_img = False
        self.bg_status.set_info(f"当前：{name}背景")
        # F2: 同步画笔颜色
        self.preview_bg.set_bg_color(rgb)
        self.preview_bg.set_bg_img_mode(False)
        self._compose_and_show()

    def _pick_bg_image(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择背景图", "",
            "图片 (*.jpg *.jpeg *.png *.bmp *.webp)")
        if not p: return
        try:
            self._bg_image = Image.open(p).convert("RGBA")
        except Exception as e:
            QMessageBox.warning(self, "背景图加载失败", str(e))
            return
        self._use_bg_img = True
        self.bg_status.set_ok(f"背景图：{Path(p).name}")
        self.btn_bg_clear.setEnabled(True)
        # F2: 背景图模式下画笔画白色
        self.preview_bg.set_bg_color(None)
        self.preview_bg.set_bg_img_mode(True)
        self._compose_and_show()

    def _clear_bg_image(self):
        self._bg_image = None; self._use_bg_img = False
        self.bg_status.set_info("当前：白色背景")
        self.btn_bg_clear.setEnabled(False)
        # F2: 恢复纯色画笔
        self.preview_bg.set_bg_color(self._bg_color)
        self.preview_bg.set_bg_img_mode(False)
        self._compose_and_show()

    # ─── 画笔 ───
    def _on_paint_toggle(self, checked):
        self.preview_bg.set_paint_mode(checked)

    def _on_brush_size(self, v):
        self.brush_size_lbl.setText(f"{v}px")
        self.preview_bg.set_brush_size(v)

    def _on_feather_toggle(self, checked):
        self.preview_bg._feather = checked

    def _on_painted(self):
        """画笔松开时触发，用防抖定时器延迟更新排版"""
        img = self.preview_bg.result()
        if img:
            self._composed = img
            self._paint_debounce.start()

    def _trigger_layout_after_paint(self):
        if self._cur_tmpl:
            self._on_tmpl(self._cur_tmpl)

    # ─── 排版 ───
    def _on_tmpl(self, name):
        if self._is_layouting:
            return
        for n, b in self._btns.items(): b.setChecked(n == name)
        self._cur_tmpl = name
        src = self._composed if self._composed else self._src_img
        if src is None:
            self.pinfo.set_info("请先上传照片"); return
        self.ly_prog.setVisible(True)
        self.btn_exp_layout.setEnabled(False)
        self.pinfo.set_info("排版生成中...")
        self._set_layouting(True)
        self._ly_worker = self._stop_worker(self._ly_worker)
        self._ly_worker = LayoutWorker(src, name, parent=self)
        self._ly_worker.done.connect(self._on_ly_done)
        self._ly_worker.fail.connect(self._on_ly_fail)
        self._ly_worker.finished.connect(lambda: self._set_layouting(False))
        self._ly_worker.start()

    def _on_ly_done(self, result):
        self.ly_prog.setVisible(False)
        self._layout_img = result
        self.preview_ly.show_img(result)
        self.btn_exp_layout.setEnabled(True)
        self.pinfo.set_ok(f"排版完成 ✓  {result.width}×{result.height}px @ 300DPI")

    def _on_ly_fail(self, msg):
        self.ly_prog.setVisible(False)
        self.pinfo.set_err(f"排版失败：{msg.split(chr(10))[0]}")

    # ─── 导出 ───
    def _export_composed(self):
        if not self._composed: return
        path, _ = QFileDialog.getSaveFileName(self, "保存换背景 JPG", "证件照换背景.jpg",
            "JPEG 图片 (*.jpg *.jpeg)")
        if path:
            try:
                img_out = self._composed
                channels = img_out.split()
                if len(channels) == 4:
                    bg = Image.new("RGB", img_out.size, self._bg_color)
                    bg.paste(img_out.convert("RGB"), mask=channels[3])
                    img_out = bg
                else:
                    img_out = img_out.convert("RGB")
                img_out.save(path, "JPEG", quality=95, dpi=(300, 300))
                self.pinfo_bg.set_ok(f"已保存：{Path(path).name}")
            except Exception as e:
                QMessageBox.critical(self, "保存失败", str(e))

    def _export_transparent(self):
        if not self._fg_rgba: return
        path, _ = QFileDialog.getSaveFileName(self, "保存透明 PNG", "证件照透明.png",
            "PNG 图片 (*.png)")
        if path:
            try:
                img_out = self._fg_rgba
                if img_out.mode != "RGBA":
                    img_out = img_out.convert("RGBA")
                img_out.save(path, "PNG")
                self.pinfo_bg.set_ok(f"已保存：{Path(path).name}")
            except Exception as e:
                QMessageBox.critical(self, "保存失败", str(e))

    def _export_layout(self):
        if not self._layout_img: return
        path, _ = QFileDialog.getSaveFileName(self, "导出排版图 JPG", "证件照排版.jpg",
            "JPEG 图片 (*.jpg *.jpeg)")
        if path:
            try:
                save_layout(self._layout_img, path)
                self.pinfo.set_ok(f"已导出：{Path(path).name}")
            except Exception as e:
                QMessageBox.critical(self, "导出失败", str(e))

    # ─── 关闭保护 ───
    def closeEvent(self, event):
        if self._is_removing or self._is_layouting:
            QMessageBox.information(
                self, "请等待",
                "当前任务还在处理中，请等待完成后再退出。\n\n"
                "（抠图或排版完成后，再点击关闭按钮即可正常退出）"
            )
            event.ignore()
            return
        self._paint_debounce.stop()
        self._rm_worker = self._stop_worker(self._rm_worker)
        self._ly_worker = self._stop_worker(self._ly_worker)
        event.accept()

# ─────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("证件照便捷工具")
    app.setStyle("Fusion")
    _ip = Path(__file__).parent / "icon.ico"
    if not _ip.exists(): _ip = Path(__file__).parent / "icon.png"
    if _ip.exists(): app.setWindowIcon(QIcon(str(_ip)))
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
