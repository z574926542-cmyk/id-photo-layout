"""
证件照排版引擎
核心逻辑：尺寸换算 → 缩放 → 拼版 → 描边 → 导出
"""

from PIL import Image, ImageDraw
import math

# ─────────────────────────────────────────────
# 常量定义
# ─────────────────────────────────────────────
DPI = 300
CM_PER_INCH = 2.54

def cm_to_px(cm: float) -> int:
    """厘米 → 像素（300 DPI）"""
    return round(cm * DPI / CM_PER_INCH)

# 画布尺寸（像素）
CANVAS_5INCH = (1050, 1500)   # 3.5 × 5 英寸
CANVAS_7INCH = (2100, 1500)   # 7 × 5 英寸

# 证件照尺寸（厘米）→ 像素
PHOTO_SIZES = {
    "1inch":    (cm_to_px(2.5), cm_to_px(3.5)),   # 一寸
    "2inch":    (cm_to_px(3.5), cm_to_px(5.0)),   # 二寸
    "small2":   (cm_to_px(3.3), cm_to_px(4.5)),   # 小二寸
    "3inch":    (cm_to_px(6.0), cm_to_px(9.0)),   # 三寸
    "driver":   (cm_to_px(2.2), cm_to_px(3.3)),   # 驾驶证
}

# 排版模板定义：(画布, 照片key, 列数, 行数)
TEMPLATES = {
    "一寸排版":      (CANVAS_5INCH, "1inch",  3, 3),
    "二寸排版":      (CANVAS_5INCH, "2inch",  2, 2),
    "小二寸排版":    (CANVAS_5INCH, "small2", 2, 2),
    "三寸排版":      (CANVAS_5INCH, "3inch",  1, 2),
    "驾驶证排版":    (CANVAS_5INCH, "driver", 5, 2),
    "一寸+二寸排版": None,   # 特殊混排，单独处理
}

# 描边参数
BORDER_COLOR = (80, 80, 80)   # 深灰
BORDER_WIDTH = 2              # px

# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────

