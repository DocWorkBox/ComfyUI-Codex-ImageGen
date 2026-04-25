from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image


def save_image_tensor_to_comfy_input(images, input_dir: Path, filename_prefix: str) -> list[Path]:
    if images is None:
        return []

    input_dir.mkdir(parents=True, exist_ok=True)
    array = _tensor_to_numpy(images)
    saved: list[Path] = []
    for index, image_array in enumerate(array, start=1):
        path = input_dir / f"{filename_prefix}_{index:03d}.png"
        Image.fromarray(image_array).save(path)
        saved.append(path)
    return saved


def load_image_tensor_from_path(image_path: str | Path):
    path = Path(image_path)
    if not path.exists():
        return empty_image_tensor()
    image = Image.open(path).convert("RGB")
    array = np.asarray(image).astype(np.float32) / 255.0
    array = np.expand_dims(array, axis=0)
    return _numpy_to_tensor(array)


def empty_image_tensor():
    array = np.zeros((1, 1, 1, 3), dtype=np.float32)
    return _numpy_to_tensor(array)


def _image_tensor_to_float_numpy(images) -> np.ndarray:
    if hasattr(images, "detach"):
        images = images.detach().cpu().numpy()
    else:
        images = np.asarray(images)

    if images.ndim == 3:
        images = np.expand_dims(images, axis=0)
    if images.ndim != 4:
        raise ValueError("images must be a ComfyUI IMAGE tensor with shape [B,H,W,C].")
    if images.shape[-1] == 4:
        images = images[..., :3]
    if images.shape[-1] != 3:
        raise ValueError("images must have 3 RGB channels or 4 RGBA channels.")
    return np.clip(images.astype(np.float32), 0.0, 1.0)


def _tensor_to_numpy(images) -> np.ndarray:
    images = _image_tensor_to_float_numpy(images)
    return (images * 255.0).round().astype(np.uint8)


def _numpy_to_tensor(array: np.ndarray):
    try:
        import torch

        return torch.from_numpy(array)
    except Exception:
        return array
