"""商品 SKU 的 Pydantic 校验模型。"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductCreate(BaseModel):
    """创建商品：sku 必须唯一，sale_price 必须是整数。"""

    sku: str = Field(..., min_length=1, max_length=32, description="SKU编号，唯一")
    name: str = Field(..., min_length=1, max_length=64, description="商品名称")
    size: str = Field(..., min_length=1, max_length=32, description="尺寸，如 20cm")
    style: str = Field(..., min_length=1, max_length=32, description="款式，如 普通款")
    sale_price: int = Field(..., ge=0, description="固定售价（元），必须是整数")
    status: str = Field("active", description="状态：active=在售, inactive=停用")

    @field_validator("sale_price")
    @classmethod
    def sale_price_must_be_int(cls, v):
        # bool 是 int 的子类，需排除；float 也不允许
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError("sale_price 必须是整数")
        return v

    @field_validator("status")
    @classmethod
    def status_valid(cls, v):
        if v not in ("active", "inactive"):
            raise ValueError("status 只能是 active 或 inactive")
        return v


class ProductUpdate(BaseModel):
    """修改商品：sku 不允许修改（避免历史数据关系混乱）。"""

    name: Optional[str] = Field(None, min_length=1, max_length=64)
    size: Optional[str] = Field(None, min_length=1, max_length=32)
    style: Optional[str] = Field(None, min_length=1, max_length=32)
    sale_price: Optional[int] = Field(None, ge=0)
    status: Optional[str] = Field(None)

    @field_validator("sale_price")
    @classmethod
    def sale_price_must_be_int(cls, v):
        if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
            raise ValueError("sale_price 必须是整数")
        return v

    @field_validator("status")
    @classmethod
    def status_valid(cls, v):
        if v is not None and v not in ("active", "inactive"):
            raise ValueError("status 只能是 active 或 inactive")
        return v


class ProductResponse(BaseModel):
    id: int
    sku: str
    name: str
    size: str
    style: str
    sale_price: int
    status: str
    image_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