def auto_orient(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """
    自动旋转图片方向：
    若目标是竖版但图片是横版，则旋转 90°；反之亦然。
    """
    iw, ih = img.size
    if (target_w < target_h) != (iw < ih):
        img = img.rotate(90, expand=True)
    return img


def resize_photo(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """
    将图片缩放并裁剪到精确的目标尺寸（保持比例，居中裁剪）。
    """
    img = auto_orient(img, target_w, target_h)
    iw, ih = img.size

    # 计算缩放比例（保证覆盖目标区域）
    scale = max(target_w / iw, target_h / ih)
    new_w = round(iw * scale)
    new_h = round(ih * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)

    # 居中裁剪
    left = (new_w - target_w) // 2
    top  = (new_h - target_h) // 2
    img = img.crop((left, top, left + target_w, top + target_h))
    return img


def add_border(img: Image.Image, border_w: int = BORDER_WIDTH,
               color: tuple = BORDER_COLOR) -> Image.Image:
    """在图片四周添加描边（直接绘制在图片边缘，不扩大尺寸）。"""
    draw = ImageDraw.Draw(img)
    w, h = img.size
    for i in range(border_w):
        draw.rectangle([i, i, w - 1 - i, h - 1 - i], outline=color)
    return img


def create_canvas(canvas_size: tuple, bg_color: tuple = (255, 255, 255)) -> Image.Image:
    """创建白色画布。"""
    return Image.new("RGB", canvas_size, bg_color)


def place_photos(canvas: Image.Image, photo: Image.Image,
                 cols: int, rows: int,
                 photo_w: int, photo_h: int,
                 offset_x: int = 0, offset_y: int = 0) -> Image.Image:
    """
    将照片按 cols × rows 均匀排列到画布上。
    照片间距自动计算（均匀分布）。
    """
    cw, ch = canvas.size

    # 计算可用区域（去掉偏移后的宽高）
    avail_w = cw - offset_x
    avail_h = ch - offset_y

    # 间距（照片之间的空白）
    gap_x = (avail_w - cols * photo_w) // (cols + 1)
    gap_y = (avail_h - rows * photo_h) // (rows + 1)

    # 若间距为负（照片太大），则强制紧密排列
    if gap_x < 0:
        gap_x = 0
    if gap_y < 0:
        gap_y = 0

    for row in range(rows):
        for col in range(cols):
            x = offset_x + gap_x + col * (photo_w + gap_x)
            y = offset_y + gap_y + row * (photo_h + gap_y)
            # 每张照片单独复制并加描边
            p = photo.copy()
            p = add_border(p)
            canvas.paste(p, (x, y))

    return canvas


# ─────────────────────────────────────────────
# 主排版函数
# ─────────────────────────────────────────────

def generate_layout(img: Image.Image, template_name: str) -> Image.Image:
    """
    根据模板名称生成排版图片。
    返回排版后的 PIL Image 对象。
    """
    if template_name not in TEMPLATES:
        raise ValueError(f"未知排版类型：{template_name}")

    # ── 混排特殊处理 ──
    if template_name == "一寸+二寸排版":
        return _generate_mixed_layout(img)

    canvas_size, photo_key, cols, rows = TEMPLATES[template_name]
    photo_w, photo_h = PHOTO_SIZES[photo_key]

    # 缩放照片
    photo = resize_photo(img.copy(), photo_w, photo_h)

    # 创建画布并排版
    canvas = create_canvas(canvas_size)
    canvas = place_photos(canvas, photo, cols, rows, photo_w, photo_h)

    return canvas


def _generate_mixed_layout(img: Image.Image) -> Image.Image:
    """
    一寸 + 二寸混排（7×5 英寸画布）：
    左侧：一寸 × 9（3列 × 3行）
    右侧：二寸 × 2（1列 × 2行）
    """
    canvas = create_canvas(CANVAS_7INCH)
    cw, ch = CANVAS_7INCH   # 2100 × 1500

    # ── 左侧：一寸 9张 ──
    pw1, ph1 = PHOTO_SIZES["1inch"]
    photo1 = resize_photo(img.copy(), pw1, ph1)

    left_w = cw // 2   # 1050px
    cols1, rows1 = 3, 3
    gap_x1 = (left_w - cols1 * pw1) // (cols1 + 1)
    gap_y1 = (ch - rows1 * ph1) // (rows1 + 1)
    if gap_x1 < 0: gap_x1 = 0
    if gap_y1 < 0: gap_y1 = 0

    for row in range(rows1):
        for col in range(cols1):
            x = gap_x1 + col * (pw1 + gap_x1)
            y = gap_y1 + row * (ph1 + gap_y1)
            p = photo1.copy()
            p = add_border(p)
            canvas.paste(p, (x, y))

    # ── 右侧：二寸 2张 ──
    pw2, ph2 = PHOTO_SIZES["2inch"]
    photo2 = resize_photo(img.copy(), pw2, ph2)

    right_w = cw - left_w   # 1050px
    cols2, rows2 = 1, 2
    gap_x2 = (right_w - cols2 * pw2) // (cols2 + 1)
    gap_y2 = (ch - rows2 * ph2) // (rows2 + 1)
    if gap_x2 < 0: gap_x2 = 0
    if gap_y2 < 0: gap_y2 = 0

    for row in range(rows2):
        x = left_w + gap_x2
        y = gap_y2 + row * (ph2 + gap_y2)
        p = photo2.copy()
        p = add_border(p)
        canvas.paste(p, (x, y))

    return canvas


def save_layout(canvas: Image.Image, output_path: str):
    """
    导出排版图片为 JPG，300 DPI。
    """
    canvas.save(output_path, "JPEG", dpi=(DPI, DPI), quality=95)
