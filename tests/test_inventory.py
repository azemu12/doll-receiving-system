"""第4阶段：收货登记 + 单只库存 + 条码生成 测试。

覆盖用户要求的全部场景：
条码生成规则、入库成功、负成本失败、Decimal 精度、两位小数、
inactive/不存在 SKU 拒绝、售价自动读取且不可篡改、编号唯一、
同 SKU 不同成本多库存、vision->receive 联动、库存查询页。
"""

import re
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.main import app
from app.models.inventory import Inventory
from app.models.product import Product
from app.services.barcode import BarcodeError, generate_barcode

TEST_SKU_PREFIX = "TEST-INV-"

client = TestClient(app)


def _cleanup():
    """清理测试数据：先删库存（外键）再删商品。"""
    with SessionLocal() as db:
        products = db.execute(
            select(Product).where(Product.sku.like(f"{TEST_SKU_PREFIX}%"))
        ).scalars().all()
        ids = [p.id for p in products]
        if ids:
            db.execute(delete(Inventory).where(Inventory.product_id.in_(ids)))
            db.execute(delete(Product).where(Product.id.in_(ids)))
        db.commit()


@pytest.fixture(autouse=True)
def cleanup():
    _cleanup()
    yield
    _cleanup()


def _make_product(suffix: str = "001", price: int = 40, status: str = "active") -> int:
    """创建测试商品，返回 product_id。"""
    resp = client.post(
        "/products",
        json={
            "sku": f"{TEST_SKU_PREFIX}{suffix}",
            "name": "星黛露",
            "size": "20cm",
            "style": "普通款",
            "sale_price": price,
            "status": status,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _receive(product_id: int, cost) -> dict:
    resp = client.post(
        "/inventory",
        json={"product_id": product_id, "recovery_cost": cost},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ==================== 条码生成器单元测试 ====================


def test_barcode_rule_40_18():
    """售价40、成本18 -> 04xx180（0/4/xx/18/0）。"""
    code = generate_barcode(40, 18)
    assert re.fullmatch(r"04\d{2}180", code), code
    assert len(code) == 7


def test_barcode_rule_50_18():
    """售价50、成本18 -> 05xx180。"""
    assert re.fullmatch(r"05\d{2}180", generate_barcode(50, 18))


def test_barcode_rule_39_18():
    """售价39、成本18 -> 03xx189（售价个位是9）。"""
    assert re.fullmatch(r"03\d{2}189", generate_barcode(39, 18))


def test_barcode_xx_is_two_digits():
    """xx 是合法的两位数字（00~99），且只出现在中间两位。"""
    for _ in range(50):
        m = re.fullmatch(r"0(\d)(\d{2})(\d{2})(\d)", generate_barcode(40, 18))
        assert m, "条码结构必须是 0+十位+xx+成本+个位"
        assert m.group(1) == "4" and m.group(3) == "18" and m.group(4) == "0"
        assert 0 <= int(m.group(2)) <= 99


def test_barcode_accepts_whole_decimal_cost():
    """整数值的 Decimal 成本可以编码（Decimal('18.00') 视为 18）。"""
    assert re.fullmatch(r"04\d{2}180", generate_barcode(40, Decimal("18.00")))


def test_barcode_rejects_fractional_cost():
    """带小数的成本（18.50）当前规则无法编码 -> BarcodeError，不擅自发明规则。"""
    with pytest.raises(BarcodeError):
        generate_barcode(40, Decimal("18.50"))


def test_barcode_rejects_out_of_range():
    """超出 0~99 的售价/成本直接报错。"""
    with pytest.raises(BarcodeError):
        generate_barcode(100, 18)
    with pytest.raises(BarcodeError):
        generate_barcode(40, 100)
    with pytest.raises(BarcodeError):
        generate_barcode(-1, 18)
    with pytest.raises(BarcodeError):
        generate_barcode(40, Decimal("-0.01"))


# ==================== POST /inventory API ====================


def test_create_inventory_success():
    """1. 创建库存成功：字段完整、编号 D 开头、条码符合规则。"""
    pid = _make_product("001", price=40)
    data = _receive(pid, "18")
    assert re.fullmatch(r"D\d{6}", data["inventory_code"])
    assert data["sku"] == f"{TEST_SKU_PREFIX}001"
    assert data["name"] == "星黛露"
    assert data["size"] == "20cm"
    assert data["style"] == "普通款"
    assert Decimal(str(data["recovery_cost"])) == Decimal("18.0")
    assert data["sale_price"] == 40
    assert re.fullmatch(r"04\d{2}180", data["barcode"])
    assert data["status"] == "in_stock"
    assert "received_at" in data


def test_create_inventory_by_sku():
    """支持用 sku（而非 product_id）入库。"""
    _make_product("002", price=50)
    resp = client.post(
        "/inventory",
        json={"sku": f"{TEST_SKU_PREFIX}002", "recovery_cost": "18"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["sku"] == f"{TEST_SKU_PREFIX}002"
    assert data["sale_price"] == 50
    assert re.fullmatch(r"05\d{2}180", data["barcode"])


def test_recovery_cost_negative_fails():
    """2. recovery_cost 为负数失败（Pydantic 校验 422）。"""
    pid = _make_product("003")
    resp = client.post(
        "/inventory", json={"product_id": pid, "recovery_cost": "-1"}
    )
    assert resp.status_code == 422


def test_recovery_cost_no_binary_float():
    """3. 成本必须按 Decimal 精确存储，不能有二进制 float 误差。"""
    pid = _make_product("004")
    data = _receive(pid, "18.1")
    with SessionLocal() as db:
        inv = db.execute(
            select(Inventory).where(Inventory.inventory_code == data["inventory_code"])
        ).scalar_one()
        # 数据库里是精确的 DECIMAL(10,2)
        assert inv.recovery_cost == Decimal("18.10")


def test_recovery_cost_two_decimals():
    """4. 支持两位小数成本（18.50）；超出条码规则时条码为空但不阻断入库。"""
    pid = _make_product("005")
    data = _receive(pid, "18.50")
    with SessionLocal() as db:
        inv = db.execute(
            select(Inventory).where(Inventory.inventory_code == data["inventory_code"])
        ).scalar_one()
        assert inv.recovery_cost == Decimal("18.50")
        assert inv.barcode is None  # 当前条码规则只能编码整数成本，条码置空
    assert data["barcode"] is None


def test_recovery_cost_too_many_decimals_fails():
    """附加：超过两位小数直接 422。"""
    pid = _make_product("006")
    resp = client.post(
        "/inventory", json={"product_id": pid, "recovery_cost": "18.555"}
    )
    assert resp.status_code == 422


def test_inactive_sku_cannot_receive():
    """5. inactive SKU 不能入库（400）。"""
    pid = _make_product("007", status="inactive")
    resp = client.post(
        "/inventory", json={"product_id": pid, "recovery_cost": "18"}
    )
    assert resp.status_code == 400


def test_nonexistent_sku_cannot_receive():
    """6. 不存在的 SKU 不能入库（404）。"""
    resp = client.post(
        "/inventory", json={"sku": f"{TEST_SKU_PREFIX}NOPE", "recovery_cost": "18"}
    )
    assert resp.status_code == 404


def test_sale_price_read_from_product():
    """7. sale_price 自动从 SKU 主档读取（售价 50 的 SKU 返回 50）。"""
    pid = _make_product("008", price=50)
    data = _receive(pid, "18")
    assert data["sale_price"] == 50


def test_sale_price_cannot_be_tampered():
    """8. 客户端传 sale_price 一律无效，售价仍以 SKU 主档为准。"""
    pid = _make_product("009", price=40)
    resp = client.post(
        "/inventory",
        json={"product_id": pid, "recovery_cost": "18", "sale_price": 999},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["sale_price"] == 40


def test_inventory_code_unique_and_format():
    """9. inventory_code 唯一、格式 D+6位数字、稳定递增。"""
    pid = _make_product("010")
    codes = [_receive(pid, "10")["inventory_code"] for _ in range(3)]
    assert all(re.fullmatch(r"D\d{6}", c) for c in codes)
    assert len(set(codes)) == 3
    nums = sorted(int(c[1:]) for c in codes)
    assert [int(c[1:]) for c in codes] == sorted(int(c[1:]) for c in codes)
    assert nums[0] > 0


def test_barcode_generated_and_stored():
    """10. 条码创建时生成一次并落库；反复读取结果稳定不变。"""
    pid = _make_product("011", price=40)
    data = _receive(pid, "18")
    assert re.fullmatch(r"04\d{2}180", data["barcode"])
    with SessionLocal() as db:
        q = select(Inventory).where(Inventory.inventory_code == data["inventory_code"])
        first = db.execute(q).scalar_one().barcode
    with SessionLocal() as db:
        q = select(Inventory).where(Inventory.inventory_code == data["inventory_code"])
        second = db.execute(q).scalar_one().barcode
    assert first == data["barcode"] == second


def test_same_sku_different_costs():
    """11. 同款同售价、不同成本：S001(40元) 三只成本 18/21/16 各自成行。"""
    pid = _make_product("012", price=40)
    d1 = _receive(pid, "18")
    d2 = _receive(pid, "21")
    d3 = _receive(pid, "16")

    codes = {d1["inventory_code"], d2["inventory_code"], d3["inventory_code"]}
    assert len(codes) == 3
    with SessionLocal() as db:
        rows = db.execute(
            select(Inventory).where(Inventory.inventory_code.in_(codes))
        ).scalars().all()
        assert len(rows) == 3
        costs = sorted(r.recovery_cost for r in rows)
        assert costs == [Decimal("16.00"), Decimal("18.00"), Decimal("21.00")]
        # 三只售价都来自同一 SKU 的固定售价 40
        for r in rows:
            assert r.product.sale_price == 40
    # API 返回层面同样验证售价恒为 40
    for d, cost in ((d1, "18"), (d2, "21"), (d3, "16")):
        assert d["sale_price"] == 40
        assert Decimal(str(d["recovery_cost"])) == Decimal(cost)


# ==================== 页面联动 ====================


def test_vision_page_links_to_receive():
    """12. /vision 确认后提供“进入收货登记”跳转（携带 product_id）。"""
    resp = client.get("/vision")
    assert resp.status_code == 200
    assert "进入收货登记" in resp.text
    assert "/receive?product_id=" in resp.text


def test_receive_page_prefills_product():
    """13a. /receive?product_id= 自动填入 SKU 信息与固定售价。"""
    pid = _make_product("013", price=40)
    resp = client.get(f"/receive?product_id={pid}")
    assert resp.status_code == 200
    assert f"{TEST_SKU_PREFIX}013" in resp.text
    assert "固定售价" in resp.text
    assert "实际回收成本" in resp.text


def test_receive_then_query_inventory_page():
    """13b/14. 收货成功后，/inventory 页面能查到该记录，支持按编号/SKU/名称搜索。"""
    pid = _make_product("014", price=40)
    data = _receive(pid, "18")

    page = client.get("/inventory")
    assert page.status_code == 200
    assert data["inventory_code"] in page.text

    by_code = client.get(f"/inventory?code={data['inventory_code']}")
    assert data["inventory_code"] in by_code.text

    by_sku = client.get(f"/inventory?sku={TEST_SKU_PREFIX}014")
    assert data["inventory_code"] in by_sku.text

    by_name = client.get("/inventory?name=星黛露")
    assert data["inventory_code"] in by_name.text

    # 搜不存在的编号则查不到该记录
    miss = client.get("/inventory?code=D999999999")
    assert data["inventory_code"] not in miss.text
