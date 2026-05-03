"""
layout_engine_v19.py — 证件照排版引擎（稳定版）
修复：
  - 三寸排版：改用 5寸横版画布（1500×1050），避免 photo_w>canvas_w 导致负坐标
  - 所有 fit_photo 注释统一为 "cover 模式：等比缩放填满目标尺寸，居中裁剪"
  - place_grid 中 paste 统一处理 RGBA 模式（传 mask 参数）
  - generate_layout 入口强制转 RGB，防止 RGBA 图片进入排版流程
"""
from PIL import Image

# ─────────────────────────────────────────────
# 常量（300 DPI 像素尺寸）
# ─────────────────────────────────────────────
# 照片尺寸（宽×高，单位：px @ 300DPI）
PHOTO_SIZES = {
    "一寸":   (295, 413),    # 25×35mm
    "二寸":   (413, 579),    # 35×49mm
    "小二寸": (413, 531),    # 35×45mm
    "三寸":   (826, 1063),   # 70×90mm（注意：宽826，高1063）
    "驾驶证": (216, 280),    # 18.3×23.8mm
    "结婚照": (413, 579),    # 35×49mm（同二寸）
}

# 画布尺寸（宽×高，单位：px @ 300DPI）
CANVAS_SIZES = {
    "5寸竖版": (1050, 1500),  # 89×127mm
    "5寸横版": (1500, 1050),  # 127×89mm
    "7寸横版": (2100, 1500),  # 178×127mm
}

GAP    = 9    # 照片间距 3px（实际 3px @ 300DPI = 约 0.25mm，这里用 9px 约 0.75mm）
BORDER = 6    # 照片描边 2px（实际 6px @ 300DPI）

