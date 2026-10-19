"""商品管理后台页面（Jinja2）。

只提供 SKU 与图片的管理页面，不涉及 AI/摄像头/条码/销售。
"""

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.models.product import Product

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/products")
def admin_products(request: Request, db: Session = Depends(get_db)):
    """商品列表页：展示所有 SKU，包含新增、编辑、删除入口。"""
    products = db.execute(
        select(Product).options(selectinload(Product.images)).order_by(Product.id)
    ).scalars().all()
    return templates.TemplateResponse(
        request,
        "admin/products.html",
        {"products": products},
    )


@router.get("/products/{product_id}")
def admin_product_detail(
    product_id: int, request: Request, db: Session = Depends(get_db)
):
    """商品详情页：编辑商品信息 + 上传/删除参考图片。"""
    product = db.execute(
        select(Product)
        .options(selectinload(Product.images))
        .where(Product.id == product_id)
    ).scalar_one_or_none()
    if product is None:
        return templates.TemplateResponse(
            request,
            "admin/404.html",
            {"product_id": product_id},
            status_code=404,
        )
    return templates.TemplateResponse(
        request,
        "admin/product_detail.html",
        {"product": product},
    )
