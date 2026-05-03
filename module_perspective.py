"""
module_perspective.py — 证件照便捷工具 透视矫正模块
功能：四点定位透视矫正，实时预览，导出 JPG/PNG/PDF
"""
from __future__ import annotations
import traceback
from pathlib import Path

import numpy as np
from PIL import Image

from PyQt5.QtCore    import Qt, QPointF, QThread, pyqtSignal
from PyQt5.QtGui     import (QColor, QImage, QPainter, QPen, QPixmap,
                              QFont, QBrush)
from PyQt5.QtWidgets import (QWidget, QLabel, QVBoxLayout, QHBoxLayout,
                              QPushButton, QFileDialog, QMessageBox,
                              QComboBox, QSizePolicy, QSpinBox, QFrame,
                              QProgressBar)

from utils import (C, safe_load_image, pil_to_qpixmap, pil_rgba_to_qpixmap,
                   make_btn, section_label, divider, StatusLabel, PreviewLabel)

# ─────────────────────────────────────────────
# 预设尺寸模板（单位 mm）
# ─────────────────────────────────────────────
PRESETS = [
    ("身份证",   85.6,  54.0),
    ("护照",    125.0,  88.0),
    ("A4 纵向", 210.0, 297.0),
    ("A4 横向", 297.0, 210.0),
    ("户口本",  130.0, 185.0),
    ("名片",     90.0,  54.0),
    ("自定义",    0.0,   0.0),
]

# ─────────────────────────────────────────────
# 透视变换后台线程
# ─────────────────────────────────────────────
class PerspectiveWorker(QThread):
    done = pyqtSignal(object)   # PIL Image
    fail = pyqtSignal(str)

    def __init__(self, img: Image.Image, pts: list, out_w: int, out_h: int, parent=None):
        super().__init__(parent)
        self._img   = img
        self._pts   = pts       # [(x0,y0),(x1,y1),(x2,y2),(x3,y3)] 图像坐标
        self._out_w = out_w
        self._out_h = out_h

    def run(self):
        try:
            result = _perspective_warp(self._img, self._pts, self._out_w, self._out_h)
            self.done.emit(result)
        except Exception:
            self.fail.emit(traceback.format_exc())


def _perspective_warp(img: Image.Image, pts: list, out_w: int, out_h: int) -> Image.Image:
    """
    使用 numpy 实现透视变换（不依赖 OpenCV）。
    pts: [TL, TR, BR, BL] 顺序的图像坐标 (x, y)
    """
    try:
        import cv2
        src = np.array(pts, dtype=np.float32)
        dst = np.array([
            [0, 0], [out_w - 1, 0],
            [out_w - 1, out_h - 1], [0, out_h - 1]
        ], dtype=np.float32)
        M = cv2.getPerspectiveTransform(src, dst)
        arr = np.array(img.convert("RGB"))
        warped = cv2.warpPerspective(arr, M, (out_w, out_h),
                                     flags=cv2.INTER_LANCZOS4)
        return Image.fromarray(warped)
    except ImportError:
        # 纯 numpy 实现（不依赖 OpenCV）
        return _perspective_warp_numpy(img, pts, out_w, out_h)


def _perspective_warp_numpy(img: Image.Image, pts: list, out_w: int, out_h: int) -> Image.Image:
    """纯 numpy 透视变换（OpenCV 不可用时的备选方案）"""
    src = np.array(pts, dtype=np.float64)
    dst = np.array([
        [0, 0], [out_w - 1, 0],
        [out_w - 1, out_h - 1], [0, out_h - 1]
    ], dtype=np.float64)

    # 构建 8x8 线性方程组求解 3x3 单应矩阵
    A = []
    for (sx, sy), (dx, dy) in zip(src, dst):
        A.append([-sx, -sy, -1, 0, 0, 0, dx * sx, dx * sy, dx])
        A.append([0, 0, 0, -sx, -sy, -1, dy * sx, dy * sy, dy])
    A = np.array(A)
    _, _, V = np.linalg.svd(A)
    H = V[-1].reshape(3, 3)
    H = H / H[2, 2]

    # 逆变换（目标 → 源）
    H_inv = np.linalg.inv(H)

    arr = np.array(img.convert("RGB"))
    ih, iw = arr.shape[:2]

    # 生成目标像素坐标网格
    gy, gx = np.mgrid[0:out_h, 0:out_w]
    ones = np.ones_like(gx)
    coords = np.stack([gx, gy, ones], axis=-1).reshape(-1, 3).T  # 3 x N

    # 变换到源坐标
    src_coords = H_inv @ coords.astype(np.float64)
    src_x = (src_coords[0] / src_coords[2]).reshape(out_h, out_w)
    src_y = (src_coords[1] / src_coords[2]).reshape(out_h, out_w)

    # 双线性插值（最近邻简化版）
    src_xi = np.clip(np.round(src_x).astype(int), 0, iw - 1)
    src_yi = np.clip(np.round(src_y).astype(int), 0, ih - 1)
    out_arr = arr[src_yi, src_xi]

    return Image.fromarray(out_arr.astype(np.uint8))


