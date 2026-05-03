"""
module_id_photo.py — 证件照便捷工具 证件照功能模块
包含：上传区、裁剪工具（PS风格）、画笔工具（圆形光标/撤销/跨背景保留）、
      抠图线程、排版线程、换背景预览、排版预览
"""
from __future__ import annotations
import traceback
from pathlib import Path
from copy import deepcopy

import numpy as np
from PIL import Image

from PyQt5.QtCore    import Qt, QTimer, pyqtSignal, QThread
from PyQt5.QtGui     import (QColor, QImage, QPainter, QPen, QPixmap, QCursor,
                              QKeySequence)
from PyQt5.QtWidgets import (QWidget, QLabel, QVBoxLayout, QHBoxLayout,
                              QPushButton, QFileDialog, QMessageBox, QFrame,
                              QSlider, QSizePolicy, QProgressBar, QDialog,
                              QDialogButtonBox, QCheckBox, QShortcut)

from utils import (C, safe_load_image, pil_to_qpixmap, pil_rgba_to_qpixmap,
                   make_btn, section_label, divider, StatusLabel, PreviewLabel,
                   make_brush_cursor)

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
# 上传区
# ─────────────────────────────────────────────
class UploadZone(QLabel):
    uploaded = pyqtSignal(object)  # (img, was_resized, orig_size)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setText("📷  点击或拖拽上传照片\n支持 JPG / PNG / BMP / WEBP")
        self.setAlignment(Qt.AlignCenter)
        self.setFixedHeight(90)
        self.setAcceptDrops(True)
        self.setStyleSheet(
            f"background:{C['card']};color:{C['text2']};font-size:12px;"
            f"border:2px dashed {C['border']};border-radius:8px;")
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._pick()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        urls = e.mimeData().urls()
        if urls:
            self._load_file(urls[0].toLocalFile())

    def _pick(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择照片", "",
            "图片 (*.jpg *.jpeg *.png *.bmp *.webp)")
        if path:
            self._load_file(path)

    def _load_file(self, path: str):
        try:
            img, was_resized, orig_size = safe_load_image(path)
        except ValueError as e:
            QMessageBox.warning(self, "图片加载失败", str(e))
            return
        self.uploaded.emit((img, was_resized, orig_size))

# ─────────────────────────────────────────────
# PS 风格裁剪框（框外暗化蒙版，框内透明）
# ─────────────────────────────────────────────
HIT_NONE=0; HIT_MOVE=1; HIT_TL=2; HIT_TR=3; HIT_BL=4; HIT_BR=5
HIT_T=6; HIT_B=7; HIT_L=8; HIT_R=9
HANDLE = 10

