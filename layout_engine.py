"""
证件照排版引擎 v2.0
核心逻辑：尺寸换算 → 缩放 → 拼版 → 描边 → 导出
修复：
  - 照片间距极小（2px），紧密排列
  - 三寸排版：横向放置（照片旋转90°），1行×2列
  - 一寸+二寸混排：左侧9张一寸（3×3）+ 右侧4张二寸（2×2）
  - 驾驶证：5列×2行，紧密排列
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
CANVAS_5INCH = (1050, 1500)   # 3.5 × 5 英寸（竖版）
CANVAS_7INCH = (2100, 1500)   # 7 × 5 英寸（横版，用于混排）

# 证件照尺寸（厘米）→ 像素（宽×高）
PHOTO_SIZES = {
    "1inch":    (cm_to_px(2.5), cm_to_px(3.5)),   # 一寸：295×413
    "2inch":    (cm_to_px(3.5), cm_to_px(5.0)),   # 二寸：413×591
    "small2":   (cm_to_px(3.3), cm_to_px(4.5)),   # 小二寸：390×531
    "3inch":    (cm_to_px(9.0), cm_to_px(6.0)),   # 三寸横排：1063×709（宽×高，横向）
    "driver":   (cm_to_px(2.2), cm_to_px(3.3)),   # 驾驶证：260×390
}

# 照片间距（px）：极小间距，方便裁剪
PHOTO_GAP = 3   # 照片之间的间隙

# 描边参数
BORDER_COLOR = (80, 80, 80)   # 深灰
BORDER_WIDTH = 2              # px

# 排版模板定义（用于 UI 显示）
TEMPLATES = {
    "一寸排版":      "1inch_layout",
    "二寸排版":      "2inch_layout",
    "小二寸排版":    "small2_layout",
    "三寸排版":      "3inch_layout",
    "驾驶证排版":    "driver_layout",
    "一寸+二寸排版": "mixed_layout",
}

# 排版说明（UI 显示用）
TEMPLATE_DESC = {
    "一寸排版":      "3×3 共9张 · 5寸纸",
    "二寸排版":      "2×2 共4张 · 5寸纸",
    "小二寸排版":    "2×2 共4张 · 5寸纸",
    "三寸排版":      "横排 1×2 共2张 · 5寸纸",
    "驾驶证排版":    "5×2 共10张 · 5寸纸",
    "一寸+二寸排版": "一寸×9 + 二寸×4 · 7寸纸",
}

# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────

def auto_orient(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """
    自动旋转图片方向：
    若目标是竖版但图片是横版，则旋转 90°；反之亦然。
    """
    iw, ih = img.size
    target_is_landscape = target_w > target_h
    img_is_landscape = iw > ih
    if target_is_landscape != img_is_landscape:
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


def place_photos_tight(canvas: Image.Image, photo: Image.Image,
                       cols: int, rows: int,
                       photo_w: int, photo_h: int,
                       offset_x: int = 0, offset_y: int = 0,
                       gap: int = PHOTO_GAP) -> Image.Image:
    """
    将照片按 cols × rows 紧密排列到画布上。
    照片间距固定为 gap px，整体在画布中居中。
    """
    cw, ch = canvas.size

    # 计算整体排版块的总宽高
    block_w = cols * photo_w + (cols - 1) * gap
    block_h = rows * photo_h + (rows - 1) * gap

    # 在可用区域内居中
    avail_w = cw - offset_x
    avail_h = ch - offset_y
    start_x = offset_x + (avail_w - block_w) // 2
    start_y = offset_y + (avail_h - block_h) // 2

    # 确保不超出画布
    if start_x < offset_x:
        start_x = offset_x
    if start_y < offset_y:
        start_y = offset_y

    for row in range(rows):
        for col in range(cols):
            x = start_x + col * (photo_w + gap)
            y = start_y + row * (photo_h + gap)
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

    if template_name == "一寸+二寸排版":
        return _generate_mixed_layout(img)

    if template_name == "一寸排版":
        return _generate_standard(img, "1inch", 3, 3, CANVAS_5INCH)

    if template_name == "二寸排版":
        return _generate_standard(img, "2inch", 2, 2, CANVAS_5INCH)

    if template_name == "小二寸排版":
        return _generate_standard(img, "small2", 2, 2, CANVAS_5INCH)

    if template_name == "三寸排版":
        return _generate_3inch(img)

    if template_name == "驾驶证排版":
        return _generate_driver(img)

    raise ValueError(f"未处理的排版类型：{template_name}")


def _generate_standard(img: Image.Image, photo_key: str,
                        cols: int, rows: int,
                        canvas_size: tuple) -> Image.Image:
    """标准排版：指定尺寸、列数、行数。"""
    photo_w, photo_h = PHOTO_SIZES[photo_key]
    photo = resize_photo(img.copy(), photo_w, photo_h)
    canvas = create_canvas(canvas_size)
    canvas = place_photos_tight(canvas, photo, cols, rows, photo_w, photo_h)
    return canvas


def _generate_3inch(img: Image.Image) -> Image.Image:
    """
    三寸排版：
    - 三寸照片横向放置（宽9cm × 高6cm）
    - 5寸纸竖放（1050×1500），照片横向排列
    - 1列 × 2行，照片横向铺满
    """
    # 三寸横向：宽 = 9cm, 高 = 6cm
    photo_w = cm_to_px(9.0)   # 1063px
    photo_h = cm_to_px(6.0)   # 709px

    # 缩放照片：先自动处理方向，再缩放到三寸横向尺寸
    src = img.copy()
    # 如果原图是竖版，旋转为横版
    iw, ih = src.size
    if iw < ih:
        # 竖版照片 → 旋转90°变横版
        src = src.rotate(-90, expand=True)

    # 缩放到三寸横向尺寸
    src_w, src_h = src.size
    scale = max(photo_w / src_w, photo_h / src_h)
    new_w = round(src_w * scale)
    new_h = round(src_h * scale)
    src = src.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - photo_w) // 2
    top  = (new_h - photo_h) // 2
    photo = src.crop((left, top, left + photo_w, top + photo_h))

    # 5寸画布竖放：1050×1500
    canvas = create_canvas(CANVAS_5INCH)
    cw, ch = CANVAS_5INCH  # 1050 × 1500

    # 2张照片竖向排列（1列×2行），居中
    cols, rows = 1, 2
    gap = PHOTO_GAP
    block_w = photo_w
    block_h = rows * photo_h + (rows - 1) * gap

    start_x = (cw - block_w) // 2
    start_y = (ch - block_h) // 2

    for row in range(rows):
        x = start_x
        y = start_y + row * (photo_h + gap)
        p = photo.copy()
        p = add_border(p)
        canvas.paste(p, (x, y))

    return canvas


def _generate_driver(img: Image.Image) -> Image.Image:
    """
    驾驶证排版：5列 × 2行，共10张。
    照片按驾驶证原始宽高比（2.2:3.3 = 2:3）缩放，
    宽度铺满5寸纸（5列紧密排列），整体上下居中。
    """
    canvas_w, canvas_h = CANVAS_5INCH  # 1050 × 1500
    cols, rows = 5, 2
    gap = PHOTO_GAP

    # 按5列铺满画布宽度计算每张照片尺寸
    photo_w = (canvas_w - (cols - 1) * gap) // cols
    # 保持驾驶证宽高比 2.2:3.3
    orig_w = cm_to_px(2.2)
    orig_h = cm_to_px(3.3)
    photo_h = round(photo_w * orig_h / orig_w)

    photo = resize_photo(img.copy(), photo_w, photo_h)
    canvas = create_canvas(CANVAS_5INCH)

    # 整体上下居中
    block_h = rows * photo_h + (rows - 1) * gap
    start_y = (canvas_h - block_h) // 2
    start_x = 0  # 从左边缘开始，宽度铺满

    for row in range(rows):
        for col in range(cols):
            x = start_x + col * (photo_w + gap)
            y = start_y + row * (photo_h + gap)
            p = photo.copy()
            p = add_border(p)
            canvas.paste(p, (x, y))

    return canvas


def _generate_mixed_layout(img: Image.Image) -> Image.Image:
    """
    一寸 + 二寸混排（7×5 英寸画布 2100×1500）：
    左块：一寸 × 9（3列 × 3行）
    右块：二寸 × 4（2列 × 2行）
    两块整体在画布中居中，块间距极小。
    """
    canvas = create_canvas(CANVAS_7INCH)
    cw, ch = CANVAS_7INCH   # 2100 × 1500

    pw1, ph1 = PHOTO_SIZES["1inch"]
    pw2, ph2 = PHOTO_SIZES["2inch"]
    photo1 = resize_photo(img.copy(), pw1, ph1)
    photo2 = resize_photo(img.copy(), pw2, ph2)

    gap = PHOTO_GAP      # 照片之间的间距
    sep = 8              # 两块之间的分隔间距

    # 左块尺寸
    cols1, rows1 = 3, 3
    block1_w = cols1 * pw1 + (cols1 - 1) * gap
    block1_h = rows1 * ph1 + (rows1 - 1) * gap

    # 右块尺寸
    cols2, rows2 = 2, 2
    block2_w = cols2 * pw2 + (cols2 - 1) * gap
    block2_h = rows2 * ph2 + (rows2 - 1) * gap

    # 整体尺寸
    total_w = block1_w + sep + block2_w
    total_h = max(block1_h, block2_h)

    # 整体在画布中居中
    origin_x = (cw - total_w) // 2
    origin_y = (ch - total_h) // 2

    # ── 左块：一寸 9张，垂直居中 ──
    start_x1 = origin_x
    start_y1 = origin_y + (total_h - block1_h) // 2

    for row in range(rows1):
        for col in range(cols1):
            x = start_x1 + col * (pw1 + gap)
            y = start_y1 + row * (ph1 + gap)
            p = photo1.copy()
            p = add_border(p)
            canvas.paste(p, (x, y))

    # ── 右块：二寸 4张，垂直居中 ──
    start_x2 = origin_x + block1_w + sep
    start_y2 = origin_y + (total_h - block2_h) // 2

    for row in range(rows2):
        for col in range(cols2):
            x = start_x2 + col * (pw2 + gap)
            y = start_y2 + row * (ph2 + gap)
            p = photo2.copy()
            p = add_border(p)
            canvas.paste(p, (x, y))

    return canvas


def save_layout(canvas: Image.Image, output_path: str):
    """导出排版图片为 JPG，300 DPI。"""
    canvas.save(output_path, "JPEG", dpi=(DPI, DPI), quality=95)