# ─────────────────────────────────────────────
# 四点标注画布
# ─────────────────────────────────────────────
POINT_NAMES = ["左上角", "右上角", "右下角", "左下角"]
POINT_COLORS = [
    QColor(255, 80, 80),   # 红
    QColor(80, 200, 80),   # 绿
    QColor(80, 150, 255),  # 蓝
    QColor(255, 200, 50),  # 黄
]
HANDLE_R = 10   # 控制点半径（显示坐标）
DRAG_THRESHOLD = 18  # 拖动命中半径


class FourPointCanvas(QLabel):
    """
    四点定位画布：
    - 点击添加点（按 TL/TR/BR/BL 顺序）
    - 四点完成后可拖动微调
    - 发出 points_changed 信号触发实时预览
    """
    points_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pil: Image.Image | None = None
        self._pts: list[tuple[float, float]] = []   # 图像坐标
        self._drag_idx: int = -1
        self.setMinimumSize(400, 400)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet(f"background:{C['preview']};border:1px solid {C['border']};border-radius:8px;")
        self.setMouseTracking(True)

    def load_image(self, pil_img: Image.Image):
        self._pil = pil_img.convert("RGB")
        self._pts = []
        self._drag_idx = -1
        self.update()

    def reset_points(self):
        self._pts = []
        self._drag_idx = -1
        self.update()
        self.points_changed.emit()

    def undo_last(self):
        if self._pts:
            self._pts.pop()
            self.update()
            self.points_changed.emit()

    def get_points(self) -> list[tuple[float, float]]:
        return list(self._pts)

    def is_complete(self) -> bool:
        return len(self._pts) == 4

    def _scale_info(self):
        if not self._pil: return 1.0, 0.0, 0.0
        dw, dh = self.width(), self.height()
        iw, ih = self._pil.size
        if dw <= 0 or dh <= 0 or iw <= 0 or ih <= 0: return 1.0, 0.0, 0.0
        s = min(dw / iw, dh / ih)
        ox = (dw - iw * s) / 2
        oy = (dh - ih * s) / 2
        return s, ox, oy

    def _img2disp(self, ix, iy):
        s, ox, oy = self._scale_info()
        return ox + ix * s, oy + iy * s

    def _disp2img(self, dx, dy):
        s, ox, oy = self._scale_info()
        if s <= 0: return 0.0, 0.0
        iw, ih = self._pil.size
        return max(0.0, min(iw, (dx - ox) / s)), max(0.0, min(ih, (dy - oy) / s))

    def _find_near_point(self, dx, dy) -> int:
        for i, (ix, iy) in enumerate(self._pts):
            px, py = self._img2disp(ix, iy)
            if (dx - px) ** 2 + (dy - py) ** 2 <= DRAG_THRESHOLD ** 2:
                return i
        return -1

    def paintEvent(self, e):
        super().paintEvent(e)
        if not self._pil: return
        s, ox, oy = self._scale_info()
        if s <= 0: return

        t = self._pil.copy()
        dw, dh = self.width(), self.height()
        t.thumbnail((dw, dh), Image.LANCZOS)
        pm = pil_to_qpixmap(t)

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.drawPixmap(int(ox), int(oy), pm)

        # 连线（四点完成后画四边形）
        if len(self._pts) >= 2:
            pts_disp = [self._img2disp(ix, iy) for ix, iy in self._pts]
            pen = QPen(QColor(255, 255, 255, 180), 1.5, Qt.DashLine)
            p.setPen(pen)
            for i in range(len(pts_disp)):
                if i + 1 < len(pts_disp):
                    x0, y0 = pts_disp[i]
                    x1, y1 = pts_disp[i + 1]
                    p.drawLine(int(x0), int(y0), int(x1), int(y1))
            if len(self._pts) == 4:
                x0, y0 = pts_disp[3]
                x1, y1 = pts_disp[0]
                p.drawLine(int(x0), int(y0), int(x1), int(y1))

        # 控制点
        font = QFont("Arial", 9, QFont.Bold)
        p.setFont(font)
        for i, (ix, iy) in enumerate(self._pts):
            dx, dy = self._img2disp(ix, iy)
            color = POINT_COLORS[i]
            # 外圈
            p.setPen(QPen(QColor(0, 0, 0, 180), 2))
            p.setBrush(QBrush(color))
            p.drawEllipse(int(dx - HANDLE_R), int(dy - HANDLE_R),
                          HANDLE_R * 2, HANDLE_R * 2)
            # 编号
            p.setPen(QPen(QColor(0, 0, 0)))
            p.drawText(int(dx - 4), int(dy + 4), str(i + 1))
            # 名称标签
            p.setPen(QPen(color))
            p.drawText(int(dx + HANDLE_R + 4), int(dy + 4), POINT_NAMES[i])

        # 提示文字
        if not self._pts:
            p.setPen(QPen(QColor(255, 255, 255, 150)))
            p.setFont(QFont("Arial", 12))
            p.drawText(self.rect(), Qt.AlignCenter,
                       "请按顺序点击四个角点\n① 左上  ② 右上  ③ 右下  ④ 左下")
        elif len(self._pts) < 4:
            next_name = POINT_NAMES[len(self._pts)]
            p.setPen(QPen(POINT_COLORS[len(self._pts)]))
            p.setFont(QFont("Arial", 11))
            p.drawText(10, 24, f"请点击第 {len(self._pts)+1} 点：{next_name}")

        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            if not self._pil: return
            # 先检查是否命中已有点（拖动）
            idx = self._find_near_point(e.x(), e.y())
            if idx >= 0 and len(self._pts) == 4:
                self._drag_idx = idx
            elif len(self._pts) < 4:
                ix, iy = self._disp2img(e.x(), e.y())
                self._pts.append((ix, iy))
                self.update()
                self.points_changed.emit()

    def mouseMoveEvent(self, e):
        if self._drag_idx >= 0 and self._pil:
            ix, iy = self._disp2img(e.x(), e.y())
            self._pts[self._drag_idx] = (ix, iy)
            self.update()
            self.points_changed.emit()
        else:
            # 更新光标
            idx = self._find_near_point(e.x(), e.y())
            if idx >= 0 and len(self._pts) == 4:
                self.setCursor(Qt.SizeAllCursor)
            else:
                self.setCursor(Qt.CrossCursor if self._pil else Qt.ArrowCursor)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_idx = -1

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.update()


