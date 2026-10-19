"""商品 SKU API 测试。

覆盖：创建成功、SKU 重复失败、售价非整数失败、查询、修改、逻辑删除、
inactive 仍可查询但不出现在 active 过滤结果中。
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core.database import SessionLocal
from app.main import app
from app.models.product import Product

TEST_SKU_PREFIX = "TEST-SKU-"

client = TestClient(app)


def _cleanup_test_skus():
    """清理所有以 TEST-SKU- 开头的测试商品。"""
    with SessionLocal() as db:
        db.execute(delete(Product).where(Product.sku.like(f"{TEST_SKU_PREFIX}%")))
        db.commit()


@pytest.fixture(autouse=True)
def cleanup():
    _cleanup_test_skus()
    yield
    _cleanup_test_skus()


def test_create_product_success():
    """1. 创建商品成功。"""
    resp = client.post(
        "/products",
        json={
            "sku": f"{TEST_SKU_PREFIX}001",
            "name": "测试娃娃",
            "size": "20cm",
            "style": "普通款",
            "sale_price": 40,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["sku"] == f"{TEST_SKU_PREFIX}001"
    assert data["name"] == "测试娃娃"
    assert data["sale_price"] == 40
    assert data["status"] == "active"
    assert data["image_count"] == 0


def test_duplicate_sku_fails():
    """2. SKU 重复时失败。"""
    payload = {
        "sku": f"{TEST_SKU_PREFIX}DUP",
        "name": "a",
        "size": "20cm",
        "style": "x",
        "sale_price": 10,
    }
    assert client.post("/products", json=payload).status_code == 201
    dup = client.post("/products", json=payload)
    assert dup.status_code == 409


def test_sale_price_not_int_fails():
    """3. sale_price 不是整数时失败。"""
    resp = client.post(
        "/products",
        json={
            "sku": f"{TEST_SKU_PREFIX}FLOAT",
            "name": "a",
            "size": "20cm",
            "style": "x",
            "sale_price": 19.9,
        },
    )
    assert resp.status_code == 422


def test_get_product():
    """4. 查询商品。"""
    sku = f"{TEST_SKU_PREFIX}GET"
    pid = client.post(
        "/products",
        json={"sku": sku, "name": "a", "size": "20cm", "style": "x", "sale_price": 25},
    ).json()["id"]
    # 单个查询
    resp = client.get(f"/products/{pid}")
    assert resp.status_code == 200
    assert resp.json()["sku"] == sku
    # 列表也能查到
    lst = client.get("/products").json()
    assert any(p["sku"] == sku for p in lst)


def test_update_product():
    """5. 修改商品（sku 不可修改）。"""
    sku = f"{TEST_SKU_PREFIX}UPD"
    pid = client.post(
        "/products",
        json={"sku": sku, "name": "旧名", "size": "20cm", "style": "x", "sale_price": 25},
    ).json()["id"]
    resp = client.put(
        f"/products/{pid}",
        json={"name": "新名", "sale_price": 99, "status": "active"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "新名"
    assert resp.json()["sale_price"] == 99
    # sku 不允许修改：即使传了 sku 也应被忽略
    client.put(f"/products/{pid}", json={"sku": "SHOULD-NOT-CHANGE"})
    assert client.get(f"/products/{pid}").json()["sku"] == sku


def test_soft_delete_sets_inactive():
    """6. 商品逻辑删除后 status 变为 inactive。"""
    sku = f"{TEST_SKU_PREFIX}DEL"
    pid = client.post(
        "/products",
        json={"sku": sku, "name": "a", "size": "20cm", "style": "x", "sale_price": 10},
    ).json()["id"]
    resp = client.delete(f"/products/{pid}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "inactive"
    # 仍可查询
    assert client.get(f"/products/{pid}").status_code == 200


def test_inactive_excluded_from_active_filter():
    """10. inactive 商品仍可查询，但不出现在 status=active 结果中（未来 AI 候选只用 active）。"""
    sku = f"{TEST_SKU_PREFIX}INA"
    pid = client.post(
        "/products",
        json={"sku": sku, "name": "a", "size": "20cm", "style": "x", "sale_price": 10},
    ).json()["id"]
    client.delete(f"/products/{pid}")
    # 全量列表仍能查到
    assert any(p["id"] == pid for p in client.get("/products").json())
    # active 过滤查不到
    actives = client.get("/products", params={"status": "active"}).json()
    assert not any(p["id"] == pid for p in actives)
