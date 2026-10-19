"""图片 -> embedding，以及 embedding 与数据库 JSON 之间的序列化。

product_images.embedding 字段是 MySQL JSON，存储格式要求：
- numpy 数组 -> 普通 Python float 组成的 list（可 JSON 序列化）
- 读取后恢复成 numpy.float32 数组
- 全库 embedding 维度统一（由模型决定，ViT-B-32 为 512）
"""

import io
from typing import List, Sequence

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

from app.services.vision.model import get_model


def serialize_embedding(vec: np.ndarray) -> List[float]:
    """numpy 数组 -> 可存入 JSON 的普通 Python float 列表。"""
    arr = np.asarray(vec, dtype=np.float32).reshape(-1)
    return [float(x) for x in arr]


def deserialize_embedding(data: Sequence) -> np.ndarray:
    """JSON(list) -> numpy.float32 一维数组。"""
    return np.asarray(data, dtype=np.float32).reshape(-1)


def embed_pil_image(image: Image.Image) -> np.ndarray:
    """PIL 图片 -> L2 归一化后的 embedding（float32 一维数组）。

    归一化后，两个向量的余弦相似度就是点积，matcher 中计算更简单。
    """
    model, preprocess, device = get_model()
    image = image.convert("RGB")
    tensor = preprocess(image).unsqueeze(0).to(device)
    with torch.no_grad():
        features = model.encode_image(tensor)
        features = F.normalize(features, dim=-1)
    return features.cpu().numpy().astype(np.float32).reshape(-1)


def embed_bytes(data: bytes) -> np.ndarray:
    """图片字节 -> embedding（用于 API 上传的查询图片）。"""
    image = Image.open(io.BytesIO(data))
    image.load()  # 提前触发解码，损坏文件会在这里抛异常
    return embed_pil_image(image)


def embed_file(path: str) -> np.ndarray:
    """本地图片文件路径 -> embedding（用于批量建库脚本）。"""
    with Image.open(path) as image:
        image.load()
        return embed_pil_image(image)
