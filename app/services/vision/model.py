"""CLIP 视觉模型的加载与生命周期管理。

设计要求：
1. 模型在进程内只加载一次（懒加载单例 + 线程锁）。
2. API 请求和批量建库脚本共用同一份模型，不会重复加载。
3. 设备可选 auto / cpu / cuda：auto 时检测到 CUDA 就用 GPU，否则 CPU。
4. 模型名称、权重来源全部来自配置（.env），不硬编码在业务代码里。
5. 未来要换模型时，只需改配置，或替换本文件实现。

第一次运行会自动下载预训练权重（ViT-B-32/openai 约 350MB），详见 README。
"""

import logging
import threading
from typing import Optional, Tuple

import open_clip
import torch
from PIL.Image import Image as PILImage

from app.core.config import settings

logger = logging.getLogger(__name__)

# 进程内单例状态。模型只加载一次。
_state: dict = {
    "model": None,
    "preprocess": None,
    "device": None,
    "dim": None,
}
_lock = threading.Lock()


def select_device() -> str:
    """根据配置选择运行设备。auto=有 CUDA 用 GPU，否则 CPU。"""
    configured = settings.VISION_DEVICE.lower()
    if configured == "auto":
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            logger.info("检测到 CUDA，视觉模型运行在 GPU: %s", name)
            return "cuda"
        logger.info("未检测到 CUDA，视觉模型运行在 CPU")
        return "cpu"
    return configured


def get_model() -> Tuple[torch.nn.Module, "object", str]:
    """获取模型单例 (model, preprocess, device)，首次调用时加载。"""
    if _state["model"] is None:
        with _lock:
            # 双重检查：可能在等锁期间已被其他线程加载
            if _state["model"] is None:
                device = select_device()
                logger.info(
                    "加载视觉模型: %s / %s（首次运行需下载权重，请耐心等待）",
                    settings.VISION_MODEL_NAME,
                    settings.VISION_PRETRAINED,
                )
                # OpenAI 发布的原版 CLIP 权重使用 QuickGELU 激活函数，
                # 新版 open_clip 默认 GELU，需显式开启以保证与原版权重匹配。
                # laion/openclip 等权重使用普通 GELU，不能强加此参数。
                force_quick_gelu = settings.VISION_PRETRAINED.lower() == "openai"
                model, _, preprocess = open_clip.create_model_and_transforms(
                    settings.VISION_MODEL_NAME,
                    pretrained=settings.VISION_PRETRAINED,
                    force_quick_gelu=force_quick_gelu,
                )
                model = model.eval().to(device)

                # 探测 embedding 维度：编码一张全黑图片得到输出宽度
                with torch.no_grad():
                    dummy = torch.zeros(1, 3, 224, 224, device=device)
                    dim = int(model.encode_image(dummy).shape[-1])

                _state.update(
                    model=model,
                    preprocess=preprocess,
                    device=device,
                    dim=dim,
                )
                logger.info("视觉模型加载完成，embedding 维度: %d，设备: %s", dim, device)
    return _state["model"], _state["preprocess"], _state["device"]


def get_embedding_dim() -> Optional[int]:
    """返回已加载模型的 embedding 维度；模型未加载时返回 None。"""
    return _state["dim"]
