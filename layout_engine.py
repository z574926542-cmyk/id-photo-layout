"""
证件照排版引擎 v3.0
核心逻辑：尺寸换算 → 缩放（等比不裁剪）→ 拼版 → 描边 → 导出

缩放规则：
  - 等比缩放到目标尺寸内（fit模式），不裁剪用户画面
  - 多余区域用白色填充，照片居中放置在目标格子内

驾驶证：
  - 画布：5寸横版（1500×1050 px，即5英寸宽×3.5英寸高）
  - 单张：2.2×3.2 cm
  - 排列：5列×2行，共10张，整体居中
"""

from PIL import Image, ImageDraw

# ─────────────────────────────────────────────
# 常量定义
# ─────────────────────────────────────────────
DPI = 300
CM_PER_INCH = 2.54

def cm_to_px(cm: float) -> int:
    """厘米 → 像素（300 DPI）"""
    return round(cm * DPI / CM_PER_INCH)

# 画布尺寸（像素）
CANVAS_5INCH_V = (1050, 1500)   # 3.5×5 英寸竖版（宽×高）
CANVAS_5INCH_H = (1500, 1050)   # 5×3.5 英寸横版（宽×高）—— 驾驶证用
CANVAS_7INCH   = (2100, 1500)   # 7×5 英寸横版（混排用）

# 证件照尺寸（厘米）→ 像素（宽×高）
PHOTO_SIZES = {
    "1inch":  (cm_to_px(2.5), cm_to_px(3.5)),   # 一寸：295×413
    "2inch":  (cm_to_px(3.5), cm_to_px(5.0)),   # 二寸：413×591
    "small2": (cm_to_px(3.3), cm_to_px(4.5)),   # 小二寸：390×531
    "3inch":  (cm_to_px(9.0), cm_to_px(6.0)),   # 三寸横排：1063×709
    "driver": (cm_to_px(2.2), cm_to_px(3.2)),   # 驾驶证：260×378
}

# 照片间距（px）
PHOTO_GAP = 3

# 描边参数
BORDER_COLOR = (80, 80, 80)
BORDER_WIDTH = 2

# 排版模板定义
TEMPLATES = {
    "一寸排版":      "1inch_layout",
    "二寸排版":      "2inch_layout",
    "小二寸排版":    "small2_layout",
    "三寸排版":      "3inch_layout",
    "驾驶证排版":    "driver_layout",
    "一寸+二寸排版": "mixed_layout",
}

TEMPLATE_DESC = {
    "一寸排版":      "3×3 共9张 · 5寸竖版",
    "二寸排版":      "2×2 共4张 · 5寸竖版",
    "小二寸排版":    "2×2 共4张 · 5寸竖版",
    "三寸排版":      "1×2 共2张 · 5寸竖版",
    "驾驶证排版":    "5×2 共10张 · 5寸横版",
    "一寸+二寸排版": "一寸×9 + 二寸×4 · 7寸横版",
}

# ─────────────────────────────────────────────
# 核心工具函数
# ─────────────────────────────────────────────

def fit_photo(img: Image.Image, target_w: int, target_h: int,
              bg_color: tuple = (255, 255, 255)) -> Image.Image:
    """
    等比缩放照片到目标尺寸（fit模式）：
    - 保持原始宽高比，不裁剪任何画面内容
    - 缩放后居中放置在目标尺寸的白色画布上
    - 多余区域用白色填充
    """
    iw, ih = img.size
    # 计算等比缩放比例（保证完整显示，不超出目标区域）
    scale = min(target_w / iw, target_h / ih)
    new_w = round(iw * scale)
    new_h = round(ih * scale)
    resized = img.resize((new_w, new_h), Image.LANCZOS)

    # 创建目标尺寸白色画布，将缩放后的图片居中粘贴
    canvas = Image.new("RGB", (target_w, target_h), bg_color)
    paste_x = (target_w - new_w) // 2
    paste_y = (target_h - new_h) // 2
    canvas.paste(resized, (paste_x, paste_y))
    return canvas


def add_border(img: Image.Image, border_w: int = BORDER_WIDTH,
               color: tuple = BORDER_COLOR) -> Image.Image:
    """在图片四周添加描边（绘制在图片边缘内侧，不扩大尺寸）。"""
    draw = ImageDraw.Draw(img)
    w, h = img.size
    for i in range(border_w):
        draw.rectangle([i, i, w - 1 - i, h - 1 - i], outline=color)
    return img


def create_canvas(canvas_size: tuple, bg_color: tuple = (255, 255, 255)) -> Image.Image:
    """创建白色画布。"""
    return Image.new("RGB", canvas_size, bg_color)


