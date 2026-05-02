"""
U²-Net 本地抠图引擎
使用 u2net.onnx 模型推理，生成人物蒙版，支持换背景合成。
"""
import os
import sys
import numpy as np
from PIL import Image

# ─── ONNX Runtime 懒加载 ───
_session = None
_MODEL_FILENAME = "u2net.onnx"


def _get_model_path() -> str:
    """查找模型文件路径（支持打包后的 _MEIPASS）"""
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, _MODEL_FILENAME)


def _get_session():
    global _session
    if _session is None:
        import onnxruntime as ort
        model_path = _get_model_path()
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"找不到模型文件: {model_path}")
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 4
        opts.inter_op_num_threads = 2
        _session = ort.InferenceSession(
            model_path,
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )
    return _session


def _preprocess(img: Image.Image) -> np.ndarray:
    """将 PIL 图像预处理为 U²-Net 输入张量 (1,3,320,320)"""
    img = img.convert("RGB").resize((320, 320), Image.BILINEAR)
    arr = np.array(img, dtype=np.float32) / 255.0
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std  = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    arr  = (arr - mean) / std
    arr  = arr.transpose(2, 0, 1)[np.newaxis, ...]  # (1,3,320,320)
    return arr.astype(np.float32)


def _postprocess(pred: np.ndarray, orig_size: tuple) -> Image.Image:
    """将模型输出转换为原始尺寸的灰度蒙版"""
    mask = pred[0, 0]                          # (320,320)
    mask = (mask - mask.min()) / (mask.max() - mask.min() + 1e-8)
    mask = (mask * 255).astype(np.uint8)
    mask_img = Image.fromarray(mask, mode="L")
    mask_img = mask_img.resize(orig_size, Image.BILINEAR)
    return mask_img


def remove_background(img: Image.Image) -> Image.Image:
    """
    对输入图像进行抠图，返回带 Alpha 通道的 RGBA 图像。
    Alpha=255 表示前景（人物），Alpha=0 表示背景。
    """
    orig_size = img.size
    session = _get_session()
    inp = _preprocess(img)
    input_name = session.get_inputs()[0].name
    outputs = session.run(None, {input_name: inp})
    mask = _postprocess(outputs[0], orig_size)

    # 将蒙版应用到原图
    rgba = img.convert("RGBA")
    r, g, b, _ = rgba.split()
    rgba = Image.merge("RGBA", (r, g, b, mask))
    return rgba


def compose_background(
    fg_rgba: Image.Image,
    bg_color: tuple = (255, 255, 255),
    bg_image: Image.Image = None,
) -> Image.Image:
    """
    将抠图结果合成到指定背景。
    - bg_color: RGB 元组，纯色背景
    - bg_image: PIL Image，图片背景（优先级高于 bg_color）
    返回 RGB 图像。
    """
    w, h = fg_rgba.size
    if bg_image is not None:
        # 图片背景：等比填满后居中裁剪
        bw, bh = bg_image.size
        scale = max(w / bw, h / bh)
        nw, nh = int(bw * scale), int(bh * scale)
        bg = bg_image.convert("RGB").resize((nw, nh), Image.LANCZOS)
        x0 = (nw - w) // 2
        y0 = (nh - h) // 2
        bg = bg.crop((x0, y0, x0 + w, y0 + h))
    else:
        bg = Image.new("RGB", (w, h), bg_color)

    bg.paste(fg_rgba, mask=fg_rgba.split()[3])
    return bg
