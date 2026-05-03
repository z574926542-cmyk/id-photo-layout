"""
抠图引擎 v2.0 - 使用 RMBG-1.4 模型（BriaAI）
相比 U²-Net 的优势：
  - 输入分辨率 1024×1024（vs 320×320），边缘更精细
  - 专为人像/前景分割设计，毛发处理更干净
  - 后处理：高斯模糊软化边缘 + S型曲线增强
  - 完全离线，ONNX 推理
模型文件：rmbg.onnx（约 176MB）
"""
from __future__ import annotations
import os
import sys
import numpy as np
from PIL import Image, ImageFilter

# ─── 全局 session 懒加载 ───
_session = None
_MODEL_FILENAME = "rmbg.onnx"

def _get_model_path() -> str:
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
            raise FileNotFoundError(
                f"找不到模型文件: {model_path}\n"
                f"请确保 rmbg.onnx 与程序在同一目录"
            )
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 4
        opts.inter_op_num_threads = 2
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        _session = ort.InferenceSession(
            model_path,
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )
    return _session

# ─── RMBG-1.4 预处理参数 ───
_RMBG_SIZE = 1024
_RMBG_MEAN = np.array([0.5, 0.5, 0.5], dtype=np.float32)
_RMBG_STD  = np.array([1.0, 1.0, 1.0], dtype=np.float32)

def _preprocess(img: Image.Image):
    orig_size = img.size  # (W, H)
    rgb = img.convert("RGB").resize((_RMBG_SIZE, _RMBG_SIZE), Image.BILINEAR)
    arr = np.array(rgb, dtype=np.float32) / 255.0
    arr = (arr - _RMBG_MEAN) / _RMBG_STD
    arr = arr.transpose(2, 0, 1)[np.newaxis, ...]  # (1, 3, 1024, 1024)
    return arr.astype(np.float32), orig_size

def _postprocess(pred: np.ndarray, orig_size) -> Image.Image:
    # pred shape: (1, 1, H, W) 或 (1, H, W) 或 (H, W)
    if pred.ndim == 4:
        mask = pred[0, 0]
    elif pred.ndim == 3:
        mask = pred[0]
    else:
        mask = pred

    # 归一化到 [0, 255]
    mn, mx = float(mask.min()), float(mask.max())
    if mx - mn > 1e-8:
        mask = (mask - mn) / (mx - mn)
    mask = (mask * 255).astype(np.uint8)

    # 还原到原始尺寸（LANCZOS 保留细节）
    mask_img = Image.fromarray(mask, mode="L")
    mask_img = mask_img.resize(orig_size, Image.LANCZOS)

    # 轻微高斯模糊软化锯齿边缘
    mask_img = mask_img.filter(ImageFilter.GaussianBlur(radius=0.6))

    # S 型曲线：前景更实、背景更透、半透明边缘保留
    arr = np.array(mask_img, dtype=np.float32)
    arr = 255.0 / (1.0 + np.exp(-0.06 * (arr - 120.0)))
    mask_img = Image.fromarray(arr.astype(np.uint8), mode="L")

    return mask_img

def remove_background(img: Image.Image) -> Image.Image:
    """
    对输入图像进行抠图，返回带 Alpha 通道的 RGBA 图像。
    Alpha=255 表示前景（人物），Alpha=0 表示背景。
    使用 RMBG-1.4 模型，1024×1024 高分辨率推理，毛发边缘更精细。
    """
    session = _get_session()
    inp, orig_size = _preprocess(img)
    input_name = session.get_inputs()[0].name
    outputs = session.run(None, {input_name: inp})
    mask = _postprocess(outputs[0], orig_size)

    rgba = img.convert("RGBA")
    r, g, b, _ = rgba.split()
    rgba = Image.merge("RGBA", (r, g, b, mask))
    return rgba

def compose_background(
    fg_rgba: Image.Image,
    bg_color: tuple = (255, 255, 255),
    bg_image: Image.Image = None,
) -> Image.Image:
    """将抠图结果合成到指定背景，返回 RGB 图像。"""
    w, h = fg_rgba.size
    if bg_image is not None:
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