def place_grid(canvas: Image.Image, photo: Image.Image,
               cols: int, rows: int,
               photo_w: int, photo_h: int,
               gap: int = PHOTO_GAP,
               offset_x: int = 0, offset_y: int = 0,
               avail_w: int = None, avail_h: int = None) -> Image.Image:
    """
    将照片按 cols×rows 网格排列到画布的指定区域内，整体居中。
    offset_x/offset_y：可用区域起始坐标
    avail_w/avail_h：可用区域宽高（默认为画布全部）
    """
    cw, ch = canvas.size
    if avail_w is None:
        avail_w = cw - offset_x
    if avail_h is None:
        avail_h = ch - offset_y

    block_w = cols * photo_w + (cols - 1) * gap
    block_h = rows * photo_h + (rows - 1) * gap

    start_x = offset_x + max(0, (avail_w - block_w) // 2)
    start_y = offset_y + max(0, (avail_h - block_h) // 2)

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
    """根据模板名称生成排版图片，返回 PIL Image。"""
    if template_name not in TEMPLATES:
        raise ValueError(f"未知排版类型：{template_name}")

    if template_name == "一寸排版":
        return _layout_standard(img, "1inch", 3, 3, CANVAS_5INCH_V)

    if template_name == "二寸排版":
        return _layout_standard(img, "2inch", 2, 2, CANVAS_5INCH_V)

    if template_name == "小二寸排版":
        return _layout_standard(img, "small2", 2, 2, CANVAS_5INCH_V)

    if template_name == "三寸排版":
        return _layout_3inch(img)

    if template_name == "驾驶证排版":
        return _layout_driver(img)

    if template_name == "一寸+二寸排版":
        return _layout_mixed(img)

    raise ValueError(f"未处理的排版类型：{template_name}")


def _layout_standard(img: Image.Image, photo_key: str,
                     cols: int, rows: int,
                     canvas_size: tuple) -> Image.Image:
    """标准排版：等比缩放（不裁剪），按网格排列。"""
    photo_w, photo_h = PHOTO_SIZES[photo_key]
    photo = fit_photo(img.copy(), photo_w, photo_h)
    canvas = create_canvas(canvas_size)
    place_grid(canvas, photo, cols, rows, photo_w, photo_h)
    return canvas


def _layout_3inch(img: Image.Image) -> Image.Image:
    """
    三寸排版：
    - 三寸照片横向（宽9cm×高6cm）
    - 5寸竖版画布（1050×1500），1列×2行
    - 等比缩放，不裁剪
    """
    photo_w = cm_to_px(9.0)   # 1063px
    photo_h = cm_to_px(6.0)   # 709px

    # 如果原图是竖版，旋转为横版（三寸是横向照片）
    src = img.copy()
    iw, ih = src.size
    if ih > iw:
        src = src.rotate(-90, expand=True)

    photo = fit_photo(src, photo_w, photo_h)
    canvas = create_canvas(CANVAS_5INCH_V)
    cw, ch = CANVAS_5INCH_V

    gap = PHOTO_GAP
    rows = 2
    block_h = rows * photo_h + (rows - 1) * gap
    start_x = (cw - photo_w) // 2
    start_y = (ch - block_h) // 2

    for row in range(rows):
        x = start_x
        y = start_y + row * (photo_h + gap)
        p = photo.copy()
        p = add_border(p)
        canvas.paste(p, (x, y))

    return canvas


def _layout_driver(img: Image.Image) -> Image.Image:
    """
    驾驶证排版：
    - 画布：5寸横版（1500×1050 px，5英寸宽×3.5英寸高）
    - 单张：2.2×3.2 cm（260×378 px）
    - 排列：5列×2行，共10张，整体居中
    - 等比缩放，不裁剪
    """
    photo_w, photo_h = PHOTO_SIZES["driver"]   # 260×378
    photo = fit_photo(img.copy(), photo_w, photo_h)
    canvas = create_canvas(CANVAS_5INCH_H)     # 1500×1050 横版
    place_grid(canvas, photo, 5, 2, photo_w, photo_h)
    return canvas


def _layout_mixed(img: Image.Image) -> Image.Image:
    """
    一寸+二寸混排（7×5英寸画布 2100×1500）：
    左块：一寸×9（3列×3行）
    右块：二寸×4（2列×2行）
    两块整体在画布中居中，块间距8px。
    等比缩放，不裁剪。
    """
    canvas = create_canvas(CANVAS_7INCH)
    cw, ch = CANVAS_7INCH

    pw1, ph1 = PHOTO_SIZES["1inch"]
    pw2, ph2 = PHOTO_SIZES["2inch"]
    photo1 = fit_photo(img.copy(), pw1, ph1)
    photo2 = fit_photo(img.copy(), pw2, ph2)

    gap = PHOTO_GAP
    sep = 8   # 两块之间的间距

    # 左块
    cols1, rows1 = 3, 3
    block1_w = cols1 * pw1 + (cols1 - 1) * gap
    block1_h = rows1 * ph1 + (rows1 - 1) * gap

    # 右块
    cols2, rows2 = 2, 2
    block2_w = cols2 * pw2 + (cols2 - 1) * gap
    block2_h = rows2 * ph2 + (rows2 - 1) * gap

    # 整体居中
    total_w = block1_w + sep + block2_w
    total_h = max(block1_h, block2_h)
    origin_x = (cw - total_w) // 2
    origin_y = (ch - total_h) // 2

    # 左块垂直居中
    start_x1 = origin_x
    start_y1 = origin_y + (total_h - block1_h) // 2
    for row in range(rows1):
        for col in range(cols1):
            x = start_x1 + col * (pw1 + gap)
            y = start_y1 + row * (ph1 + gap)
            p = photo1.copy()
            p = add_border(p)
            canvas.paste(p, (x, y))

    # 右块垂直居中
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