# ─────────────────────────────────────────────
# 透视矫正功能主面板
# ─────────────────────────────────────────────
class PerspectiveModule(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pil_src: Image.Image | None = None
        self._result:  Image.Image | None = None
        self._worker:  PerspectiveWorker | None = None
        self._is_working = False
        self._build()

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

        ll.addWidget(section_label("上传图片"))
        btn_upload = make_btn("📂  选择图片", primary=True)
        btn_upload.clicked.connect(self._on_upload)
        ll.addWidget(btn_upload)
        self.upload_status = StatusLabel("请上传需要透视矫正的图片")
        ll.addWidget(self.upload_status)
        ll.addWidget(divider())

        ll.addWidget(section_label("目标输出尺寸"))
        self.preset_combo = QComboBox()
        self.preset_combo.setStyleSheet(
            f"QComboBox{{background:{C['card']};color:{C['text']};border:1px solid {C['border']};"
            f"border-radius:6px;padding:4px 8px;font-size:12px;}}"
            f"QComboBox::drop-down{{border:none;}}"
            f"QComboBox QAbstractItemView{{background:{C['card']};color:{C['text']};"
            f"border:1px solid {C['border']};}}")
        for name, w, h in PRESETS:
            self.preset_combo.addItem(f"{name}  ({w}×{h} mm)" if w > 0 else name)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_change)
        ll.addWidget(self.preset_combo)

        # 自定义宽高
        custom_row = QHBoxLayout()
        custom_row.setSpacing(6)
        lbl_w = QLabel("宽(px):")
        lbl_w.setStyleSheet(f"font-size:11px;color:{C['text2']};background:transparent;")
        self.spin_w = QSpinBox()
        self.spin_w.setRange(10, 10000)
        self.spin_w.setValue(856)
        self.spin_w.setStyleSheet(
            f"QSpinBox{{background:{C['card']};color:{C['text']};border:1px solid {C['border']};"
            f"border-radius:4px;padding:2px 4px;font-size:11px;}}")
        lbl_h = QLabel("高(px):")
        lbl_h.setStyleSheet(f"font-size:11px;color:{C['text2']};background:transparent;")
        self.spin_h = QSpinBox()
        self.spin_h.setRange(10, 10000)
        self.spin_h.setValue(540)
        self.spin_h.setStyleSheet(self.spin_w.styleSheet())
        custom_row.addWidget(lbl_w); custom_row.addWidget(self.spin_w)
        custom_row.addWidget(lbl_h); custom_row.addWidget(self.spin_h)
        ll.addLayout(custom_row)
        self._custom_row_widget = custom_row
        self._set_custom_visible(False)
        ll.addWidget(divider())

        ll.addWidget(section_label("四点操作"))
        btn_undo = make_btn("↩  撤销上一点")
        btn_undo.clicked.connect(self._on_undo)
        ll.addWidget(btn_undo)
        btn_reset = make_btn("✕  清空重新定位", danger=True)
        btn_reset.clicked.connect(self._on_reset)
        ll.addWidget(btn_reset)
        self.pts_status = StatusLabel("点击图片上的四个角点开始")
        ll.addWidget(self.pts_status)
        ll.addWidget(divider())

        ll.addWidget(section_label("执行矫正"))
        self.btn_warp = make_btn("🔧  执行透视矫正", primary=True)
        self.btn_warp.setEnabled(False)
        self.btn_warp.clicked.connect(self._on_warp)
        ll.addWidget(self.btn_warp)
        self.warp_prog = QProgressBar()
        self.warp_prog.setRange(0, 0)
        self.warp_prog.setFixedHeight(4)
        self.warp_prog.setVisible(False)
        self.warp_prog.setStyleSheet(
            f"QProgressBar{{background:{C['border']};border:none;border-radius:2px;}}"
            f"QProgressBar::chunk{{background:{C['accent']};border-radius:2px;}}")
        ll.addWidget(self.warp_prog)
        self.warp_status = StatusLabel("")
        ll.addWidget(self.warp_status)
        ll.addWidget(divider())

        ll.addWidget(section_label("导出结果"))
        btn_exp_jpg = make_btn("💾  导出 JPG")
        btn_exp_jpg.clicked.connect(lambda: self._export("jpg"))
        ll.addWidget(btn_exp_jpg)
        btn_exp_png = make_btn("🔲  导出 PNG")
        btn_exp_png.clicked.connect(lambda: self._export("png"))
        ll.addWidget(btn_exp_png)
        btn_exp_pdf = make_btn("📄  导出 PDF")
        btn_exp_pdf.clicked.connect(lambda: self._export("pdf"))
        ll.addWidget(btn_exp_pdf)
        ll.addStretch()
        hl.addWidget(panel)

        # ── 右侧预览区 ──
        preview_area = QWidget()
        preview_area.setStyleSheet(f"background:{C['bg']};")
        pl = QHBoxLayout(preview_area)
        pl.setContentsMargins(12, 12, 12, 12)
        pl.setSpacing(12)

        # 左：原图 + 四点标注
        src_vl = QVBoxLayout()
        src_vl.setSpacing(6)
        src_title = QLabel("原图（点击标记四个角点）")
        src_title.setStyleSheet(
            f"font-size:11px;font-weight:600;color:{C['text2']};letter-spacing:1px;")
        src_vl.addWidget(src_title)
        self.canvas = FourPointCanvas()
        self.canvas.points_changed.connect(self._on_pts_changed)
        src_vl.addWidget(self.canvas, 1)
        pl.addLayout(src_vl, 1)

        # 右：矫正结果预览
        dst_vl = QVBoxLayout()
        dst_vl.setSpacing(6)
        dst_title = QLabel("矫正预览")
        dst_title.setStyleSheet(
            f"font-size:11px;font-weight:600;color:{C['text2']};letter-spacing:1px;")
        dst_vl.addWidget(dst_title)
        self.preview_result = PreviewLabel("执行矫正后\n在此预览结果")
        dst_vl.addWidget(self.preview_result, 1)
        pl.addLayout(dst_vl, 1)

        hl.addWidget(preview_area, 1)

    def _set_custom_visible(self, v: bool):
        for i in range(self._custom_row_widget.count()):
            w = self._custom_row_widget.itemAt(i).widget()
            if w: w.setVisible(v)

    def _on_preset_change(self, idx):
        name, pw, ph = PRESETS[idx]
        is_custom = (pw == 0 and ph == 0)
        self._set_custom_visible(is_custom)
        if not is_custom:
            # 以 300 DPI 换算像素（1 mm = 11.811 px @ 300DPI）
            dpi_factor = 300 / 25.4
            self.spin_w.setValue(int(pw * dpi_factor))
            self.spin_h.setValue(int(ph * dpi_factor))

    def _on_upload(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "",
            "图片 (*.jpg *.jpeg *.png *.bmp *.webp)")
        if not path: return
        try:
            img, was_resized, orig_size = safe_load_image(path)
        except ValueError as e:
            QMessageBox.warning(self, "图片加载失败", str(e))
            return
        self._pil_src = img
        self._result  = None
        self.canvas.load_image(img)
        self.preview_result.show_img(img)
        self.btn_warp.setEnabled(False)
        self.warp_status.set_info("")
        msg = f"已加载：{Path(path).name}  ({img.width}×{img.height}px)"
        if was_resized:
            ow, oh = orig_size
            msg += f"\n（原始 {ow}×{oh}，已自动优化）"
        self.upload_status.set_ok(msg)

    def _on_pts_changed(self):
        n = len(self.canvas.get_points())
        if n < 4:
            names = ["左上角", "右上角", "右下角", "左下角"]
            self.pts_status.set_info(f"已标记 {n}/4 点，下一个：{names[n]}")
            self.btn_warp.setEnabled(False)
        else:
            self.pts_status.set_ok("四点已完成 ✓  可拖动微调，或直接执行矫正")
            self.btn_warp.setEnabled(True)

    def _on_undo(self):
        self.canvas.undo_last()

    def _on_reset(self):
        self.canvas.reset_points()
        self.pts_status.set_info("点击图片上的四个角点开始")
        self.btn_warp.setEnabled(False)

    def _on_warp(self):
        if self._is_working: return
        pts = self.canvas.get_points()
        if len(pts) != 4:
            QMessageBox.warning(self, "提示", "请先完成四点标记")
            return
        out_w = self.spin_w.value()
        out_h = self.spin_h.value()
        self.warp_prog.setVisible(True)
        self.warp_status.set_info("透视矫正中...")
        self._is_working = True
        self.btn_warp.setEnabled(False)
        if self._worker and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(3000)
        self._worker = PerspectiveWorker(self._pil_src, pts, out_w, out_h, parent=self)
        self._worker.done.connect(self._on_warp_done)
        self._worker.fail.connect(self._on_warp_fail)
        self._worker.finished.connect(self._on_warp_finished)
        self._worker.start()

    def _on_warp_done(self, result: Image.Image):
        self._result = result
        self.preview_result.show_img(result)
        self.warp_status.set_ok(f"矫正完成 ✓  {result.width}×{result.height}px")

    def _on_warp_fail(self, msg: str):
        self.warp_status.set_err(f"矫正失败：{msg.split(chr(10))[0]}")

    def _on_warp_finished(self):
        self.warp_prog.setVisible(False)
        self._is_working = False
        self.btn_warp.setEnabled(True)

    def _export(self, fmt: str):
        if not self._result:
            QMessageBox.information(self, "提示", "请先执行透视矫正")
            return
        filter_map = {
            "jpg": "JPEG 图片 (*.jpg *.jpeg)",
            "png": "PNG 图片 (*.png)",
            "pdf": "PDF 文档 (*.pdf)",
        }
        default_map = {
            "jpg": "透视矫正结果.jpg",
            "png": "透视矫正结果.png",
            "pdf": "透视矫正结果.pdf",
        }
        path, _ = QFileDialog.getSaveFileName(
            self, f"导出 {fmt.upper()}", default_map[fmt], filter_map[fmt])
        if not path: return
        try:
            img = self._result.convert("RGB")
            if fmt == "jpg":
                img.save(path, "JPEG", quality=95, dpi=(300, 300))
            elif fmt == "png":
                img.save(path, "PNG", dpi=(300, 300))
            elif fmt == "pdf":
                img.save(path, "PDF", resolution=300)
            self.warp_status.set_ok(f"已导出：{Path(path).name}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def cleanup(self):
        if self._worker and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(3000)
