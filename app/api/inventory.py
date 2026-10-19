"""收货登记 + 单只库存 API 与页面。

业务流程（本阶段只做这一段）：
    人工确认SKU -> 输入实际回收成本 -> 创建单只库存
    -> 售价自动取 products.sale_price -> 生成业务条码 -> 返回结果

铁律：
- sale_price 只来自 products 表，客户端传入的一律无效（请求模型里根本没有该字段）；
- 每一只娃娃单独一条 inventory 记录，同 SKU 不同成本各自成行；
- inventory_code 由数据库自增 id 派生（D000001...），并发安全、稳定递增，
  不用 COUNT(*)+1（删除/并发会冲突）；
- barcode 在创建时生成一次并落库，之后一律读库原样返回，绝不重新生成。
"""

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.models.inventory import Inventory
from app.models.product import Product
from app.schemas.inventory import InventoryCreate, InventoryResponse
from app.services.barcode import BarcodeError, generate_barcode

logger = logging.getLogger(__name__)

router = APIRouter(tags=["inventory"])
templates = Jinja2Templates(directory="app/templates")


def _to_response(inv: Inventory, product: Product) -> InventoryResponse:
    """组装响应：售价等 SKU 信息一律从 products 主档读取。"""
    return InventoryResponse(
        inventory_code=inv.inventory_code,
        sku=product.sku,
        name=product.name,
        size=product.size,
        style=product.style,
        recovery_cost=inv.recovery_cost,
        sale_price=product.sale_price,
        barcode=inv.barcode,
        status=inv.status,
        received_at=inv.received_at,
    )


# ===================== 收货登记 API =====================


@router.post("/inventory", response_model=InventoryResponse,
             status_code=status.HTTP_201_CREATED)
def create_inventory(payload: InventoryCreate, db: Session = Depends(get_db)):
    """创建单只库存（收货入库）。

    1. 按 product_id 或 sku 定位商品；2. 必须 active；3. 售价读 products；
    4. 自动生成唯一 inventory_code；5. 自动生成 barcode；6. 落库并返回。
    """
    # 1. 定位 SKU
    if payload.product_id is not None:
        product = db.execute(
            select(Product).where(Product.id == payload.product_id)
        ).scalar_one_or_none()
    else:
        product = db.execute(
            select(Product).where(Product.sku == payload.sku)
        ).scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="SKU 不存在，无法入库")
    # 2. 必须 active
    if product.status != "active":
        raise HTTPException(
            status_code=400, detail=f"SKU {product.sku} 已停用（inactive），不能入库"
        )

    # 3. 生成条码。成本带小数等超出当前条码规则时不阻断入库：
    #    barcode 置 None 并记录日志（条码规则见 app/services/barcode.py 说明）
    barcode: Optional[str] = None
    try:
        barcode = generate_barcode(product.sale_price, payload.recovery_cost)
    except BarcodeError as exc:
        logger.warning(
            "SKU %s 成本 %s 超出当前条码规则，本只库存不生成条码: %s",
            product.sku, payload.recovery_cost, exc,
        )

    # 4. 创建记录：先用临时编号占位，flush 拿到自增 id 后派生正式编号。
    #    MySQL 自增 id 本身并发安全、稳定递增，因此 D{id:06d} 唯一可靠。
    inv = Inventory(
        # 占位临时编号（<=32字符），保证 unique 约束下 flush 成功；随后立即改为正式编号
        inventory_code=f"TMP-{uuid.uuid4().hex[:28]}",
        product_id=product.id,
        recovery_cost=payload.recovery_cost,
        barcode=barcode,
        image_path=payload.image_path,
        status="in_stock",
    )
    db.add(inv)
    db.flush()  # 拿到自增 id（此时事务未提交，编号仍在本事务内）
    inv.inventory_code = f"D{inv.id:06d}"
    db.commit()
    db.refresh(inv)

    logger.info(
        "入库成功: %s SKU=%s 成本=%s 售价=%s 条码=%s",
        inv.inventory_code, product.sku, inv.recovery_cost,
        product.sale_price, inv.barcode,
    )
    return _to_response(inv, product)


# ===================== 收货登记页面 =====================


@router.get("/receive")
def receive_page(
    request: Request,
    product_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """收货登记页。

    两种入口：
    1. /vision 人工确认后跳转 /receive?product_id=xxx（自动填入 SKU 信息）；
    2. 直接打开本页，手动下拉选择 SKU。
    """
    products = db.execute(
        select(Product).where(Product.status == "active").order_by(Product.sku)
    ).scalars().all()
    # 传给前端的轻量 SKU 数据（含固定售价，用于展示；提交时仍由后端取售价）
    product_list = [
        {
            "id": p.id,
            "sku": p.sku,
            "name": p.name,
            "size": p.size,
            "style": p.style,
            "sale_price": p.sale_price,
        }
        for p in products
    ]
    selected_id = product_id if any(p.id == product_id for p in products) else None
    return templates.TemplateResponse(
        request,
        "receive.html",
        {"products": product_list, "selected_id": selected_id},
    )


# ===================== 库存查询页面 =====================


@router.get("/inventory")
def inventory_page(
    request: Request,
    sku: Optional[str] = None,
    name: Optional[str] = None,
    code: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """库存查询页：支持按 SKU / 商品名称 / 库存编号模糊搜索，默认收货时间倒序。"""
    stmt = (
        select(Inventory)
        .join(Inventory.product)
        .options(selectinload(Inventory.product))
    )
    if sku:
        stmt = stmt.where(Product.sku.like(f"%{sku}%"))
    if name:
        stmt = stmt.where(Product.name.like(f"%{name}%"))
    if code:
        stmt = stmt.where(Inventory.inventory_code.like(f"%{code}%"))
    # 默认按收货时间倒序（id 倒序兜底，保证同秒数据稳定）
    stmt = stmt.order_by(Inventory.received_at.desc(), Inventory.id.desc()).limit(500)

    inventories = db.execute(stmt).scalars().all()
    return templates.TemplateResponse(
        request,
        "inventory_list.html",
        {
            "inventories": inventories,
            "query": {"sku": sku or "", "name": name or "", "code": code or ""},
        },
    )
