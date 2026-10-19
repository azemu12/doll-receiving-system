"""库存（单只娃娃）的 Pydantic 校验模型。

铁律：请求模型中【没有】sale_price 字段 —— 售价只由 SKU 主档
products.sale_price 决定，客户端无权传入、更无权修改某一只娃娃的售价。
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class InventoryCreate(BaseModel):
    """创建单只库存（收货登记）。

    - product_id 或 sku 二选一，至少提供一个；
    - recovery_cost：该只娃娃实际回收成本（元），Decimal，>=0，最多两位小数
      （绝不用 float 存金额，Pydantic 会把 JSON 数字按字符串精度转为 Decimal）；
    - image_path：该只娃娃实拍图片路径，可选。
    """

    product_id: Optional[int] = Field(None, description="商品ID（与 sku 二选一）")
    sku: Optional[str] = Field(None, min_length=1, max_length=32,
                               description="SKU编号（与 product_id 二选一）")
    recovery_cost: Decimal = Field(
        ..., ge=0, max_digits=10, decimal_places=2,
        description="该只娃娃实际回收成本（元），>=0，最多两位小数",
    )
    image_path: Optional[str] = Field(None, max_length=255,
                                      description="该只娃娃实拍图片路径（可选）")

    @model_validator(mode="after")
    def check_product_ref(self):
        """product_id 与 sku 至少提供一个。"""
        if self.product_id is None and not self.sku:
            raise ValueError("必须提供 product_id 或 sku 之一")
        return self


class InventoryResponse(BaseModel):
    """入库结果 / 库存信息。

    sale_price 来自关联的 products 主档（只读展示），不是 inventory 自己的字段。
    """

    inventory_code: str
    sku: str
    name: str
    size: str
    style: str
    recovery_cost: Decimal
    sale_price: int  # 来自 products.sale_price，客户端不可修改
    barcode: Optional[str]  # 成本含小数等超出条码规则时为 None
    status: str
    received_at: datetime

    model_config = ConfigDict(from_attributes=True)
