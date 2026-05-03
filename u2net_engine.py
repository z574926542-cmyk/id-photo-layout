"""
抠图引擎 v3.0 - MODNet（Trimap-Free Portrait Matting）
相比 RMBG-1.4 的优势：
  - Matting 模型，输出真正的 Alpha 软边（非硬分割）
  - 发丝、半透明边缘精细处理
  - 模型体积仅 ~25MB（vs RMBG 的 176MB）
  - 完全离线，ONNX 推理
模型文件：modnet.onnx
"""
from __future__ import annotations
import os
import sys
import numpy as np
from PIL import Image, ImageFilter

_session = None
_MODEL_FILENAME = "modnet.onnx"
_REF_SIZE = 512


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
                f"请确保 modnet.onnx 与程序在同一目录"
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


def _get_scale_factor(im_h: int, im_w: int, ref_size: int):
    if max(im_h, im_w) < ref_size or min(im_h, im_w) > ref_size:
        if im_w >= im_h:
            im_rh = ref_size
            im_rw = int(im_w / im_h * ref_size)
        else:
            im_rw = ref_size
            im_rh = int(im_h / im_w * ref_size)
    else:
        im_rh = im_h
        im_rw = im_w
    im_rw = max(32, im_rw - im_rw % 32)
    im_rh = max(32, im_rh - im_rh % 32)
    return im_rw / im_w, im_rh / im_h


def _preprocess(img: Image.Image):
    orig_size = img.size  # (W, H)
    rgb = img.convert("RGB")
    arr = np.array(rgb, dtype=np.float32)
    im_h, im_w = arr.shape[:2]
    arr = (arr - 127.5) / 127.5
    x_scale, y_scale = _get_scale_factor(im_h, im_w, _REF_SIZE)
    new_w = int(im_w * x_scale)
    new_h = int(im_h * y_scale)
    # 缩放
    tmp = ((arr * 127.5 + 127.5).clip(0, 255).astype(np.uint8))
    arr_scaled = np.array(
        Image.fromarray(tmp).resize((new_w, new_h), Image.LANCZOS),
        dtype=np.float32
    )
    arr_scaled = (arr_scaled - 127.5) / 127.5
    # (H,W,3) -> (1,3,H,W)
    arr_scaled = arr_scaled.transpose(2, 0, 1)[np.newaxis, ...]
    return arr_scaled.astype(np.float32), orig_size


def _postprocess(pred: np.ndarray, orig_wh: tuple) -> Image.Image:
    if pred.ndim == 4:
        matte = pred[0, 0]
    elif pred.ndim == 3:
        matte = pred[0]
    else:
        matte = pred
    mn, mx = float(matte.min()), float(matte.max())
    if mx - mn > 1e-8:
        matte = (matte - mn) / (mx - mn)
    matte = (matte * 255).clip(0, 255).astype(np.uint8)
    matte_img = Image.fromarray(matte, mode="L")
    matte_img = matte_img.resize(orig_wh, Image.LANCZOS)
    matte_img = matte_img.filter(ImageFilter.GaussianBlur(radius=0.4))
    return matte_img


def remove_background(img: Image.Image) -> Image.Image:
    """
    对输入图像进行抠图，返回带 Alpha 通道的 RGBA 图像。
    Alpha=255 表示前景（人物），Alpha=0 表示背景。
    """
    session = _get_session()
    inp, orig_size = _preprocess(img)
    input_name  = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name
    outputs = session.run([output_name], {input_name: inp})
    matte = _postprocess(outputs[0], orig_size)
    rgba = img.convert("RGBA")
    r, g, b, _ = rgba.split()
    rgba = Image.merge("RGBA", (r, g, b, matte))
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
