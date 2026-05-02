"""
证件照排版工具 v12.0
功能：AI抠图换背景 + 多规格排版 + 画笔修复 + PS风格裁剪框 + JPG导出
"""
from __future__ import annotations
import sys
from pathlib import Path
from typing import Optional, Tuple

from PyQt5.QtCore    import Qt, QThread, pyqtSignal, QPoint
from PyQt5.QtGui     import (QColor, QIcon, QPalette, QPixmap, QImage,
                              QPainter, QPen, QBrush, QCursor, QFont)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QHBoxLayout, QVBoxLayout, QSizePolicy,
    QFileDialog, QDialog, QDialogButtonBox, QMessageBox,
    QProgressBar, QSlider, QColorDialog, QFrame,
)
from PIL import Image

# ─────────────────────────────────────────────
# 延迟导入
# ─────────────────────────────────────────────
def generate_layout(img: Image.Image, name: str) -> Image.Image:
    from layout_engine import generate_layout as _gl
    return _gl(img, name)

def save_layout(img: Image.Image, path: str):
    from layout_engine import save_layout as _sl
    _sl(img, path)

# ─────────────────────────────────────────────
# 颜色主题
# ─────────────────────────────────────────────
C = {
    "bg":         "#0f0f1a",
    "panel":      "#13131f",
    "card":       "#1c1c35",
    "card_hover": "#22223d",
    "preview":    "#0a0a14",
    "border":     "#2a2a4a",
    "border_hi":  "#3d3d6b",
    "accent":     "#5b6cf9",
    "accent2":    "#8b5cf6",
    "text":       "#e8e8ff",
    "text2":      "#9090b8",
    "muted":      "#5a5a7a",
    "success":    "#34d399",
    "warning":    "#fbbf24",
}

# ─────────────────────────────────────────────
# PIL ↔ QPixmap
# ─────────────────────────────────────────────
def pil_to_qpixmap(img: Image.Image) -> QPixmap:
    if img.mode != "RGB": img = img.convert("RGB")
    data = img.tobytes("raw", "RGB")
    qi = QImage(data, img.width, img.height, img.width*3, QImage.Format_RGB888)
    return QPixmap.fromImage(qi)

def pil_rgba_to_qpixmap(img: Image.Image) -> QPixmap:
    if img.mode != "RGBA": img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qi = QImage(data, img.width, img.height, img.width*4, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qi)

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
    _IDLE = f"QLabel{{background:{C['card']};border:2px dashed {C['border_hi']};border-radius:10px;color:{C['text2']};font-size:12px;}}QLabel:hover{{background:{C['card_hover']};border-color:#818cf8;}}"
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
            p, _ = QFileDialog.getOpenFileName(self, "选择证件照", "", "图片 (*.jpg *.jpeg *.png *.bmp *.tiff *.webp)")
            if p: self._load(p)
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()
    def dropEvent(self, e):
        urls = e.mimeData().urls()
        if urls: self._load(urls[0].toLocalFile())
    def _load(self, path):
        try:
            img = Image.open(path).convert("RGB")
            self._pil = img; self._update_thumb(img)
            self.setStyleSheet(self._ACTIVE)
            self.setToolTip(f"{Path(path).name}  {img.width}x{img.height}px")
            self.loaded.emit(img)
        except Exception as ex:
            QMessageBox.warning(self, "加载失败", str(ex))
    def _update_thumb(self, img):
        t = img.copy(); t.thumbnail((self.width()-16 or 260, self.height()-16 or 90), Image.LANCZOS)
        self.setPixmap(pil_to_qpixmap(t))
    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._pil: self._update_thumb(self._pil)

