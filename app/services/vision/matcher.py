"""查询 embedding 与数据库中 SKU 参考图 embedding 的匹配与聚合。

关键业务规则：
- 候选单位是【SKU】而不是单张图片。
- 一个 SKU 通常有多张参考图（不同角度/光线/背景），查询图只会与其中
  某一张最像。第一版采用「该 SKU 所有参考图中的最高相似度」作为 SKU
  的综合相似度，原因：
    1. 拍摄角度/光线随机，查询图往往只与某个角度的参考图高度吻合，
       取平均会被其他不相关角度稀释，导致正确 SKU 分数偏低；
    2. 图库阶段每个 SKU 图片数量可能不同，max 比 mean 更不受图片
       数量影响，避免“图多的 SKU 吃亏/占便宜”；
    3. 未来图片量大了可再升级为 top-k 平均等策略。
- 只匹配 status=active 的 SKU；inactive 商品不进入候选。
- 没有任何 embedding 的 SKU 跳过（不报错、不中断）。
- 所有有 embedding 的 active SKU 都要返回，按相似度倒序，不做 TopN 截断。
- 本模块只算相似度，绝不自动确认、绝不写库存。
"""

import logging
from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.product import Product
from app.services.vision.embedding import deserialize_embedding

logger = logging.getLogger(__name__)


@dataclass
class Candidate:
    """一个 SKU 候选（人工最终从候选列表中选择）。"""

    product_id: int  # products.id，收货登记页用它跳转 /receive?product_id=
    sku: str
    name: str
    size: str
    style: str
    sale_price: int
    similarity: float
    reference_image: str  # 该 SKU 最相似的那张参考图 URL


def cosine_similarity(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """计算一个查询向量与一组向量的余弦相似度。

    query: shape (D,)；matrix: shape (N, D)。返回 shape (N,)。
    建库时已做 L2 归一化，这里仍按通用余弦公式计算，保证稳健。
    """
    q = query.astype(np.float32)
    m = matrix.astype(np.float32)
    q_norm = np.linalg.norm(q)
    m_norm = np.linalg.norm(m, axis=1)
    if q_norm == 0 or np.any(m_norm == 0):
        # 出现零向量属于异常数据，相似度记 0，避免除零
        return np.zeros(m.shape[0], dtype=np.float32)
    return (m @ q) / (m_norm * q_norm)


def match_query_embedding(query: np.ndarray, db: Session) -> list[Candidate]:
    """用查询 embedding 匹配全部 active SKU，返回倒序候选列表。"""
    products = db.execute(
        select(Product)
        .options(selectinload(Product.images))
        .where(Product.status == "active")
        .order_by(Product.id)
    ).scalars().all()

    candidates: list[Candidate] = []
    query_dim = int(query.shape[0])
    for product in products:
        # 反序列化该 SKU 已有的参考图 embedding
        embedded: list = []
        vectors: list[np.ndarray] = []
        for img in product.images:
            if img.embedding is None:
                continue
            vec = deserialize_embedding(img.embedding)
            # 维度与查询不一致的 embedding（例如更换模型后旧库尚未 --force 重建）
            # 直接跳过，避免矩阵维度错误，也不影响其他 SKU
            if vec.shape[0] != query_dim:
                logger.warning(
                    "SKU %s 的图片 %s embedding 维度 %d 与当前模型维度 %d 不一致，跳过"
                    "（请运行 python -m app.vision.build_embeddings --force 重建）",
                    product.sku, img.image_path, vec.shape[0], query_dim,
                )
                continue
            embedded.append(img)
            vectors.append(vec)

        if not embedded:
            # 没有可用 embedding 的 SKU 不参与匹配，跳过但不影响其他 SKU
            logger.info("SKU %s 没有可用 embedding，跳过该候选", product.sku)
            continue

        matrix = np.stack(vectors)
        sims = cosine_similarity(query, matrix)

        # 第一版：取该 SKU 所有参考图中的最高相似度
        best_idx = int(np.argmax(sims))
        best_image = embedded[best_idx]
        candidates.append(
            Candidate(
                product_id=product.id,
                sku=product.sku,
                name=product.name,
                size=product.size,
                style=product.style,
                sale_price=product.sale_price,
                similarity=round(float(sims[best_idx]), 4),
                reference_image=best_image.image_url,
            )
        )

    # 相似度倒序；不做数量截断，所有 active 且有 embedding 的 SKU 都返回
    candidates.sort(key=lambda c: c.similarity, reverse=True)
    return candidates


def has_any_embedding(db: Session) -> bool:
    """是否至少存在一个 active SKU 拥有 embedding（用于给出明确报错提示）。"""
    products = db.execute(
        select(Product)
        .options(selectinload(Product.images))
        .where(Product.status == "active")
    ).scalars().all()
    return any(
        any(img.embedding is not None for img in p.images) for p in products
    )