class CropCanvas(QLabel):
    def __init__(self, pil_img: Image.Image, parent=None):
        super().__init__(parent)
        self._pil = pil_img.convert("RGB")
        self._iw, self._ih = self._pil.size
        self._cx0 = 0.0; self._cy0 = 0.0
        self._cx1 = float(self._iw); self._cy1 = float(self._ih)
        self._hit = HIT_NONE
        self._drag_start = None
        self._drag_box   = None
        self.setMinimumSize(400, 400)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("background:#111;border:none;")

    def reset(self):
        self._cx0 = 0.0; self._cy0 = 0.0
        self._cx1 = float(self._iw); self._cy1 = float(self._ih)
        self.update()

    def _scale(self):
        """返回 (scale, offset_x, offset_y)"""
        dw = self.width(); dh = self.height()
        if dw <= 0 or dh <= 0 or self._iw <= 0 or self._ih <= 0:
            return 0, 0, 0
        s = min(dw / self._iw, dh / self._ih)
        ox = (dw - self._iw * s) / 2
        oy = (dh - self._ih * s) / 2
        return s, ox, oy

    def _img2disp(self, ix, iy):
        s, ox, oy = self._scale()
        return ox + ix * s, oy + iy * s

    def _hit_test(self, dx, dy):
        def near(a, b): return abs(a - b) < HANDLE + 2
        x0d, y0d = self._img2disp(self._cx0, self._cy0)
        x1d, y1d = self._img2disp(self._cx1, self._cy1)
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

        # 绘制原图
        t = self._pil.copy()
        dw, dh = self.width(), self.height()
        if dw <= 0 or dh <= 0: return
        t.thumbnail((dw, dh), Image.LANCZOS)
        px = pil_to_qpixmap(t)

        p = QPainter(self)
        p.drawPixmap(int(ox), int(oy), px)

        # ── PS 风格蒙版：画四个半透明黑色矩形（不用 CompositionMode_Clear）──
        x0d, y0d = self._img2disp(self._cx0, self._cy0)
        x1d, y1d = self._img2disp(self._cx1, self._cy1)
        iw_d = int(self._iw * s)
        ih_d = int(self._ih * s)
        mask_color = QColor(0, 0, 0, 130)

        # 上方
        p.fillRect(int(ox), int(oy), iw_d, max(0, int(y0d - oy)), mask_color)
        # 下方
        p.fillRect(int(ox), int(y1d), iw_d, max(0, int(oy + ih_d - y1d)), mask_color)
        # 左侧（裁剪框行高范围内）
        p.fillRect(int(ox), int(y0d), max(0, int(x0d - ox)), int(y1d - y0d), mask_color)
        # 右侧（裁剪框行高范围内）
        p.fillRect(int(x1d), int(y0d), max(0, int(ox + iw_d - x1d)), int(y1d - y0d), mask_color)

        # 裁剪框白色边线
        p.setPen(QPen(QColor(255, 255, 255, 220), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(int(x0d), int(y0d), int(x1d - x0d), int(y1d - y0d))

        # 三等分辅助线
        p.setPen(QPen(QColor(255, 255, 255, 70), 1))
        for i in (1, 2):
            xg = x0d + (x1d - x0d) * i / 3
            yg = y0d + (y1d - y0d) * i / 3
            p.drawLine(int(xg), int(y0d), int(xg), int(y1d))
            p.drawLine(int(x0d), int(yg), int(x1d), int(yg))

        # 四角 L 形控制柄
        p.setPen(QPen(QColor(255, 255, 255), 2))
        arm = 12
        for hx, hy, sx, sy in [
            (x0d, y0d,  1,  1), (x1d, y0d, -1,  1),
            (x0d, y1d,  1, -1), (x1d, y1d, -1, -1),
        ]:
            p.drawLine(int(hx), int(hy), int(hx + sx * arm), int(hy))
            p.drawLine(int(hx), int(hy), int(hx), int(hy + sy * arm))

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
            self._drag_start = None
            self._drag_box   = None

    def get_cropped(self) -> Image.Image:
        x0 = min(self._cx0, self._cx1); y0 = min(self._cy0, self._cy1)
        x1 = max(self._cx0, self._cx1); y1 = max(self._cy0, self._cy1)
        if x1 - x0 < 4 or y1 - y0 < 4:
            return self._pil.copy()
        return self._pil.crop((int(x0), int(y0), int(x1), int(y1)))


class CropDialog(QDialog):
    def __init__(self, pil_img: Image.Image, parent=None):
        super().__init__(parent)
        self.setWindowTitle("调整裁剪区域")
        self.setMinimumSize(700, 560)
        self.setStyleSheet(f"background:{C['bg']};")
        vl = QVBoxLayout(self)
        self._canvas = CropCanvas(pil_img)
        vl.addWidget(self._canvas)
        btns = QDialogButtonBox()
        btn_ok     = btns.addButton("确认裁剪", QDialogButtonBox.AcceptRole)
        btn_reset  = btns.addButton("重置",     QDialogButtonBox.ResetRole)
        btn_cancel = btns.addButton("取消",     QDialogButtonBox.RejectRole)
        btn_ok.setStyleSheet(
            f"background:{C['accent']};color:#fff;border:none;border-radius:6px;"
            f"padding:6px 18px;font-size:12px;font-weight:500;")
        btn_reset.setStyleSheet(
            f"background:{C['card']};color:{C['text']};border:1px solid {C['border']};"
            f"border-radius:6px;padding:6px 18px;font-size:12px;")
        btn_cancel.setStyleSheet(
            f"background:{C['card']};color:{C['text2']};border:1px solid {C['border']};"
            f"border-radius:6px;padding:6px 18px;font-size:12px;")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        btn_reset.clicked.connect(self._canvas.reset)
        vl.addWidget(btns)

    def get_result(self) -> Image.Image:
        return self._canvas.get_cropped()

# ─────────────────────────────────────────────
# 可绘制预览（画笔工具 + 撤销 + 跨背景保留）
# ─────────────────────────────────────────────
class PaintablePreview(PreviewLabel):
    painted = pyqtSignal()

    def __init__(self, placeholder="", parent=None):
        super().__init__(placeholder, parent)
        self._paint_mode  = False
        self._drawing     = False
        self._brush_size  = 20
        self._feather     = True
        self._bg_color    = (255, 255, 255)
        self._use_bg_img  = False
        self._brush_cursor = None

        # ── 画笔 mask（跨背景保留核心）──
        # _paint_mask: numpy bool array (h, w)，记录哪些像素被画笔修改过
        # _paint_color_map: numpy uint8 array (h, w, 4)，记录每个像素被画笔写入的 RGBA 值
        self._paint_mask      = None   # np.ndarray bool (h, w)
        self._paint_color_map = None   # np.ndarray uint8 (h, w, 4)

        # ── 撤销栈（每笔结束时保存快照）──
        # 每个元素是 (paint_mask_copy, paint_color_map_copy)
        self._undo_stack: list = []
        self._MAX_UNDO = 30

    # ── 同步内部图片（换背景后必须调用）──
    def sync_img(self, pil_img: Image.Image):
        """
        换背景后同步基础图片。
        如果已有 paint_mask，重新把画笔效果应用到新背景图上。
        """
        if pil_img.mode != "RGBA":
            pil_img = pil_img.convert("RGBA")
        base = np.array(pil_img, dtype=np.uint8)
        h, w = base.shape[:2]

        # 初始化或重置 mask（尺寸变化时重置）
        if self._paint_mask is None or self._paint_mask.shape != (h, w):
            self._paint_mask      = np.zeros((h, w), dtype=bool)
            self._paint_color_map = np.zeros((h, w, 4), dtype=np.uint8)

        # 把已有画笔效果叠加到新背景上
        if self._paint_mask.any():
            mask = self._paint_mask
            base[mask] = self._paint_color_map[mask]

        self._img = Image.fromarray(base, "RGBA")
        self._refresh_pixmap()

    def clear_paint(self):
        """清除所有画笔效果（不影响背景）"""
        self._paint_mask      = None
        self._paint_color_map = None
        self._undo_stack.clear()

    # ── 画笔模式切换 ──
    def set_paint_mode(self, v: bool):
        self._paint_mode = v
        if v:
            self._update_cursor()
        else:
            self.setCursor(Qt.ArrowCursor)

    def _update_cursor(self):
        self._brush_cursor = make_brush_cursor(self._brush_size)
        self.setCursor(self._brush_cursor)

    def set_brush_size(self, s: int):
        self._brush_size = s
        if self._paint_mode:
            self._update_cursor()

    def set_bg_color(self, color):
        self._bg_color = color

    def set_bg_img_mode(self, use_img: bool):
        self._use_bg_img = use_img

    def result(self) -> Image.Image | None:
        return self._img

    # ── 撤销 ──
    def undo(self):
        if not self._undo_stack: return
        self._paint_mask, self._paint_color_map = self._undo_stack.pop()
        # 重新从 _img 的基础上重建（需要外部调用 sync_img 触发重绘）
        self.painted.emit()

    def _save_undo_snapshot(self):
        if self._paint_mask is None: return
        self._undo_stack.append((
            self._paint_mask.copy(),
            self._paint_color_map.copy()
        ))
        if len(self._undo_stack) > self._MAX_UNDO:
            self._undo_stack.pop(0)

    # ── 鼠标事件 ──
    def mousePressEvent(self, e):
        if self._paint_mode and e.button() == Qt.LeftButton and self._img:
            self._drawing = True
            self._save_undo_snapshot()
            self._draw_at(e.pos())

    def mouseMoveEvent(self, e):
        if self._paint_mode and self._drawing and self._img:
            self._draw_at(e.pos())

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            if self._paint_mode and self._img and self._drawing:
                self._drawing = False
                self.painted.emit()

    # ── 核心绘制（羽化 + paint_mask 记录）──
    def _draw_at(self, pos):
        if not self._img: return
        img = self._img
        disp_w = self.width(); disp_h = self.height()
        img_w, img_h = img.size
        if img_w <= 0 or img_h <= 0 or disp_w <= 0 or disp_h <= 0: return
        scale = min(disp_w / img_w, disp_h / img_h)
        if scale <= 0: return
        off_x = (disp_w - img_w * scale) / 2
        off_y = (disp_h - img_h * scale) / 2
        ix = int((pos.x() - off_x) / scale)
        iy = int((pos.y() - off_y) / scale)
        r  = max(1, int(self._brush_size / scale / 2))

        if img.mode != "RGBA":
            img = img.convert("RGBA")
            self._img = img

        arr = np.array(img, dtype=np.float32)
        img_h_arr, img_w_arr = arr.shape[:2]

        # 初始化 mask（如果尚未初始化）
        if self._paint_mask is None or self._paint_mask.shape != (img_h_arr, img_w_arr):
            self._paint_mask      = np.zeros((img_h_arr, img_w_arr), dtype=bool)
            self._paint_color_map = np.zeros((img_h_arr, img_w_arr, 4), dtype=np.uint8)

        y0 = max(0, iy - r); y1 = min(img_h_arr, iy + r + 1)
        x0 = max(0, ix - r); x1 = min(img_w_arr, ix + r + 1)
        if y0 >= y1 or x0 >= x1: return

        cy_range = np.arange(y0, y1) - iy
        cx_range = np.arange(x0, x1) - ix
        cx_grid, cy_grid = np.meshgrid(cx_range, cy_range)
        dist2 = cx_grid.astype(np.float32)**2 + cy_grid.astype(np.float32)**2
        r2 = float(r * r)
        inside = dist2 <= r2

        if self._feather and r > 2:
            feather_start = (r * 0.7) ** 2
            strength = np.where(
                dist2 <= feather_start, 1.0,
                np.where(inside,
                         1.0 - (dist2 - feather_start) / max(1.0, r2 - feather_start),
                         0.0)
            ).astype(np.float32)
        else:
            strength = inside.astype(np.float32)

        if strength.shape != arr[y0:y1, x0:x1, 0].shape: return

        # 确定画笔颜色
        if self._use_bg_img:
            paint_color = np.array([255.0, 255.0, 255.0], dtype=np.float32)
            target_alpha = 255.0
        elif self._bg_color is not None:
            paint_color = np.array([float(self._bg_color[0]),
                                    float(self._bg_color[1]),
                                    float(self._bg_color[2])], dtype=np.float32)
            target_alpha = 255.0
        else:
            paint_color = None
            target_alpha = 0.0

        sub = arr[y0:y1, x0:x1]
        if paint_color is not None:
            for c in range(3):
                sub[:, :, c] = sub[:, :, c] * (1.0 - strength) + paint_color[c] * strength
            sub[:, :, 3] = sub[:, :, 3] * (1.0 - strength) + target_alpha * strength
        else:
            sub[:, :, 3] = sub[:, :, 3] * (1.0 - strength)

        arr[y0:y1, x0:x1] = sub
        result_arr = arr.astype(np.uint8)

        # 更新 paint_mask（strength > 0.1 的像素标记为已修改）
        modified = (strength > 0.1) & inside
        self._paint_mask[y0:y1, x0:x1] |= modified
        self._paint_color_map[y0:y1, x0:x1][modified] = result_arr[y0:y1, x0:x1][modified]

        self._img = Image.fromarray(result_arr, "RGBA")
        self._refresh_pixmap()

# ─────────────────────────────────────────────
# 后台线程
# ─────────────────────────────────────────────
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
# 证件照功能主面板
# ─────────────────────────────────────────────
class IdPhotoModule(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        # 状态变量
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
        self._setup_shortcuts()

    def _setup_shortcuts(self):
        """注册 Cmd+Z / Ctrl+Z 撤销快捷键"""
        undo_sc = QShortcut(QKeySequence.Undo, self)
        undo_sc.activated.connect(self._undo_paint)

    def _undo_paint(self):
        """撤销画笔操作"""
        if not self._fg_rgba: return
        self.preview_bg.undo()

    # ─── 线程管理 ───
    def _set_removing(self, v: bool):
        self._is_removing = v
        self.btn_remove_bg.setEnabled(not v)

    def _set_layouting(self, v: bool):
        self._is_layouting = v

    def _stop_worker(self, w):
        if w is None: return None
        for sig in (w.done, w.fail, w.finished):
            try: sig.disconnect()
            except Exception: pass
        if w.isRunning():
            w.quit()
            if not w.wait(3000):
                w.terminate()
                w.wait(1000)
        return None

    # ─── UI 构建 ───
    def _build(self):
        self.setStyleSheet(f"background:{C['bg']};")
        hl = QHBoxLayout(self)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(0)

        # ── 左侧控制面板 ──
        panel = QWidget()
        panel.setFixedWidth(290)
        panel.setStyleSheet(
            f"background:{C['panel']};border-right:1px solid {C['border']};")
        ll = QVBoxLayout(panel)
        ll.setContentsMargins(12, 12, 12, 12)
        ll.setSpacing(8)

        # 上传区
        self.upload_zone = UploadZone()
        self.upload_zone.uploaded.connect(self._on_upload)
        ll.addWidget(self.upload_zone)

        # 裁剪按钮
        self.btn_crop = make_btn("✂  调整裁剪区域")
        self.btn_crop.setEnabled(False)
        self.btn_crop.clicked.connect(self._on_crop)
        ll.addWidget(self.btn_crop)
        ll.addWidget(divider())

        # 抠图
        ll.addWidget(section_label("AI 抠图"))
        self.btn_remove_bg = make_btn("🪄  一键抠图", primary=True)
        self.btn_remove_bg.setEnabled(False)
        self.btn_remove_bg.clicked.connect(self._start_remove_bg)
        ll.addWidget(self.btn_remove_bg)
        self.rm_prog = QProgressBar()
        self.rm_prog.setRange(0, 0)
        self.rm_prog.setFixedHeight(4)
        self.rm_prog.setVisible(False)
        self.rm_prog.setStyleSheet(
            f"QProgressBar{{background:{C['border']};border:none;border-radius:2px;}}"
            f"QProgressBar::chunk{{background:{C['accent']};border-radius:2px;}}")
        ll.addWidget(self.rm_prog)
        self.rm_status = StatusLabel("上传照片后点击抠图")
        ll.addWidget(self.rm_status)
        ll.addWidget(divider())

        # 背景颜色
        ll.addWidget(section_label("背景颜色"))
        bg_colors = [
            ("白色", (255, 255, 255)), ("红色", (220, 35, 35)),
            ("蓝色", (67, 114, 196)), ("深蓝", (0, 51, 153)),
            ("浅蓝", (173, 216, 230)), ("灰色", (192, 192, 192)),
        ]
        bg_grid = QWidget()
        bg_gl = QHBoxLayout(bg_grid)
        bg_gl.setContentsMargins(0, 0, 0, 0)
        bg_gl.setSpacing(4)
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

        # 背景图
        bg_img_row = QHBoxLayout()
        bg_img_row.setSpacing(6)
        self.btn_bg_img = make_btn("🖼  选择背景图", small=True)
        self.btn_bg_img.clicked.connect(self._pick_bg_image)
        self.btn_bg_clear = make_btn("✕  清除背景图", small=True, danger=True)
        self.btn_bg_clear.setEnabled(False)
        self.btn_bg_clear.clicked.connect(self._clear_bg_image)
        bg_img_row.addWidget(self.btn_bg_img)
        bg_img_row.addWidget(self.btn_bg_clear)
        ll.addLayout(bg_img_row)
        self.bg_status = StatusLabel("当前：白色背景")
        ll.addWidget(self.bg_status)
        ll.addWidget(divider())
        # 排版模板
        ll.addWidget(section_label("排版模板"))
        # 模板名称 -> 副标题备注
        TMPL_INFO = {
            "一寸排版":      "3×3 · 9张 · 5寸竖版",
            "二寸排版":      "2×2 · 4张 · 5寸竖版",
            "小二寸排版":    "2×2 · 4张 · 5寸竖版",
            "三寸排版":      "1×2 · 2张 · 5寸竖版",
            "驾驶证排版":    "5×2 · 10张 · 5寸横版",
            "一寸+二寸排版": "9+4张 · 7寸横版",
            "结婚照排版":    "2×2 · 4张 · 5寸横版",
        }
        tmpls = list(TMPL_INFO.keys())
        self._btns = {}
        tmpl_grid = QWidget()
        tgl = QVBoxLayout(tmpl_grid)
        tgl.setContentsMargins(0, 0, 0, 0)
        tgl.setSpacing(4)
        row = None
        for i, name in enumerate(tmpls):
            if i % 2 == 0:
                row = QHBoxLayout()
                row.setSpacing(4)
                tgl.addLayout(row)
            # 卡片式按钮：主标题 + 副标题
            card = QWidget()
            card.setObjectName(f"tmpl_card_{i}")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(6, 6, 6, 6)
            card_layout.setSpacing(2)
            title_lbl = QLabel(name)
            title_lbl.setAlignment(Qt.AlignCenter)
            title_lbl.setStyleSheet(f"color:{C['text']};font-size:12px;font-weight:bold;background:transparent;border:none;")
            sub_lbl = QLabel(TMPL_INFO[name])
            sub_lbl.setAlignment(Qt.AlignCenter)
            sub_lbl.setStyleSheet(f"color:{C['text2']};font-size:10px;background:transparent;border:none;")
            card_layout.addWidget(title_lbl)
            card_layout.addWidget(sub_lbl)
            # 用 QPushButton 做可点击背景
            b = QPushButton()
            b.setCheckable(True)
            b.setFixedHeight(52)
            b.setStyleSheet(
                f"QPushButton{{background:{C['card']};border:1px solid {C['border']};border-radius:6px;}}"
                f"QPushButton:hover{{border-color:{C['text2']};}}"
                f"QPushButton:checked{{background:{C['accent']};border-color:{C['accent']};}}"
            )
            b.clicked.connect(lambda checked, n=name: self._on_tmpl(n))
            self._btns[name] = b
            # 将卡片叠加在按钮上（通过父子关系）
            overlay = QWidget(b)
            overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            ov_layout = QVBoxLayout(overlay)
            ov_layout.setContentsMargins(6, 6, 6, 6)
            ov_layout.setSpacing(2)
            t2 = QLabel(name)
            t2.setAlignment(Qt.AlignCenter)
            t2.setStyleSheet(f"color:{C['text']};font-size:12px;font-weight:bold;background:transparent;border:none;")
            s2 = QLabel(TMPL_INFO[name])
            s2.setAlignment(Qt.AlignCenter)
            s2.setStyleSheet(f"color:{C['text2']};font-size:10px;background:transparent;border:none;")
            ov_layout.addWidget(t2)
            ov_layout.addWidget(s2)
            # 选中时更新文字颜色
            def _update_labels(checked, btn=b, lbl_title=t2, lbl_sub=s2):
                if checked:
                    lbl_title.setStyleSheet(f"color:#fff;font-size:12px;font-weight:bold;background:transparent;border:none;")
                    lbl_sub.setStyleSheet(f"color:rgba(255,255,255,180);font-size:10px;background:transparent;border:none;")
                else:
                    lbl_title.setStyleSheet(f"color:{C['text']};font-size:12px;font-weight:bold;background:transparent;border:none;")
                    lbl_sub.setStyleSheet(f"color:{C['text2']};font-size:10px;background:transparent;border:none;")
            b.toggled.connect(_update_labels)
            b.resizeEvent = lambda e, ov=overlay: ov.setGeometry(0, 0, e.size().width(), e.size().height())
            row.addWidget(b)
        if len(tmpls) % 2 == 1:
            row.addStretch()
        ll.addWidget(tmpl_grid)
        self.ly_prog = QProgressBar()
        self.ly_prog.setRange(0, 0)
        self.ly_prog.setFixedHeight(4)
        self.ly_prog.setVisible(False)
        self.ly_prog.setStyleSheet(
            f"QProgressBar{{background:{C['border']};border:none;border-radius:2px;}}"
            f"QProgressBar::chunk{{background:{C['success']};border-radius:2px;}}")
        ll.addWidget(self.ly_prog)
        self.pinfo = StatusLabel("上传照片后选择排版模板")
        ll.addWidget(self.pinfo)
        ll.addStretch()
        hl.addWidget(panel)

        # ── 右侧预览区 ──
        preview_area = QWidget()
        preview_area.setStyleSheet(f"background:{C['bg']};")
        pl = QHBoxLayout(preview_area)
        pl.setContentsMargins(12, 12, 12, 12)
        pl.setSpacing(12)

        # 换背景预览列
        bg_vl = QVBoxLayout()
        bg_vl.setSpacing(6)
        bg_title = QLabel("换背景预览")
        bg_title.setStyleSheet(
            f"font-size:11px;font-weight:600;color:{C['text2']};letter-spacing:1px;")
        bg_vl.addWidget(bg_title)

        self.preview_bg = PaintablePreview("抠图后在此预览\n换背景效果")
        self.preview_bg.painted.connect(self._on_painted)
        bg_vl.addWidget(self.preview_bg, 1)

        # 画笔工具栏
        paint_bar = QWidget()
        paint_hl = QHBoxLayout(paint_bar)
        paint_hl.setContentsMargins(0, 0, 0, 0)
        paint_hl.setSpacing(6)

        self.btn_paint = QPushButton("✏  画笔")
        self.btn_paint.setCheckable(True)
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
        self.brush_slider.setRange(4, 80)
        self.brush_slider.setValue(20)
        self.brush_slider.setFixedWidth(90)
        self.brush_slider.valueChanged.connect(self._on_brush_size)
        paint_hl.addWidget(self.brush_slider)

        self.brush_size_lbl = QLabel("20px")
        self.brush_size_lbl.setStyleSheet(
            f"font-size:11px;color:{C['text2']};background:transparent;min-width:32px;")
        paint_hl.addWidget(self.brush_size_lbl)

        self.chk_feather = QCheckBox("羽化")
        self.chk_feather.setChecked(True)
        self.chk_feather.setStyleSheet(f"color:{C['text2']};font-size:11px;background:transparent;")
        self.chk_feather.toggled.connect(self._on_feather_toggle)
        paint_hl.addWidget(self.chk_feather)

        btn_clear_paint = make_btn("清除画笔", small=True, danger=True)
        btn_clear_paint.clicked.connect(self._on_clear_paint)
        paint_hl.addWidget(btn_clear_paint)
        paint_hl.addStretch()
        bg_vl.addWidget(paint_bar)

        # 换背景导出按钮
        bg_exp_row = QHBoxLayout()
        bg_exp_row.setSpacing(8)
        self.btn_save_jpg = make_btn("💾  保存换背景 JPG", primary=True)
        self.btn_save_jpg.setEnabled(False)
        self.btn_save_jpg.clicked.connect(self._export_composed)
        self.btn_save_png = make_btn("🔲  保存透明 PNG")
        self.btn_save_png.setEnabled(False)
        self.btn_save_png.clicked.connect(self._export_transparent)
        bg_exp_row.addWidget(self.btn_save_jpg)
        bg_exp_row.addWidget(self.btn_save_png)
        bg_vl.addLayout(bg_exp_row)
        self.pinfo_bg = StatusLabel("")
        bg_vl.addWidget(self.pinfo_bg)
        pl.addLayout(bg_vl, 1)

        # 排版预览列
        ly_vl = QVBoxLayout()
        ly_vl.setSpacing(6)
        ly_title = QLabel("排版预览")
        ly_title.setStyleSheet(
            f"font-size:11px;font-weight:600;color:{C['text2']};letter-spacing:1px;")
        ly_vl.addWidget(ly_title)
        self.preview_ly = PreviewLabel("选择排版模板后\n在此预览排版效果")
        ly_vl.addWidget(self.preview_ly, 1)
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
        self._src_img    = img
        self._fg_rgba    = None
        self._composed   = None
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
            self.rm_status.set_warn("请先上传照片")
            return
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
        # 重置画笔 mask（新图片）
        self.preview_bg.clear_paint()
        self.rm_prog.setVisible(False)
        self.rm_status.set_ok("抠图完成 ✓")
        self.btn_save_png.setEnabled(True)
        self._compose_and_show()

    def _on_rm_fail(self, msg):
        self.rm_prog.setVisible(False)
        self.rm_status.set_err(f"抠图失败：{msg.split(chr(10))[0]}")

    # ─── 合成背景并显示 ───
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

        # 同步到 PaintablePreview（会重新应用 paint_mask）
        self.preview_bg.show_img(composed)
        self.preview_bg.sync_img(composed)

        # 同步画笔颜色状态
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
        self.preview_bg.set_bg_color(None)
        self.preview_bg.set_bg_img_mode(True)
        self._compose_and_show()

    def _clear_bg_image(self):
        self._bg_image = None
        self._use_bg_img = False
        self.bg_status.set_info("当前：白色背景")
        self.btn_bg_clear.setEnabled(False)
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

    def _on_clear_paint(self):
        """清除画笔效果，重新从原始合成图显示"""
        self.preview_bg.clear_paint()
        if self._fg_rgba:
            self._compose_and_show()

    def _on_painted(self):
        """画笔松开时触发，同步 _composed 并防抖触发排版"""
        img = self.preview_bg.result()
        if img:
            self._composed = img
            self._paint_debounce.start()

    def _trigger_layout_after_paint(self):
        if self._cur_tmpl:
            self._on_tmpl(self._cur_tmpl)

    # ─── 排版 ───
    def _on_tmpl(self, name):
        if self._is_layouting: return
        for n, b in self._btns.items():
            b.setChecked(n == name)
        self._cur_tmpl = name
        src = self._composed if self._composed else self._src_img
        if src is None:
            self.pinfo.set_info("请先上传照片")
            return
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

    # ─── 关闭前清理 ───
    def cleanup(self):
        self._paint_debounce.stop()
        self._rm_worker = self._stop_worker(self._rm_worker)
        self._ly_worker = self._stop_worker(self._ly_worker)

    def is_busy(self) -> bool:
        return self._is_removing or self._is_layouting
