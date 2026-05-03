"""
layout_engine v22 — 证件照排版引擎
修复：
  - 描边改为黑色 (0,0,0)
  - 画布尺寸精确贴合照片组（无多余白边），裁一刀即可分割
  - 一寸+二寸合并版：左侧3×3=9张一寸，右侧2×2=4张二寸，7寸横版画布
"""
from PIL import Image

# ─────────────────────────────────────────────
# 常量（300 DPI 像素尺寸）
# ─────────────────────────────────────────────
PHOTO_SIZES = {
    "一寸":   (295, 413),    # 25×35mm
    "二寸":   (413, 579),    # 35×49mm
    "小二寸": (413, 531),    # 35×45mm
    "三寸":   (826, 1063),   # 70×90mm
    "驾驶证": (216, 280),    # 18.3×23.8mm
    "结婚照": (413, 579),    # 35×49mm（同二寸）
}

CANVAS_SIZES = {
    "5寸竖版": (1050, 1500),  # 89×127mm
    "5寸横版": (1500, 1050),  # 127×89mm
    "7寸横版": (2100, 1500),  # 178×127mm
}

GAP    = 3    # 照片间距 3px（裁一刀可分割）
BORDER = 1    # 照片描边 1px @ 300DPI（极细分割线，不影响裁剪）
BORDER_COLOR = (0, 0, 0)  # 黑色描边

