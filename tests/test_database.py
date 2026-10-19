"""第1阶段数据库基础测试。

运行前提：.env 已配置好，且 MySQL 中已创建数据库（见 README）。

覆盖：
1. 可以连接 MySQL
2. 三张表能够创建
3. products 可以插入一条测试数据
4. inventory 可以关联 products

测试数据会自动清理，不会污染业务数据。
"""

from decimal import Decimal

import pytest
from sqlalchemy import delete, select, text

from app.core.database import Base, SessionLocal, engine
from app.models import Inventory, Product

TEST_SKU = "TEST-SKU-001"
TEST_CODE_PREFIX = "D-TEST-"


@pytest.fixture(scope="module", autouse=True)
def tables():
    """确保三张表存在（不存在则创建），结束后清理测试数据。"""
    Base.metadata.create_all(bind=engine)
    yield
    _cleanup()


def _cleanup():
    """清理测试数据（外键顺序：先 inventory 后 products）。"""
    with SessionLocal() as db:
        db.execute(delete(Inventory).where(Inventory.inventory_code.like(f"{TEST_CODE_PREFIX}%")))
        db.execute(delete(Product).where(Product.sku == TEST_SKU))
        db.commit()


def test_can_connect_mysql():
    """1. 可以连接 MySQL。"""
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1


def test_three_tables_created():
    """2. 三张表能够创建。"""
    with engine.connect() as conn:
        tables_in_db = set(conn.execute(text("SHOW TABLES")).scalars())
    assert {"products", "product_images", "inventory"} <= tables_in_db


def test_product_insert_and_inventory_relation():
    """3. products 可以插入测试数据；4. inventory 可以关联 products。

    业务校验：同 SKU 售价固定，但每只娃娃的回收成本可以不同。
    """
    _cleanup()
    with SessionLocal() as db:
        # 插入一条 SKU：S001 类似物，售价 40 元
        product = Product(
            sku=TEST_SKU,
            name="测试娃娃",
            size="20cm",
            style="普通款",
            sale_price=40,
        )
        db.add(product)
        db.commit()
        db.refresh(product)

        # 同一 SKU 收三只娃娃，成本各不相同
        costs = ("18.00", "21.00", "16.00")
        for i, cost in enumerate(costs, start=1):
            db.add(
                Inventory(
                    inventory_code=f"{TEST_CODE_PREFIX}{i:06d}",
                    product_id=product.id,
                    recovery_cost=Decimal(cost),
                )
            )
        db.commit()

        # 校验 SKU：售价固定、默认状态 active
        saved_product = db.execute(
            select(Product).where(Product.sku == TEST_SKU)
        ).scalar_one()
        assert saved_product.sale_price == 40
        assert saved_product.status == "active"

        # 校验库存：一只娃娃一条记录，成本为 DECIMAL 类型且各不相同
        rows = db.execute(
            select(Inventory)
            .where(Inventory.product_id == product.id)
            .order_by(Inventory.id)
        ).scalars().all()
        assert [r.inventory_code for r in rows] == [
            f"{TEST_CODE_PREFIX}{i:06d}" for i in (1, 2, 3)
        ]
        assert [r.recovery_cost for r in rows] == [Decimal(c) for c in costs]
        assert all(r.status == "in_stock" for r in rows)
        assert all(r.barcode is None for r in rows)  # 条码第1阶段允许为空

        # 校验关联：inventory.product_id 正确指向 products.id
        assert all(r.product_id == saved_product.id for r in rows)
        assert all(inv.product.sku == TEST_SKU for inv in rows)  # ORM 关系可用
