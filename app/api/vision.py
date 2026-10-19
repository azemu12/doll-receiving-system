"""视觉识别 API + 识别页面（含第5阶段电脑摄像头拍照识别）。

本阶段流程只有：
    摄像头拍照 / 上传图片 -> CLIP embedding -> 与 active SKU 参考图相似度排序
    -> 人工选择 -> 跳转 /receive

明确【不做】：自动确认、库存入库、回收成本、条码、打印、OpenCV 视频流。

摄像头在浏览器侧实现（getUserMedia + canvas 抓帧成 JPEG），直接复用本文件的
/vision/match，服务端不新增视频流接口，也不每次请求重建 CLIP 模型
（模型单例见 app/services/vision/model.py）。
"""

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api.products import ALLOWED_CONTENT_TYPES, _detect_image_extension
from app.core.config import settings
from app.core.database import get_db
from app.services.vision import embedding as vision_embedding
from app.services.vision.matcher import (
    has_any_embedding,
    list_active_sku_candidates,
    match_all_active_skus,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["vision"])
templates = Jinja2Templates(directory="app/templates")

NO_EMBEDDING_HINT = (
    "商品图库尚未建立Embedding，请先运行：python -m app.vision.build_embeddings"
)


def _candidate_dict(c) -> dict:
    """Candidate -> API 返回字段（has_embedding=False 时 similarity 为 None）。"""
    return {
        "product_id": c.product_id,
        "sku": c.sku,
        "name": c.name,
        "size": c.size,
        "style": c.style,
        "sale_price": c.sale_price,
        "similarity": c.similarity,
        "reference_image": c.reference_image,
        "has_embedding": c.has_embedding,
        "image_count": c.image_count,
    }


@router.get("/vision")
def vision_page(request: Request):
    """视觉识别页面（摄像头拍照 / 上传图片 + 候选列表 + 人工确认）。"""
    return templates.TemplateResponse(
        request,
        "vision.html",
        {"max_image_mb": settings.VISION_MAX_IMAGE_MB},
    )


@router.get("/vision/skus")
def list_selectable_skus(db: Session = Depends(get_db)):
    """全部可人工选择的 active SKU（兜底列表，不含相似度）。

    用于摄像头/AI 不可用或图库尚未建 embedding 时，仍让工作人员能看到并
    人工选择每一个 active SKU。similarity 一律为 None，禁止伪造。
    """
    candidates = list_active_sku_candidates(db)
    return {
        "query_image": "",
        "candidates": [_candidate_dict(c) for c in candidates],
    }


@router.post("/vision/match")
def match_image(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """上传一张娃娃图片（摄像头抓帧或文件上传），返回全部 active SKU 候选。

    - 支持 jpg/jpeg/png/webp，大小不超过配置上限（默认10MB）；
    - 查询图片只在内存中处理，不写入商品图库、不作为永久文件保存；
    - 有 embedding 的 SKU 按相似度倒序在前，未建立图库的 SKU 排最后且
      similarity=None（不伪造相似度）；
    - 只返回候选，绝不自动确认、绝不创建 inventory。
    """
    # 1. 类型与大小校验
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {file.content_type}，仅支持 jpg/jpeg/png/webp",
        )
    data = file.file.read()
    max_bytes = settings.VISION_MAX_IMAGE_MB * 1024 * 1024
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"图片过大，最大允许 {settings.VISION_MAX_IMAGE_MB}MB",
        )
    if _detect_image_extension(data) is None:
        raise HTTPException(status_code=400, detail="文件内容不是有效的图片")

    # 2. 图库中必须至少有一个 active SKU 已生成 embedding
    if not has_any_embedding(db):
        raise HTTPException(status_code=400, detail=NO_EMBEDDING_HINT)

    # 3. 查询图片 -> embedding（纯内存处理，不落盘）
    try:
        query_vec = vision_embedding.embed_bytes(data)
    except Exception as exc:
        logger.warning("查询图片解析/向量化失败: %s", exc)
        raise HTTPException(status_code=400, detail="图片解析失败，请更换图片") from exc

    # 4. 与全部 active SKU 的参考图匹配：有 embedding 的倒序在前，
    #    没有 embedding 的仍然返回（similarity=None），保证全部 SKU 可人工选择。
    candidates = match_all_active_skus(query_vec, db)
    if not candidates:
        # 没有任何 active SKU（理论上不会走到，has_any_embedding 已检查）
        raise HTTPException(status_code=400, detail="当前没有可选的在售商品SKU")

    missing = [c.sku for c in candidates if not c.has_embedding]
    if missing:
        logger.info("以下SKU未建立图库Embedding，已排在候选末尾由人工选择: %s",
                    ", ".join(missing))

    # query_image 留空：查询图片是临时数据，不持久化，前端用本地预览
    return {
        "query_image": "",
        "candidates": [_candidate_dict(c) for c in candidates],
    }
