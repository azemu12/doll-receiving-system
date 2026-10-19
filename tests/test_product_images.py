"""商品图片 API 测试。

覆盖：上传成功、查询图片、删除图片（数据库记录 + 本地文件都删除）。
"""

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.database import SessionLocal
from app.main import app
from app.models.product import Product
from app.models.product_image import ProductImage

# 一个合法的 1x1 PNG 文件字节（用于模拟真实图片上传）
PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf"
    b"\xc0\xf0\x1f\x00\x04\xff\x01\xfe\xa5\xea\xa0\x82\x00\x00\x00\x00IEND"
    b"\xaeB`\x82"
)

TEST_SKU = "TEST-IMG-SKU"

client = TestClient(app)


@pytest.fixture
def product():
    """创建一个测试用 SKU，测试结束后清理图片文件、图片记录和 SKU。"""
    _cleanup()
    pid = client.post(
        "/products",
        json={"sku": TEST_SKU, "name": "测试", "size": "20cm", "style": "x", "sale_price": 10},
    ).json()["id"]
    yield pid
    _cleanup()


def _cleanup():
    with SessionLocal() as db:
        product = db.execute(
            select(Product).where(Product.sku == TEST_SKU)
        ).scalar_one_or_none()
        if product is not None:
            images = db.execute(
                select(ProductImage).where(ProductImage.product_id == product.id)
            ).scalars().all()
            for img in images:
                full = Path(settings.UPLOAD_DIR) / img.image_path
                if full.exists():
                    full.unlink()
                db.delete(img)
            db.delete(product)
        db.commit()


def test_upload_image_success(product):
    """7. 上传图片成功，本地文件也存在。"""
    resp = client.post(
        f"/products/{product}/images",
        files={"file": ("test.png", io.BytesIO(PNG_BYTES), "image/png")},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["product_id"] == product
    assert data["image_path"].endswith(".png")
    # 本地文件确实存在
    full = Path(settings.UPLOAD_DIR) / data["image_path"]
    assert full.exists()
    assert full.read_bytes() == PNG_BYTES


def test_list_images(product):
    """8. 查询 SKU 图片。"""
    for i in range(2):
        client.post(
            f"/products/{product}/images",
            files={"file": (f"t{i}.png", io.BytesIO(PNG_BYTES), "image/png")},
        )
    resp = client.get(f"/products/{product}/images")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_delete_image_removes_db_and_file(product):
    """9. 删除图片后数据库记录和本地文件都删除。"""
    up = client.post(
        f"/products/{product}/images",
        files={"file": ("del.png", io.BytesIO(PNG_BYTES), "image/png")},
    )
    image_id = up.json()["id"]
    full = Path(settings.UPLOAD_DIR) / up.json()["image_path"]
    assert full.exists()

    resp = client.delete(f"/products/{product}/images/{image_id}")
    assert resp.status_code == 200
    # 数据库记录已删
    lst = client.get(f"/products/{product}/images").json()
    assert all(i["id"] != image_id for i in lst)
    # 本地文件已删
    assert not full.exists()


def test_upload_non_image_rejected(product):
    """附加：非图片文件应被拒绝（魔数校验）。"""
    resp = client.post(
        f"/products/{product}/images",
        files={"file": ("fake.png", io.BytesIO(b"this is not an image"), "image/png")},
    )
    assert resp.status_code == 400