# ─────────────────────────────────────────────
# 背景色按钮
# ─────────────────────────────────────────────
class BgColorBtn(QPushButton):
    selected = pyqtSignal(object)
    def __init__(self, color, label, is_custom=False):
        super().__init__(); self._color = color; self._label = label
        self._is_custom = is_custom; self._active = False
        self.setFixedSize(30, 30); self.setToolTip(label); self._refresh()
    def _refresh(self):
        r,g,b = self._color
        brd = f"3px solid {C['accent']}" if self._active else f"2px solid {C['border_hi']}"
        if self._is_custom:
            self.setStyleSheet(f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #ff6b6b,stop:0.33 #ffd93d,stop:0.66 #6bcb77,stop:1 #4d96ff);border:{brd};border-radius:15px;font-size:12px;color:white;}}")
        else:
            self.setStyleSheet(f"QPushButton{{background:rgb({r},{g},{b});border:{brd};border-radius:15px;}}")
    def set_active(self, v): self._active = v; self._refresh()
    def set_color(self, c): self._color = c; self._refresh()
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            if self._is_custom:
                qc = QColorDialog.getColor(QColor(*self._color), self, "选择背景颜色")
                if qc.isValid():
                    self._color = (qc.red(), qc.green(), qc.blue())
                    self._refresh(); self.selected.emit(self._color)
            else:
                self.selected.emit(self._color)

# ─────────────────────────────────────────────
# 排版模板按钮
# ─────────────────────────────────────────────
class LayoutBtn(QPushButton):
    def __init__(self, name, desc):
        super().__init__(); self._active = False
        lo = QVBoxLayout(self); lo.setContentsMargins(6,3,6,3); lo.setSpacing(0)
        self._n = QLabel(name); self._n.setStyleSheet(f"font-size:11px;font-weight:600;color:{C['text']};background:transparent;")
        self._d = QLabel(desc); self._d.setStyleSheet(f"font-size:9px;color:{C['text2']};background:transparent;")
        lo.addWidget(self._n); lo.addWidget(self._d)
        self.setFixedHeight(38); self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._refresh()
    def _refresh(self):
        if self._active:
            self.setStyleSheet(f"QPushButton{{background:{C['accent']};border:1px solid {C['accent']};border-radius:6px;}}QPushButton:hover{{background:#6b7cff;}}")
            self._n.setStyleSheet("font-size:11px;font-weight:600;color:#fff;background:transparent;")
            self._d.setStyleSheet("font-size:9px;color:rgba(255,255,255,0.75);background:transparent;")
        else:
            self.setStyleSheet(f"QPushButton{{background:{C['card']};border:1px solid {C['border']};border-radius:6px;}}QPushButton:hover{{background:{C['card_hover']};border-color:{C['border_hi']};}}")
            self._n.setStyleSheet(f"font-size:11px;font-weight:600;color:{C['text']};background:transparent;")
            self._d.setStyleSheet(f"font-size:9px;color:{C['text2']};background:transparent;")
    def activate(self, v): self._active = v; self._refresh()

# ─────────────────────────────────────────────
# 可绘制预览（换背景区）
# ─────────────────────────────────────────────
class PaintablePreview(QLabel):
    painted = pyqtSignal()
    def __init__(self, placeholder=""):
        super().__init__(); self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._img = None; self._placeholder = placeholder
        self._paint_mode = False; self._brush_size = 20
        self._bg_color = (255,255,255); self._use_transparent = False
        self._last_pos = None; self._idle()
    def _idle(self):
        self.setText(self._placeholder)
        self.setStyleSheet(f"QLabel{{background:{C['preview']};border:1px solid {C['border']};border-radius:12px;color:{C['muted']};font-size:13px;}}")
    def show_img(self, img):
        self._img = img.copy(); self._render()
        self.setStyleSheet(f"QLabel{{background:{C['preview']};border:1px solid {C['border']};border-radius:12px;}}")
    def _render(self):
        if not self._img: return
        w = max(self.width()-8, 100); h = max(self.height()-8, 100)
        t = self._img.copy(); t.thumbnail((w,h), Image.LANCZOS)
        self.setPixmap(pil_rgba_to_qpixmap(t) if self._img.mode=="RGBA" else pil_to_qpixmap(t))
    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._img: self._render()
    def set_paint_mode(self, v):
        self._paint_mode = v
        self.setCursor(QCursor(Qt.CrossCursor) if v else QCursor(Qt.ArrowCursor))
        if not v: self._last_pos = None
    def set_brush_size(self, s): self._brush_size = s
    def set_bg_color(self, c):
        self._bg_color = c; self._use_transparent = (c is None)
    def _img_pos(self, wp):
        if not self._img: return None
        px = self.pixmap()
        if not px: return None
        pw,ph = px.width(),px.height(); lw,lh = self.width(),self.height()
        ox=(lw-pw)//2; oy=(lh-ph)//2
        ix=wp.x()-ox; iy=wp.y()-oy
        if ix<0 or iy<0 or ix>=pw or iy>=ph: return None
        iw,ih = self._img.size
        return (max(0,min(int(ix*iw/pw),iw-1)), max(0,min(int(iy*ih/ph),ih-1)))
    def _draw_at(self, p1, p2=None):
        if not self._img: return
        from PIL import ImageDraw
        img = self._img.convert("RGBA")
        draw = ImageDraw.Draw(img)
        r = max(1, self._brush_size//2)
        fill = (0,0,0,0) if self._use_transparent else (*(self._bg_color or (255,255,255)), 255)
        def dc(cx,cy): draw.ellipse([cx-r,cy-r,cx+r,cy+r], fill=fill)
        if p2 is None:
            dc(*p1)
        else:
            x0,y0=p1; x1,y1=p2
            dist = max(abs(x1-x0),abs(y1-y0))
            steps = max(1, dist//max(1,r//2))
            for i in range(steps+1):
                t=i/steps; dc(int(x0+(x1-x0)*t), int(y0+(y1-y0)*t))
        self._img = img; self._render(); self.painted.emit()
    def mousePressEvent(self, e):
        if not self._paint_mode or e.button()!=Qt.LeftButton:
            super().mousePressEvent(e); return
        pos = self._img_pos(e.pos())
        if pos: self._last_pos=pos; self._draw_at(pos)
    def mouseMoveEvent(self, e):
        if not self._paint_mode or not (e.buttons()&Qt.LeftButton):
            super().mouseMoveEvent(e); return
        pos = self._img_pos(e.pos())
        if pos: self._draw_at(self._last_pos or pos, pos); self._last_pos=pos
    def mouseReleaseEvent(self, e):
        if e.button()==Qt.LeftButton: self._last_pos=None
        super().mouseReleaseEvent(e)
    def result(self): return self._img

# ─────────────────────────────────────────────
# 普通预览（排版区）
# ─────────────────────────────────────────────
class PreviewLabel(QLabel):
    def __init__(self, placeholder=""):
        super().__init__(); self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._img = None; self._placeholder = placeholder; self._idle()
    def _idle(self):
        self.setText(self._placeholder)
        self.setStyleSheet(f"QLabel{{background:{C['preview']};border:1px solid {C['border']};border-radius:12px;color:{C['muted']};font-size:13px;}}")
    def show_img(self, img):
        self._img = img.copy(); self._render()
        self.setStyleSheet(f"QLabel{{background:{C['preview']};border:1px solid {C['border']};border-radius:12px;}}")
    def _render(self):
        if not self._img: return
        w=max(self.width()-8,100); h=max(self.height()-8,100)
        t=self._img.copy(); t.thumbnail((w,h), Image.LANCZOS)
        self.setPixmap(pil_rgba_to_qpixmap(t) if self._img.mode=="RGBA" else pil_to_qpixmap(t))
    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._img: self._render()
    def result(self): return self._img

# ─────────────────────────────────────────────
# PS风格裁剪框
# ─────────────────────────────────────────────
HIT_NONE=0; HIT_MOVE=1; HIT_TL=2; HIT_TR=3; HIT_BL=4; HIT_BR=5
HIT_T=6; HIT_B=7; HIT_L=8; HIT_R=9

class CropCanvas(QLabel):
    HANDLE=8
    def __init__(self, pil_img):
        super().__init__(); self._pil=pil_img
        self._iw,self._ih=pil_img.size
        self._cx0=0.0; self._cy0=0.0; self._cx1=float(self._iw); self._cy1=float(self._ih)
        self._hit=HIT_NONE; self._drag_start=None; self._drag_box=None
        self.setMouseTracking(True); self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
        self.setMinimumSize(400,300)
    def reset(self):
        self._cx0=0.0; self._cy0=0.0; self._cx1=float(self._iw); self._cy1=float(self._ih); self.update()
    def _scale(self):
        lw,lh=self.width(),self.height(); iw,ih=self._iw,self._ih
        s=min(lw/iw,lh/ih); dw,dh=iw*s,ih*s
        return s,(lw-dw)/2,(lh-dh)/2
    def _to_w(self,ix,iy):
        s,ox,oy=self._scale(); return ox+ix*s,oy+iy*s
    def _to_i(self,wx,wy):
        s,ox,oy=self._scale(); return (wx-ox)/s,(wy-oy)/s
    def paintEvent(self,e):
        super().paintEvent(e)
        p=QPainter(self)
        s,ox,oy=self._scale()
        t=self._pil.copy(); t.thumbnail((int(self._iw*s)+2,int(self._ih*s)+2),Image.LANCZOS)
        p.drawPixmap(int(ox),int(oy),pil_to_qpixmap(t))
        x0,y0=self._to_w(self._cx0,self._cy0); x1,y1=self._to_w(self._cx1,self._cy1)
        p.fillRect(int(ox),int(oy),int(self._iw*s),int(self._ih*s),QColor(0,0,0,100))
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.fillRect(int(x0),int(y0),int(x1-x0),int(y1-y0),QColor(0,0,0,255))
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.setPen(QPen(QColor(255,255,255,220),1.5,Qt.SolidLine))
        p.drawRect(int(x0),int(y0),int(x1-x0),int(y1-y0))
        p.setPen(QPen(QColor(255,255,255,80),0.8,Qt.DashLine))
        for i in (1,2):
            xi=x0+(x1-x0)*i/3; yi=y0+(y1-y0)*i/3
            p.drawLine(int(xi),int(y0),int(xi),int(y1))
            p.drawLine(int(x0),int(yi),int(x1),int(yi))
        H=self.HANDLE
        handles=[(x0,y0),(x1-H,y0),(x0,y1-H),(x1-H,y1-H),
                 ((x0+x1)/2-H/2,y0),((x0+x1)/2-H/2,y1-H),
                 (x0,(y0+y1)/2-H/2),(x1-H,(y0+y1)/2-H/2)]
        p.setPen(QPen(QColor(255,255,255,200),1)); p.setBrush(QBrush(QColor(255,255,255,180)))
        for hx,hy in handles: p.drawRect(int(hx),int(hy),H,H)
        p.end()
    def _hit_test(self,mx,my):
        x0,y0=self._to_w(self._cx0,self._cy0); x1,y1=self._to_w(self._cx1,self._cy1)
        H=self.HANDLE+4
        def near(a,b): return abs(a-b)<H
        def inr(v,lo,hi): return lo-H<v<hi+H
        if near(mx,x0) and near(my,y0): return HIT_TL
        if near(mx,x1) and near(my,y0): return HIT_TR
        if near(mx,x0) and near(my,y1): return HIT_BL
        if near(mx,x1) and near(my,y1): return HIT_BR
        if near(my,y0) and inr(mx,x0,x1): return HIT_T
        if near(my,y1) and inr(mx,x0,x1): return HIT_B
        if near(mx,x0) and inr(my,y0,y1): return HIT_L
        if near(mx,x1) and inr(my,y0,y1): return HIT_R
        if x0<mx<x1 and y0<my<y1: return HIT_MOVE
        return HIT_NONE
    def _cursor_for_hit(self,hit):
        m={HIT_NONE:Qt.ArrowCursor,HIT_MOVE:Qt.SizeAllCursor,
           HIT_TL:Qt.SizeFDiagCursor,HIT_BR:Qt.SizeFDiagCursor,
           HIT_TR:Qt.SizeBDiagCursor,HIT_BL:Qt.SizeBDiagCursor,
           HIT_T:Qt.SizeVerCursor,HIT_B:Qt.SizeVerCursor,
           HIT_L:Qt.SizeHorCursor,HIT_R:Qt.SizeHorCursor}
        return QCursor(m.get(hit,Qt.ArrowCursor))
    def mouseMoveEvent(self,e):
        mx,my=e.pos().x(),e.pos().y()
        if self._hit==HIT_NONE:
            self.setCursor(self._cursor_for_hit(self._hit_test(mx,my))); return
        if not self._drag_start: return
        s,_,_=self._scale()
        dx=(mx-self._drag_start[0])/s; dy=(my-self._drag_start[1])/s
        cx0,cy0,cx1,cy1=self._drag_box
        iw,ih=float(self._iw),float(self._ih)
        if self._hit==HIT_MOVE:
            w,h=cx1-cx0,cy1-cy0; nx0=max(0.0,min(cx0+dx,iw-w)); ny0=max(0.0,min(cy0+dy,ih-h))
            self._cx0,self._cy0,self._cx1,self._cy1=nx0,ny0,nx0+w,ny0+h
        elif self._hit==HIT_TL: self._cx0=max(0.0,min(cx0+dx,cx1-20)); self._cy0=max(0.0,min(cy0+dy,cy1-20))
        elif self._hit==HIT_TR: self._cx1=min(iw,max(cx1+dx,cx0+20)); self._cy0=max(0.0,min(cy0+dy,cy1-20))
        elif self._hit==HIT_BL: self._cx0=max(0.0,min(cx0+dx,cx1-20)); self._cy1=min(ih,max(cy1+dy,cy0+20))
        elif self._hit==HIT_BR: self._cx1=min(iw,max(cx1+dx,cx0+20)); self._cy1=min(ih,max(cy1+dy,cy0+20))
        elif self._hit==HIT_T: self._cy0=max(0.0,min(cy0+dy,cy1-20))
        elif self._hit==HIT_B: self._cy1=min(ih,max(cy1+dy,cy0+20))
        elif self._hit==HIT_L: self._cx0=max(0.0,min(cx0+dx,cx1-20))
        elif self._hit==HIT_R: self._cx1=min(iw,max(cx1+dx,cx0+20))
        self.update()
    def mousePressEvent(self,e):
        if e.button()!=Qt.LeftButton: return
        mx,my=e.pos().x(),e.pos().y(); self._hit=self._hit_test(mx,my)
        if self._hit!=HIT_NONE:
            self._drag_start=(mx,my); self._drag_box=(self._cx0,self._cy0,self._cx1,self._cy1)
            self.setCursor(self._cursor_for_hit(self._hit))
    def mouseReleaseEvent(self,e):
        if e.button()==Qt.LeftButton:
            self._hit=HIT_NONE; self._drag_start=None; self._drag_box=None
            self.setCursor(self._cursor_for_hit(self._hit_test(e.pos().x(),e.pos().y())))
    def get_cropped(self):
        x0=int(max(0,self._cx0)); y0=int(max(0,self._cy0))
        x1=int(min(self._iw,self._cx1)); y1=int(min(self._ih,self._cy1))
        return self._pil.crop((x0,y0,x1,y1))

class CropDialog(QDialog):
    def __init__(self, pil_img, parent=None):
        super().__init__(parent); self.setWindowTitle("调整裁剪区域")
        self.setModal(True); self.setMinimumSize(620,540)
        self.setStyleSheet(f"QDialog{{background:{C['panel']};}}")
        lo=QVBoxLayout(self); lo.setContentsMargins(20,16,20,16); lo.setSpacing(10)
        tip=QLabel("拖动框内移动  ·  拖动四角等比缩放  ·  拖动四边自由拉伸")
        tip.setStyleSheet(f"font-size:11px;color:{C['text2']};"); lo.addWidget(tip)
        self.canvas=CropCanvas(pil_img); lo.addWidget(self.canvas,1)
        reset_btn=QPushButton("重置裁剪框"); reset_btn.setFixedHeight(34)
        reset_btn.setStyleSheet(f"QPushButton{{background:{C['card']};color:{C['text2']};border:1px solid {C['border']};border-radius:8px;min-width:100px;font-size:13px;}}QPushButton:hover{{background:{C['card_hover']};}}")
        reset_btn.clicked.connect(self.canvas.reset)
        btns=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        ok_btn=btns.button(QDialogButtonBox.Ok); ok_btn.setText("应用裁剪")
        cancel_btn=btns.button(QDialogButtonBox.Cancel); cancel_btn.setText("取消")
        for btn in [ok_btn,cancel_btn]: btn.setFixedHeight(34); btn.setMinimumWidth(90)
        ok_btn.setStyleSheet(f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {C['accent']},stop:1 {C['accent2']});color:#fff;border:none;border-radius:8px;font-size:13px;font-weight:600;}}")
        cancel_btn.setStyleSheet(f"QPushButton{{background:{C['card']};color:{C['text2']};border:1px solid {C['border']};border-radius:8px;font-size:13px;}}QPushButton:hover{{background:{C['card_hover']};}}")
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        btn_row=QHBoxLayout(); btn_row.addWidget(reset_btn); btn_row.addStretch(); btn_row.addWidget(btns)
        lo.addLayout(btn_row)
    def get_cropped(self): return self.canvas.get_cropped()

# ─────────────────────────────────────────────
# 后台线程
# ─────────────────────────────────────────────
class RemoveBgWorker(QThread):
    done=pyqtSignal(object); fail=pyqtSignal(str)
    def __init__(self,img): super().__init__(); self._img=img
    def run(self):
        try:
            from u2net_engine import remove_background
            self.done.emit(remove_background(self._img))
        except Exception as e: self.fail.emit(str(e))

class LayoutWorker(QThread):
    done=pyqtSignal(object,str); fail=pyqtSignal(str)
    def __init__(self,img,name): super().__init__(); self.img=img; self.name=name
    def run(self):
        try: self.done.emit(generate_layout(self.img,self.name),self.name)
        except Exception as e: self.fail.emit(str(e))

# ─────────────────────────────────────────────
# 主窗口
# ─────────────────────────────────────────────
class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("证件照排版工具")
        self.resize(1360,860); self.setMinimumSize(1100,700)
        _ico=Path(__file__).parent/"icon.ico"
        if not _ico.exists(): _ico=Path(__file__).parent/"icon.png"
        if _ico.exists(): self.setWindowIcon(QIcon(str(_ico)))
        self.setStyleSheet(f"QMainWindow,QWidget{{background:{C['bg']};color:{C['text']};font-family:'PingFang SC','Microsoft YaHei',Arial,sans-serif;}}")
        self._orig_img=None; self._src_img=None; self._fg_rgba=None
        self._composed=None; self._layout_img=None; self._cur_tmpl=None
        self._bg_color=(255,255,255); self._bg_image=None; self._use_bg_img=False
        self._rm_worker=None; self._ly_worker=None
        self._build()

    def _build(self):
        root=QWidget(); self.setCentralWidget(root)
        main_h=QHBoxLayout(root); main_h.setContentsMargins(0,0,0,0); main_h.setSpacing(0)

        # ══ 左侧控制面板（290px，无滚动）══
        left=QWidget(); left.setFixedWidth(290)
        left.setStyleSheet(f"background:{C['panel']};border-right:1px solid {C['border']};")
        ll=QVBoxLayout(left); ll.setContentsMargins(14,14,14,14); ll.setSpacing(7)

        title=QLabel("证件照排版工具")
        title.setStyleSheet(f"font-size:14px;font-weight:700;color:{C['text']};letter-spacing:0.5px;padding-bottom:2px;")
        ll.addWidget(title); ll.addWidget(divider())

        # STEP 1
        ll.addWidget(section_label("STEP 1  ·  上传照片"))
        self.upload=UploadZone(); self.upload.loaded.connect(self._on_upload); ll.addWidget(self.upload)
        crop_row=QHBoxLayout(); crop_row.setSpacing(6)
        self.btn_crop=make_btn("✂  调整裁剪",small=True); self.btn_crop.setEnabled(False)
        self.btn_crop.clicked.connect(self._open_crop); crop_row.addWidget(self.btn_crop); crop_row.addStretch()
        ll.addLayout(crop_row)
        self.info_lbl=StatusLabel("等待上传..."); ll.addWidget(self.info_lbl)
        self.rm_prog=QProgressBar(); self.rm_prog.setRange(0,0); self.rm_prog.setFixedHeight(3); self.rm_prog.setVisible(False)
        self.rm_prog.setStyleSheet(f"QProgressBar{{background:{C['border']};border:none;border-radius:2px;}}QProgressBar::chunk{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {C['accent']},stop:1 {C['accent2']});border-radius:2px;}}")
        ll.addWidget(self.rm_prog)
        self.rm_status=StatusLabel(""); ll.addWidget(self.rm_status)
        ll.addWidget(divider())

        # STEP 2
        ll.addWidget(section_label("STEP 2  ·  选择背景"))
        bg_colors=[((255,255,255),"白色"),((67,114,196),"蓝色"),((220,50,50),"红色"),((100,180,100),"绿色"),((240,240,240),"浅灰")]
        color_row=QHBoxLayout(); color_row.setSpacing(5)
        self._bg_btns=[]
        for color,label in bg_colors:
            btn=BgColorBtn(color,label); btn.selected.connect(self._on_bg_color)
            color_row.addWidget(btn); self._bg_btns.append(btn)
        self._custom_btn=BgColorBtn((200,200,200),"自定义颜色",is_custom=True)
        self._custom_btn.selected.connect(self._on_bg_color); color_row.addWidget(self._custom_btn); color_row.addStretch()
        ll.addLayout(color_row); self._bg_btns[0].set_active(True)
        bg_img_row=QHBoxLayout(); bg_img_row.setSpacing(6)
        self.btn_bg_img=make_btn("🖼  上传背景图",small=True); self.btn_bg_img.clicked.connect(self._pick_bg_image)
        self.btn_clear_bg=make_btn("× 清除",danger=True,small=True); self.btn_clear_bg.setEnabled(False); self.btn_clear_bg.clicked.connect(self._clear_bg_image)
        bg_img_row.addWidget(self.btn_bg_img); bg_img_row.addWidget(self.btn_clear_bg); bg_img_row.addStretch()
        ll.addLayout(bg_img_row)
        self.bg_status=StatusLabel("当前背景：白色"); self.bg_status.set_info("当前背景：白色"); ll.addWidget(self.bg_status)
        ll.addWidget(divider())

        # STEP 3
        ll.addWidget(section_label("STEP 3  ·  选择排版"))
        TEMPLATES=[("一寸排版","3×3·9张·5寸竖"),("二寸排版","2×2·4张·5寸竖"),
                   ("小二寸排版","2×2·4张·5寸竖"),("三寸排版","1×2·2张·5寸竖"),
                   ("驾驶证排版","5×2·10张·5寸横"),("一寸+二寸排版","9+4张·7寸横"),
                   ("结婚照排版","2×2·4张·5寸横")]
        self._btns={}
        for i in range(0,len(TEMPLATES),2):
            rw=QWidget(); rw.setStyleSheet("background:transparent;")
            rl=QHBoxLayout(rw); rl.setContentsMargins(0,0,0,0); rl.setSpacing(6)
            for j in range(2):
                if i+j<len(TEMPLATES):
                    n,d=TEMPLATES[i+j]; b=LayoutBtn(n,d)
                    b.clicked.connect(lambda _,name=n: self._on_tmpl(name))
                    self._btns[n]=b; rl.addWidget(b)
            ll.addWidget(rw)
        self.ly_prog=QProgressBar(); self.ly_prog.setRange(0,0); self.ly_prog.setFixedHeight(3); self.ly_prog.setVisible(False)
        self.ly_prog.setStyleSheet(f"QProgressBar{{background:{C['border']};border:none;border-radius:2px;}}QProgressBar::chunk{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {C['accent']},stop:1 {C['accent2']});border-radius:2px;}}")
        ll.addWidget(self.ly_prog)
        ll.addStretch()

        # ══ 右侧预览区（两栏）══
        right=QWidget(); right.setStyleSheet(f"background:{C['bg']};")
        right_h=QHBoxLayout(right); right_h.setContentsMargins(12,12,12,12); right_h.setSpacing(12)

        # ── 左栏：换背景预览 ──
        bg_col=QWidget(); bg_col.setStyleSheet("background:transparent;")
        bg_vl=QVBoxLayout(bg_col); bg_vl.setContentsMargins(0,0,0,0); bg_vl.setSpacing(7)
        bg_title=QLabel("换背景预览")
        bg_title.setStyleSheet(f"font-size:11px;font-weight:600;color:{C['text2']};letter-spacing:1px;")
        bg_vl.addWidget(bg_title)
        self.preview_bg=PaintablePreview("AI 抠图换背景\n\n上传照片后自动处理")
        self.preview_bg.painted.connect(self._on_painted); bg_vl.addWidget(self.preview_bg,1)

        # 画笔工具栏
        paint_bar=QWidget()
        paint_bar.setStyleSheet(f"background:{C['panel']};border:1px solid {C['border']};border-radius:8px;")
        paint_hl=QHBoxLayout(paint_bar); paint_hl.setContentsMargins(10,5,10,5); paint_hl.setSpacing(8)
        self.btn_paint=QPushButton("🖌  画笔"); self.btn_paint.setCheckable(True); self.btn_paint.setFixedHeight(26)
        self.btn_paint.setStyleSheet(f"QPushButton{{background:{C['card']};color:{C['text2']};border:1px solid {C['border']};border-radius:6px;font-size:11px;padding:0 8px;}}QPushButton:checked{{background:{C['accent']};color:#fff;border-color:{C['accent']};}}QPushButton:hover{{background:{C['card_hover']};}}")
        self.btn_paint.toggled.connect(self._on_paint_toggle); paint_hl.addWidget(self.btn_paint)
        brush_lbl=QLabel("大小:"); brush_lbl.setStyleSheet(f"font-size:11px;color:{C['text2']};background:transparent;"); paint_hl.addWidget(brush_lbl)
        self.brush_slider=QSlider(Qt.Horizontal); self.brush_slider.setRange(4,80); self.brush_slider.setValue(20); self.brush_slider.setFixedWidth(90)
        self.brush_slider.setStyleSheet(f"QSlider::groove:horizontal{{height:4px;background:{C['border']};border-radius:2px;}}QSlider::handle:horizontal{{width:12px;height:12px;margin:-4px 0;background:{C['accent']};border-radius:6px;}}QSlider::sub-page:horizontal{{background:{C['accent']};border-radius:2px;}}")
        self.brush_slider.valueChanged.connect(self._on_brush_size); paint_hl.addWidget(self.brush_slider)
        self.brush_size_lbl=QLabel("20px"); self.brush_size_lbl.setFixedWidth(30)
        self.brush_size_lbl.setStyleSheet(f"font-size:11px;color:{C['text2']};background:transparent;"); paint_hl.addWidget(self.brush_size_lbl)
        paint_hl.addStretch()
        paint_tip=QLabel("有背景色补色 · 透明模式擦除"); paint_tip.setStyleSheet(f"font-size:10px;color:{C['muted']};background:transparent;"); paint_hl.addWidget(paint_tip)
        bg_vl.addWidget(paint_bar)

        # 换背景导出按钮
        bg_exp_row=QHBoxLayout(); bg_exp_row.setSpacing(8)
        self.btn_save_jpg=make_btn("💾  保存换背景 JPG",primary=True); self.btn_save_jpg.setEnabled(False); self.btn_save_jpg.clicked.connect(self._export_composed)
        self.btn_save_png=make_btn("🔲  保存透明 PNG"); self.btn_save_png.setEnabled(False); self.btn_save_png.clicked.connect(self._export_transparent)
        bg_exp_row.addWidget(self.btn_save_jpg); bg_exp_row.addWidget(self.btn_save_png)
        bg_vl.addLayout(bg_exp_row)
        self.pinfo_bg=StatusLabel(""); bg_vl.addWidget(self.pinfo_bg)

        # ── 右栏：排版预览 ──
        ly_col=QWidget(); ly_col.setStyleSheet("background:transparent;")
        ly_vl=QVBoxLayout(ly_col); ly_vl.setContentsMargins(0,0,0,0); ly_vl.setSpacing(7)
        ly_title=QLabel("排版预览")
        ly_title.setStyleSheet(f"font-size:11px;font-weight:600;color:{C['text2']};letter-spacing:1px;")
        ly_vl.addWidget(ly_title)
        self.preview_layout=PreviewLabel("选择排版模板后\n自动生成排版图"); ly_vl.addWidget(self.preview_layout,1)
        self.btn_exp_layout=make_btn("📐  导出排版图  JPG 300DPI",primary=True); self.btn_exp_layout.setEnabled(False); self.btn_exp_layout.clicked.connect(self._export_layout)
        ly_vl.addWidget(self.btn_exp_layout)
        self.pinfo=StatusLabel(""); ly_vl.addWidget(self.pinfo)

        right_h.addWidget(bg_col,1); right_h.addWidget(ly_col,1)
        main_h.addWidget(left); main_h.addWidget(right,1)

    # ─── 工具 ───
    @staticmethod
    def _stop_worker(w):
        if w and w.isRunning(): w.quit(); w.wait(2000)
        return None

    # ─── 上传 ───
    def _on_upload(self,img):
        self._orig_img=img; self._src_img=img
        self.info_lbl.set_ok(f"已加载  {img.width}×{img.height} px")
        self.btn_crop.setEnabled(True); self._start_remove_bg()

    def _start_remove_bg(self):
        if not self._src_img: return
        self.rm_prog.setVisible(True); self.rm_status.set_info("AI 抠图中...")
        self._rm_worker=self._stop_worker(self._rm_worker)
        self._rm_worker=RemoveBgWorker(self._src_img)
        self._rm_worker.done.connect(self._on_rm_done)
        self._rm_worker.fail.connect(self._on_rm_fail)
        self._rm_worker.finished.connect(self._rm_worker.deleteLater)
        self._rm_worker.start()

    def _on_rm_done(self,rgba):
        self.rm_prog.setVisible(False); self._fg_rgba=rgba
        self.rm_status.set_ok("抠图完成 ✓"); self.btn_save_png.setEnabled(True)
        self._compose_and_show()

    def _on_rm_fail(self,msg):
        self.rm_prog.setVisible(False); self.rm_status.set_err(f"抠图失败：{msg}")

    # ─── 合成 ───
    def _compose_and_show(self):
        if not self._fg_rgba: return
        fg=self._fg_rgba
        if self._use_bg_img and self._bg_image:
            bg=self._bg_image.convert("RGBA").resize(fg.size,Image.LANCZOS)
        else:
            bg=Image.new("RGBA",fg.size,(*self._bg_color,255))
        composed=Image.alpha_composite(bg,fg)
        self._composed=composed; self.preview_bg.show_img(composed)
        self.preview_bg.set_bg_color((255,255,255) if self._use_bg_img else self._bg_color)
        self.btn_save_jpg.setEnabled(True)

    def _on_bg_color(self,color):
        for b in self._bg_btns: b.set_active(b._color==color and not b._is_custom)
        self._custom_btn.set_active(False)
        self._bg_color=color; self._use_bg_img=False; self._bg_image=None
        self.btn_clear_bg.setEnabled(False)
        names={(255,255,255):"白色",(67,114,196):"蓝色",(220,50,50):"红色",(100,180,100):"绿色",(240,240,240):"浅灰"}
        self.bg_status.set_info(f"当前背景：{names.get(color,'自定义颜色')}")
        self._compose_and_show()

    def _pick_bg_image(self):
        p,_=QFileDialog.getOpenFileName(self,"选择背景图片","","图片 (*.jpg *.jpeg *.png *.bmp *.webp)")
        if not p: return
        try:
            self._bg_image=Image.open(p).convert("RGBA"); self._use_bg_img=True
            self.btn_clear_bg.setEnabled(True)
            for b in self._bg_btns: b.set_active(False)
            self._custom_btn.set_active(False)
            self.bg_status.set_info(f"背景图：{Path(p).name}"); self._compose_and_show()
        except Exception as ex: QMessageBox.warning(self,"加载失败",str(ex))

    def _clear_bg_image(self):
        self._bg_image=None; self._use_bg_img=False; self.btn_clear_bg.setEnabled(False)
        self._bg_btns[0].set_active(True); self._bg_color=(255,255,255)
        self.bg_status.set_info("当前背景：白色"); self._compose_and_show()

    # ─── 裁剪 ───
    def _open_crop(self):
        if not self._orig_img: return
        dlg=CropDialog(self._orig_img,self)
        if dlg.exec_()==QDialog.Accepted:
            cropped=dlg.get_cropped(); self._src_img=cropped
            self.info_lbl.set_ok(f"已裁剪  {cropped.width}×{cropped.height} px")
            t=cropped.copy(); t.thumbnail((260,90),Image.LANCZOS)
            self.upload.setPixmap(pil_to_qpixmap(t))
            self._fg_rgba=None; self._start_remove_bg()

    # ─── 画笔 ───
    def _on_paint_toggle(self,checked):
        self.preview_bg.set_paint_mode(checked)
        self.btn_paint.setText("🖌  画笔 ON" if checked else "🖌  画笔")

    def _on_brush_size(self,val):
        self.preview_bg.set_brush_size(val); self.brush_size_lbl.setText(f"{val}px")

    def _on_painted(self):
        img=self.preview_bg.result()
        if img:
            self._composed=img
            if self._cur_tmpl: self._on_tmpl(self._cur_tmpl)

    # ─── 排版 ───
    def _on_tmpl(self,name):
        for n,b in self._btns.items(): b.activate(n==name)
        self._cur_tmpl=name
        src=self._composed if self._composed else self._src_img
        if src is None: self.pinfo.set_info("请先上传照片"); return
        self.ly_prog.setVisible(True); self.btn_exp_layout.setEnabled(False)
        self.pinfo.set_info("排版生成中...")
        self._ly_worker=self._stop_worker(self._ly_worker)
        self._ly_worker=LayoutWorker(src,name)
        self._ly_worker.done.connect(self._on_ly_done)
        self._ly_worker.fail.connect(self._on_ly_fail)
        self._ly_worker.finished.connect(self._ly_worker.deleteLater)
        self._ly_worker.start()

    def _on_ly_done(self,img,name):
        self._layout_img=img; self.ly_prog.setVisible(False)
        self.preview_layout.show_img(img); self.btn_exp_layout.setEnabled(True)
        self.pinfo.set_ok(f"{name}  ·  {img.width}×{img.height}px  ·  300 DPI")

    def _on_ly_fail(self,msg):
        self.ly_prog.setVisible(False); self.pinfo.set_err(f"排版失败：{msg}")

    # ─── 导出 ───
    def _export_layout(self):
        if not self._layout_img: return
        path,_=QFileDialog.getSaveFileName(self,"导出排版图片",f"{self._cur_tmpl or '排版'}.jpg","JPEG (*.jpg *.jpeg)")
        if path:
            if not path.lower().endswith(('.jpg','.jpeg')): path+='.jpg'
            try: save_layout(self._layout_img,path); self.pinfo.set_ok(f"已导出：{Path(path).name}")
            except Exception as e: QMessageBox.critical(self,"导出失败",str(e))

    def _export_composed(self):
        if not self._composed: return
        path,_=QFileDialog.getSaveFileName(self,"保存换背景图片","换背景.jpg","JPEG (*.jpg *.jpeg)")
        if path:
            if not path.lower().endswith(('.jpg','.jpeg')): path+='.jpg'
            try:
                self._composed.convert("RGB").save(path,"JPEG",quality=95,dpi=(300,300))
                self.pinfo_bg.set_ok(f"已保存：{Path(path).name}")
            except Exception as e: QMessageBox.critical(self,"保存失败",str(e))

    def _export_transparent(self):
        if not self._fg_rgba: return
        path,_=QFileDialog.getSaveFileName(self,"保存透明 PNG","透明抠图.png","PNG (*.png)")
        if path:
            if not path.lower().endswith('.png'): path+='.png'
            try: self._fg_rgba.save(path,"PNG"); self.pinfo_bg.set_ok(f"已保存：{Path(path).name}")
            except Exception as e: QMessageBox.critical(self,"保存失败",str(e))

    def closeEvent(self,event):
        self._rm_worker=self._stop_worker(self._rm_worker)
        self._ly_worker=self._stop_worker(self._ly_worker)
        event.accept()

# ─────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────
def main():
    app=QApplication(sys.argv)
    app.setApplicationName("证件照排版工具")
    app.setStyle("Fusion")
    _ip=Path(__file__).parent/"icon.ico"
    if not _ip.exists(): _ip=Path(__file__).parent/"icon.png"
    if _ip.exists(): app.setWindowIcon(QIcon(str(_ip)))
    pal=QPalette()
    pal.setColor(QPalette.Window,          QColor(C['bg']))
    pal.setColor(QPalette.WindowText,      QColor(C['text']))
    pal.setColor(QPalette.Base,            QColor(C['card']))
    pal.setColor(QPalette.Text,            QColor(C['text']))
    pal.setColor(QPalette.Button,          QColor(C['card']))
    pal.setColor(QPalette.ButtonText,      QColor(C['text']))
    pal.setColor(QPalette.Highlight,       QColor(C['accent']))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    app.setPalette(pal)
    w=App(); w.show()
    sys.exit(app.exec_())

if __name__=="__main__":
    main()