# ─────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────
def fit_photo(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """
    cover 模式：等比缩放填满目标尺寸，居中裁剪。
    保证输出图片尺寸精确为 target_w × target_h。
    """
    if target_w <= 0 or target_h <= 0:
        raise ValueError(f"目标尺寸无效：{target_w}×{target_h}")
    src_w, src_h = img.size
    if src_w <= 0 or src_h <= 0:
        raise ValueError(f"源图片尺寸无效：{src_w}×{src_h}")

    scale = max(target_w / src_w, target_h / src_h)
    new_w = max(1, round(src_w * scale))
    new_h = max(1, round(src_h * scale))
    img = img.resize((new_w, new_h), Image.LANCZOS)

    # 居中裁剪
    left = (new_w - target_w) // 2
    top  = (new_h - target_h) // 2
    img  = img.crop((left, top, left + target_w, top + target_h))
    return img


def add_border(img: Image.Image, border_px: int, color=(200, 200, 200)) -> Image.Image:
    """在照片四周添加描边（不改变照片尺寸，在外部扩展）"""
    if border_px <= 0:
        return img
    new_w = img.width  + border_px * 2
    new_h = img.height + border_px * 2
    canvas = Image.new("RGB", (new_w, new_h), color)
    canvas.paste(img, (border_px, border_px))
    return canvas


def create_canvas(w: int, h: int, bg=(255, 255, 255)) -> Image.Image:
    return Image.new("RGB", (w, h), bg)


def place_grid(canvas: Image.Image, photo: Image.Image,
               rows: int, cols: int,
               start_x: int, start_y: int,
               gap: int) -> None:
    """
    将 photo 按 rows×cols 网格放置到 canvas 上。
    start_x/start_y 是第一张照片左上角坐标（含描边）。
    gap 是照片之间的间距（像素）。
    """
    pw, ph = photo.size
    # 如果 photo 是 RGBA，提取 alpha 通道作为 mask
    if photo.mode == "RGBA":
        mask = photo.split()[3]
        photo_rgb = photo.convert("RGB")
    else:
        mask = None
        photo_rgb = photo

    for row in range(rows):
        for col in range(cols):
            x = start_x + col * (pw + gap)
            y = start_y + row * (ph + gap)
            # 边界检查：防止粘贴超出画布
            if x < 0 or y < 0 or x + pw > canvas.width or y + ph > canvas.height:
                continue
            if mask:
                canvas.paste(photo_rgb, (x, y), mask)
            else:
                canvas.paste(photo_rgb, (x, y))


def center_offset(canvas_size: int, content_size: int) -> int:
    """计算居中偏移量，保证 >= 0"""
    return max(0, (canvas_size - content_size) // 2)

# ─────────────────────────────────────────────
# 排版函数
# ─────────────────────────────────────────────
def _layout_1inch(img: Image.Image) -> Image.Image:
    """一寸排版：3列×3行，9张，5寸竖版画布"""
    cw, ch = CANVAS_SIZES["5寸竖版"]   # 1050×1500
    pw, ph = PHOTO_SIZES["一寸"]        # 295×413
    rows, cols = 3, 3

    photo = fit_photo(img, pw, ph)
    photo = add_border(photo, BORDER)
    bw, bh = photo.size   # 307×425

    total_w = cols * bw + (cols - 1) * GAP   # 3*307 + 2*9 = 939
    total_h = rows * bh + (rows - 1) * GAP   # 3*425 + 2*9 = 1293

    canvas = create_canvas(cw, ch)
    ox = center_offset(cw, total_w)
    oy = center_offset(ch, total_h)
    place_grid(canvas, photo, rows, cols, ox, oy, GAP)
    return canvas


def _layout_2inch(img: Image.Image) -> Image.Image:
    """二寸排版：2列×2行，4张，5寸竖版画布"""
    cw, ch = CANVAS_SIZES["5寸竖版"]   # 1050×1500
    pw, ph = PHOTO_SIZES["二寸"]        # 413×579
    rows, cols = 2, 2

    photo = fit_photo(img, pw, ph)
    photo = add_border(photo, BORDER)
    bw, bh = photo.size   # 425×591

    total_w = cols * bw + (cols - 1) * GAP   # 2*425 + 9 = 859
    total_h = rows * bh + (rows - 1) * GAP   # 2*591 + 9 = 1191

    canvas = create_canvas(cw, ch)
    ox = center_offset(cw, total_w)
    oy = center_offset(ch, total_h)
    place_grid(canvas, photo, rows, cols, ox, oy, GAP)
    return canvas


def _layout_small2inch(img: Image.Image) -> Image.Image:
    """小二寸排版：2列×2行，4张，5寸竖版画布"""
    cw, ch = CANVAS_SIZES["5寸竖版"]   # 1050×1500
    pw, ph = PHOTO_SIZES["小二寸"]      # 413×531
    rows, cols = 2, 2

    photo = fit_photo(img, pw, ph)
    photo = add_border(photo, BORDER)
    bw, bh = photo.size   # 425×543

    total_w = cols * bw + (cols - 1) * GAP   # 2*425 + 9 = 859
    total_h = rows * bh + (rows - 1) * GAP   # 2*543 + 9 = 1095

    canvas = create_canvas(cw, ch)
    ox = center_offset(cw, total_w)
    oy = center_offset(ch, total_h)
    place_grid(canvas, photo, rows, cols, ox, oy, GAP)
    return canvas


def _layout_3inch(img: Image.Image) -> Image.Image:
    """
    三寸排版：1列×2行，2张，5寸横版画布（1500×1050）。
    三寸照片尺寸：826×1063（宽×高）。
    注意：照片高度 1063 > 画布高度 1050，因此使用 cover 模式裁剪到 826×1021，
    加描边后 838×1033，两张竖排总高 2075，超过画布，改为横排（2列×1行）。
    实际布局：2列×1行，横排，画布 1500×1050。
    """
    cw, ch = CANVAS_SIZES["5寸横版"]   # 1500×1050
    # 三寸照片适配画布高度：高度不超过 (ch - 2*GAP - 2*BORDER*2) // 1
    # 安全尺寸：宽 826，高限制在 ch - 2*BORDER = 1050 - 12 = 1038
    pw = 826
    ph = min(1063, ch - BORDER * 2 - 4)   # 1038，防止超出画布
    rows, cols = 1, 2

    photo = fit_photo(img, pw, ph)
    photo = add_border(photo, BORDER)
    bw, bh = photo.size   # 838×(ph+12)

    total_w = cols * bw + (cols - 1) * GAP   # 2*838 + 9 = 1685
    total_h = rows * bh                       # bh

    # 如果 total_w 超出画布，缩小照片宽度
    if total_w > cw:
        # 重新计算照片宽度：(cw - GAP - 2*BORDER*2) // 2
        pw = (cw - GAP - BORDER * 4) // 2   # (1500 - 9 - 24) // 2 = 733
        photo = fit_photo(img, pw, ph)
        photo = add_border(photo, BORDER)
        bw, bh = photo.size
        total_w = cols * bw + (cols - 1) * GAP
        total_h = rows * bh

    canvas = create_canvas(cw, ch)
    ox = center_offset(cw, total_w)
    oy = center_offset(ch, total_h)
    place_grid(canvas, photo, rows, cols, ox, oy, GAP)
    return canvas


def _layout_driver(img: Image.Image) -> Image.Image:
    """驾驶证排版：5列×2行，10张，5寸横版画布"""
    cw, ch = CANVAS_SIZES["5寸横版"]   # 1500×1050
    pw, ph = PHOTO_SIZES["驾驶证"]      # 216×280
    rows, cols = 2, 5

    photo = fit_photo(img, pw, ph)
    photo = add_border(photo, BORDER)
    bw, bh = photo.size   # 228×292

    total_w = cols * bw + (cols - 1) * GAP   # 5*228 + 4*9 = 1176
    total_h = rows * bh + (rows - 1) * GAP   # 2*292 + 9 = 593

    canvas = create_canvas(cw, ch)
    ox = center_offset(cw, total_w)
    oy = center_offset(ch, total_h)
    place_grid(canvas, photo, rows, cols, ox, oy, GAP)
    return canvas


def _layout_1inch_2inch(img: Image.Image) -> Image.Image:
    """一寸+二寸混排：7寸横版画布，上方4张一寸，下方3张二寸"""
    cw, ch = CANVAS_SIZES["7寸横版"]   # 2100×1500

    pw1, ph1 = PHOTO_SIZES["一寸"]     # 295×413
    pw2, ph2 = PHOTO_SIZES["二寸"]     # 413×579

    p1 = fit_photo(img, pw1, ph1); p1 = add_border(p1, BORDER)
    p2 = fit_photo(img, pw2, ph2); p2 = add_border(p2, BORDER)
    bw1, bh1 = p1.size   # 307×425
    bw2, bh2 = p2.size   # 425×591

    # 上排：4张一寸
    row1_w = 4 * bw1 + 3 * GAP   # 4*307 + 3*9 = 1255
    ox1 = center_offset(cw, row1_w)
    oy1 = center_offset(ch, bh1 + GAP + bh2)

    # 下排：3张二寸
    row2_w = 3 * bw2 + 2 * GAP   # 3*425 + 2*9 = 1293
    ox2 = center_offset(cw, row2_w)
    oy2 = oy1 + bh1 + GAP

    canvas = create_canvas(cw, ch)
    place_grid(canvas, p1, 1, 4, ox1, oy1, GAP)
    place_grid(canvas, p2, 1, 3, ox2, oy2, GAP)
    return canvas


def _layout_wedding(img: Image.Image) -> Image.Image:
    """结婚照排版：2列×2行，4张，5寸横版画布"""
    cw, ch = CANVAS_SIZES["5寸横版"]   # 1500×1050
    pw, ph = PHOTO_SIZES["结婚照"]      # 413×579
    rows, cols = 2, 2

    photo = fit_photo(img, pw, ph)
    photo = add_border(photo, BORDER)
    bw, bh = photo.size   # 425×591

    total_w = cols * bw + (cols - 1) * GAP   # 2*425 + 9 = 859
    total_h = rows * bh + (rows - 1) * GAP   # 2*591 + 9 = 1191

    # 如果总高超过画布，缩小照片
    if total_h > ch:
        ph_new = (ch - GAP - BORDER * 4) // 2
        pw_new = round(pw * ph_new / ph)
        photo = fit_photo(img, pw_new, ph_new)
        photo = add_border(photo, BORDER)
        bw, bh = photo.size
        total_w = cols * bw + (cols - 1) * GAP
        total_h = rows * bh + (rows - 1) * GAP

    canvas = create_canvas(cw, ch)
    ox = center_offset(cw, total_w)
    oy = center_offset(ch, total_h)
    place_grid(canvas, photo, rows, cols, ox, oy, GAP)
    return canvas

# ─────────────────────────────────────────────
# 公开接口
# ─────────────────────────────────────────────
_LAYOUT_MAP = {
    "一寸排版":      _layout_1inch,
    "二寸排版":      _layout_2inch,
    "小二寸排版":    _layout_small2inch,
    "三寸排版":      _layout_3inch,
    "驾驶证排版":    _layout_driver,
    "一寸+二寸排版": _layout_1inch_2inch,
    "结婚照排版":    _layout_wedding,
}


def generate_layout(img: Image.Image, name: str) -> Image.Image:
    """
    生成排版图片。
    img: 输入图片（PIL Image，可以是 RGB 或 RGBA）
    name: 排版模板名称
    返回: 排版后的 RGB 图片（300 DPI 标注）
    """
    if img is None:
        raise ValueError("输入图片为空")
    if name not in _LAYOUT_MAP:
        raise ValueError(f"未知排版模板：{name}，可用模板：{list(_LAYOUT_MAP.keys())}")

    # 强制转 RGB（防止 RGBA 图片在 paste 时崩溃）
    if img.mode == "RGBA":
        # 合成白色背景
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img.convert("RGB"), mask=img.split()[3])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")

    result = _LAYOUT_MAP[name](img)

    # 标注 300 DPI
    result.info["dpi"] = (300, 300)
    return result


def save_layout(img: Image.Image, path: str) -> None:
    """保存排版图片为 JPEG，300 DPI"""
    if img.mode != "RGB":
        img = img.convert("RGB")
    img.save(path, "JPEG", quality=95, dpi=(300, 300))
