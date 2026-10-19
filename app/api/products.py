"""商品 SKU 管理 API（含图片上传/删除）。

只做 SKU 与图片图库管理，不涉及 AI、embedding、摄像头、条码、销售。
"""

import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.database import get_db
from app.models.product import Product
from app.models.product_image import ProductImage
from app.schemas.product import ProductCreate, ProductResponse, ProductUpdate
from app.schemas.product_image import ProductImageResponse

router = APIRouter(prefix="/products", tags=["products"])

# 允许的图片类型
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def _detect_image_extension(data: bytes) -> Optional[str]:
    """通过文件魔数判断真实图片格式，防止把非图片伪装成图片上传。"""
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return ".webp"
    return None


def get_product_or_404(db: Session, product_id: int) -> Product:
    """按 id 取商品，不存在则 404。附带图片关系以便返回 image_count。"""
    product = db.execute(
        select(Product)
        .options(selectinload(Product.images))
        .where(Product.id == product_id)
    ).scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail=f"商品 {product_id} 不存在")
    return product


# ===================== 商品 CRUD =====================


@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductCreate, db: Session = Depends(get_db)):
    """新增商品。sku 必须唯一。"""
    existing = db.execute(
        select(Product).where(Product.sku == payload.sku)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"SKU {payload.sku} 已存在")
    product = Product(**payload.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return get_product_or_404(db, product.id)


@router.get("", response_model=list[ProductResponse])
def list_products(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """商品列表。可用 status=active 只取在售（未来 AI 候选只用 active）。"""
    stmt = select(Product).options(selectinload(Product.images))
    if status:
        stmt = stmt.where(Product.status == status)
    stmt = stmt.order_by(Product.id)
    return db.execute(stmt).scalars().all()


@router.get("/{product_id}", response_model=ProductResponse)
def get_product(product_id: int, db: Session = Depends(get_db)):
    """单个商品详情。"""
    return get_product_or_404(db, product_id)


@router.put("/{product_id}", response_model=ProductResponse)
def update_product(
    product_id: int, payload: ProductUpdate, db: Session = Depends(get_db)
):
    """修改商品。sku 不可修改（避免历史数据关系混乱）。"""
    product = get_product_or_404(db, product_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    db.commit()
    return get_product_or_404(db, product_id)


@router.delete("/{product_id}", response_model=ProductResponse)
def delete_product(product_id: int, db: Session = Depends(get_db)):
    """逻辑删除：把 status 改为 inactive，不物理删除。"""
    product = get_product_or_404(db, product_id)
    product.status = "inactive"
    db.commit()
    return get_product_or_404(db, product_id)


# ===================== 商品图片 =====================


@router.post(
    "/{product_id}/images",
    response_model=ProductImageResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_image(
    product_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)
):
    """上传一张 SKU 参考图片。一个 SKU 可上传多张。"""
    product = get_product_or_404(db, product_id)

    # 1. 校验 Content-Type
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {file.content_type}，仅支持 jpg/jpeg/png/webp",
        )

    # 2. 读取并校验文件内容确实是图片（魔数）
    data = file.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    real_ext = _detect_image_extension(data)
    if real_ext is None:
        raise HTTPException(status_code=400, detail="文件内容不是有效的图片")

    # 3. 扩展名：优先使用上传文件名的合法扩展名，否则用魔数识别的
    original_ext = Path(file.filename or "").suffix.lower()
    ext = original_ext if original_ext in ALLOWED_EXTENSIONS else real_ext

    # 4. 保存到 uploads/products/{sku}/
    sku_dir = Path(settings.UPLOAD_DIR) / "products" / product.sku
    sku_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}{ext}"
    file_path = sku_dir / filename
    file_path.write_bytes(data)

    # 5. 数据库存相对路径
    relative_path = str(file_path.relative_to(settings.UPLOAD_DIR)).replace("\\", "/")
    image = ProductImage(product_id=product.id, image_path=relative_path)
    db.add(image)
    db.commit()
    db.refresh(image)
    return image


@router.get("/{product_id}/images", response_model=list[ProductImageResponse])
def list_images(product_id: int, db: Session = Depends(get_db)):
    """列出该 SKU 的所有参考图片。"""
    get_product_or_404(db, product_id)  # 校验商品存在
    images = db.execute(
        select(ProductImage)
        .where(ProductImage.product_id == product_id)
        .order_by(ProductImage.id)
    ).scalars().all()
    return images


@router.delete("/{product_id}/images/{image_id}")
def delete_image(
    product_id: int, image_id: int, db: Session = Depends(get_db)
):
    """删除图片：数据库记录 + 本地文件一起删除。"""
    get_product_or_404(db, product_id)  # 校验商品存在
    image = db.execute(
        select(ProductImage).where(
            ProductImage.id == image_id,
            ProductImage.product_id == product_id,
        )
    ).scalar_one_or_none()
    if image is None:
        raise HTTPException(status_code=404, detail=f"图片 {image_id} 不存在")

    # 先删本地文件，再删数据库记录
    full_path = Path(settings.UPLOAD_DIR) / image.image_path
    try:
        if full_path.exists():
            full_path.unlink()
    except OSError:
        pass  # 文件已不存在则忽略

    db.delete(image)
    db.commit()
    return {"message": "图片已删除", "image_id": image_id}
