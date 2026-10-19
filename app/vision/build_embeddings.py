"""为商品图库批量生成 embedding。

用法：
    python -m app.vision.build_embeddings           # 只为 embedding 为空的图片生成
    python -m app.vision.build_embeddings --force   # 强制全部重新生成

规则：
- 只处理 status=active 的商品；
- 已有 embedding 的图片默认跳过；
- 模型只加载一次，在进程内复用；
- 失败图片不中断整体流程，最后汇总失败原因。
"""

import argparse
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.models.product import Product
from app.services.vision.embedding import embed_file, serialize_embedding
from app.services.vision.model import get_embedding_dim, get_model


def run(force: bool = False) -> int:
    init_db()
    # 先加载模型（只加载一次）；下载/加载失败时直接报错退出
    get_model()
    dim = get_embedding_dim()

    total = success = failed = skipped = 0
    failures: list[tuple[str, str]] = []

    db = SessionLocal()
    try:
        products = db.execute(
            select(Product)
            .options(selectinload(Product.images))
            .where(Product.status == "active")
            .order_by(Product.id)
        ).scalars().all()

        for product in products:
            for img in product.images:
                total += 1
                label = f"{product.sku} / {img.image_path}"

                if img.embedding is not None and not force:
                    skipped += 1
                    print(f"{label} / 跳过（已有embedding）")
                    continue

                full_path = Path(settings.UPLOAD_DIR) / img.image_path
                if not full_path.exists():
                    failed += 1
                    reason = "本地图片文件不存在"
                    failures.append((label, reason))
                    print(f"{label} / 失败 / {reason}")
                    continue

                try:
                    vec = embed_file(str(full_path))
                    img.embedding = serialize_embedding(vec)
                    db.commit()
                    success += 1
                    print(f"{label} / OK / dim={vec.shape[0]}")
                except Exception as exc:  # 单张失败不影响其他图片
                    db.rollback()
                    failed += 1
                    reason = f"{type(exc).__name__}: {exc}"
                    failures.append((label, reason))
                    print(f"{label} / 失败 / {reason}")
    finally:
        db.close()

    print("\n========== 汇总 ==========")
    print(f"总图片数：{total}")
    print(f"成功：{success}")
    print(f"失败：{failed}")
    print(f"跳过：{skipped}")
    print(f"embedding维度：{dim}")
    if failures:
        print("\n失败明细：")
        for label, reason in failures:
            print(f"  {label} -> {reason}")
    return 0 if failed == 0 else 1


def main():
    parser = argparse.ArgumentParser(description="为商品参考图生成 embedding")
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新生成所有图片的 embedding（默认跳过已有的）",
    )
    args = parser.parse_args()
    sys.exit(run(force=args.force))


if __name__ == "__main__":
    main()