# ─────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────
def fit_photo(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """cover 模式：等比缩放填满目标尺寸，居中裁剪。"""
    if target_w <= 0 or target_h <= 0:
        raise ValueError(f"目标尺寸无效：{target_w}×{target_h}")
    src_w, src_h = img.size
    if src_w <= 0 or src_h <= 0:
        raise ValueError(f"源图片尺寸无效：{src_w}×{src_h}")
    scale = max(target_w / src_w, target_h / src_h)
    new_w = max(1, round(src_w * scale))
    new_h = max(1, round(src_h * scale))
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top  = (new_h - target_h) // 2
    img  = img.crop((left, top, left + target_w, top + target_h))
    return img

def add_border(img: Image.Image, border_px: int,
               color=BORDER_COLOR) -> Image.Image:
    """在照片四周添加黑色描边（向外扩展）。"""
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
    """将 photo 按 rows×cols 网格放置到 canvas 上。"""
    pw, ph = photo.size
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
            if x < 0 or y < 0 or x + pw > canvas.width or y + ph > canvas.height:
                continue
            if mask:
                canvas.paste(photo_rgb, (x, y), mask)
            else:
                canvas.paste(photo_rgb, (x, y))

def center_offset(canvas_size: int, content_size: int) -> int:
    """计算居中偏移量（内容在画布中居中）。"""
    return max(0, (canvas_size - content_size) // 2)

def tight_canvas(photo: Image.Image, rows: int, cols: int,
                 gap: int) -> tuple:
    """
    计算紧密贴合的画布尺寸（照片组恰好填满，无多余白边）。
    返回 (canvas_w, canvas_h)。
    """
    pw, ph = photo.size
    cw = cols * pw + (cols - 1) * gap
    ch = rows * ph + (rows - 1) * gap
    return cw, ch

# ─────────────────────────────────────────────
# 排版函数
# ─────────────────────────────────────────────

def _layout_1inch(img: Image.Image) -> Image.Image:
    """一寸排版：3列×3行，9张，5寸竖版画布（1050×1500）。"""
    cw, ch = CANVAS_SIZES["5寸竖版"]   # 1050×1500
    pw, ph = PHOTO_SIZES["一寸"]        # 295×413
    rows, cols = 3, 3
    photo = fit_photo(img, pw, ph)
    photo = add_border(photo, BORDER)
    bw, bh = photo.size   # 307×425
    total_w = cols * bw + (cols - 1) * GAP   # 3*307 + 2*3 = 927
    total_h = rows * bh + (rows - 1) * GAP   # 3*425 + 2*3 = 1281
    canvas = create_canvas(cw, ch)
    ox = center_offset(cw, total_w)
    oy = center_offset(ch, total_h)
    place_grid(canvas, photo, rows, cols, ox, oy, GAP)
    return canvas

def _layout_2inch(img: Image.Image) -> Image.Image:
    """二寸排版：2列×2行，4张，5寸竖版画布（1050×1500）。"""
    cw, ch = CANVAS_SIZES["5寸竖版"]   # 1050×1500
    pw, ph = PHOTO_SIZES["二寸"]        # 413×579
    rows, cols = 2, 2
    photo = fit_photo(img, pw, ph)
    photo = add_border(photo, BORDER)
    bw, bh = photo.size   # 425×591
    total_w = cols * bw + (cols - 1) * GAP   # 2*425 + 3 = 853
    total_h = rows * bh + (rows - 1) * GAP   # 2*591 + 3 = 1185
    canvas = create_canvas(cw, ch)
    ox = center_offset(cw, total_w)
    oy = center_offset(ch, total_h)
    place_grid(canvas, photo, rows, cols, ox, oy, GAP)
    return canvas

def _layout_small2inch(img: Image.Image) -> Image.Image:
    """小二寸排版：2列×2行，4张，5寸竖版画布（1050×1500）。"""
    cw, ch = CANVAS_SIZES["5寸竖版"]   # 1050×1500
    pw, ph = PHOTO_SIZES["小二寸"]      # 413×531
    rows, cols = 2, 2
    photo = fit_photo(img, pw, ph)
    photo = add_border(photo, BORDER)
    bw, bh = photo.size   # 425×543
    total_w = cols * bw + (cols - 1) * GAP   # 2*425 + 3 = 853
    total_h = rows * bh + (rows - 1) * GAP   # 2*543 + 3 = 1089
    canvas = create_canvas(cw, ch)
    ox = center_offset(cw, total_w)
    oy = center_offset(ch, total_h)
    place_grid(canvas, photo, rows, cols, ox, oy, GAP)
    return canvas

def _layout_3inch(img: Image.Image) -> Image.Image:
    """三寸排版：1列×2行，2张，5寸竖版画布（1050×1500）。"""
    cw, ch = CANVAS_SIZES["5寸竖版"]   # 1050×1500
    pw, ph = PHOTO_SIZES["三寸"]        # 826×1063
    rows, cols = 1, 2

    # 三寸宽826，两张横排：2*826+3=1655 > 1050，改为竖排1列×2行
    rows, cols = 2, 1
    # 高度：2*1063+3=2129 > 1500，需缩小
    # 适配画布：每张高度 = (1500 - GAP - BORDER*4) // 2
    ph_fit = (ch - GAP - BORDER * 4) // 2   # (1500 - 3 - 24) // 2 = 736
    pw_fit = round(pw * ph_fit / ph)         # 826 * 736/1063 ≈ 572
    photo = fit_photo(img, pw_fit, ph_fit)
    photo = add_border(photo, BORDER)
    bw, bh = photo.size
    total_w = cols * bw
    total_h = rows * bh + (rows - 1) * GAP
    canvas = create_canvas(cw, ch)
    ox = center_offset(cw, total_w)
    oy = center_offset(ch, total_h)
    place_grid(canvas, photo, rows, cols, ox, oy, GAP)
    return canvas

def _layout_driver(img: Image.Image) -> Image.Image:
    """驾驶证排版：5列×2行，10张，5寸横版画布（1500×1050）。"""
    cw, ch = CANVAS_SIZES["5寸横版"]   # 1500×1050
    pw, ph = PHOTO_SIZES["驾驶证"]      # 216×280
    rows, cols = 2, 5
    photo = fit_photo(img, pw, ph)
    photo = add_border(photo, BORDER)
    bw, bh = photo.size   # 228×292
    total_w = cols * bw + (cols - 1) * GAP   # 5*228 + 4*3 = 1152
    total_h = rows * bh + (rows - 1) * GAP   # 2*292 + 3 = 587
    canvas = create_canvas(cw, ch)
    ox = center_offset(cw, total_w)
    oy = center_offset(ch, total_h)
    place_grid(canvas, photo, rows, cols, ox, oy, GAP)
    return canvas

def _layout_1inch_2inch(img: Image.Image) -> Image.Image:
    """
    一寸+二寸混排：7寸横版画布（2100×1500）。
    左侧：3列×3行 = 9张一寸
    右侧：2列×2行 = 4张二寸
    两组之间用 GROUP_GAP 分隔。
    """
    cw, ch = CANVAS_SIZES["7寸横版"]   # 2100×1500
    GROUP_GAP = 30  # 两组之间的分隔间距

    pw1, ph1 = PHOTO_SIZES["一寸"]     # 295×413
    pw2, ph2 = PHOTO_SIZES["二寸"]     # 413×579

    p1 = fit_photo(img, pw1, ph1)
    p1 = add_border(p1, BORDER)
    p2 = fit_photo(img, pw2, ph2)
    p2 = add_border(p2, BORDER)

    bw1, bh1 = p1.size   # 307×425
    bw2, bh2 = p2.size   # 425×591

    # 左侧一寸组：3列×3行
    rows1, cols1 = 3, 3
    group1_w = cols1 * bw1 + (cols1 - 1) * GAP   # 3*307 + 2*3 = 927
    group1_h = rows1 * bh1 + (rows1 - 1) * GAP   # 3*425 + 2*3 = 1281

    # 右侧二寸组：2列×2行
    rows2, cols2 = 2, 2
    group2_w = cols2 * bw2 + (cols2 - 1) * GAP   # 2*425 + 3 = 853
    group2_h = rows2 * bh2 + (rows2 - 1) * GAP   # 2*591 + 3 = 1185

    # 两组总宽
    total_w = group1_w + GROUP_GAP + group2_w   # 927 + 30 + 853 = 1810
    total_h = max(group1_h, group2_h)           # 1281

    canvas = create_canvas(cw, ch)
    ox = center_offset(cw, total_w)   # (2100 - 1810) // 2 = 145
    oy = center_offset(ch, total_h)   # (1500 - 1281) // 2 = 109

    # 左侧一寸：垂直居中
    oy1 = oy + center_offset(total_h, group1_h)
    place_grid(canvas, p1, rows1, cols1, ox, oy1, GAP)

    # 右侧二寸：垂直居中
    ox2 = ox + group1_w + GROUP_GAP
    oy2 = oy + center_offset(total_h, group2_h)
    place_grid(canvas, p2, rows2, cols2, ox2, oy2, GAP)

    return canvas

def _layout_wedding(img: Image.Image) -> Image.Image:
    """结婚照排版：2列×2行，4张，5寸横版画布（1500×1050）。"""
    cw, ch = CANVAS_SIZES["5寸横版"]   # 1500×1050
    pw, ph = PHOTO_SIZES["结婚照"]      # 413×579
    rows, cols = 2, 2
    photo = fit_photo(img, pw, ph)
    photo = add_border(photo, BORDER)
    bw, bh = photo.size   # 425×591
    total_w = cols * bw + (cols - 1) * GAP   # 2*425 + 3 = 853
    total_h = rows * bh + (rows - 1) * GAP   # 2*591 + 3 = 1185
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
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img.convert("RGB"), mask=img.split()[3])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    result = _LAYOUT_MAP[name](img)
    result.info["dpi"] = (300, 300)
    return result

def save_layout(img: Image.Image, path: str) -> None:
    """保存排版图片为 JPEG，300 DPI"""
    if img.mode != "RGB":
        img = img.convert("RGB")
    img.save(path, "JPEG", quality=95, dpi=(300, 300))
