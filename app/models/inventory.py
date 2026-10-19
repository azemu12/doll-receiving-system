"""Inventory 模型：单只娃娃库存记录（inventory 表）。

每一只实际收到的娃娃都单独建立一条记录：
- 同一个 SKU 的不同实物，实际回收成本可以不同；
- 条码根据“固定售价 + 该只娃娃实际回收成本”生成，属于后续阶段，允许为空。
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Inventory(Base):
    """一只娃娃 = 一条 inventory 记录。

    示例（同 SKU 售价固定 40 元，但三只成本各不相同）：
        D000001 | S001 | 18
        D000002 | S001 | 21
        D000003 | S001 | 16
    """

    __tablename__ = "inventory"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 单只娃娃唯一编号，如 D000001
    inventory_code: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, comment="单只娃娃唯一编号，如 D000001"
    )
    # 所属 SKU，关联 products.id
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"), nullable=False, comment="所属 SKU，关联 products.id"
    )
    # 该只娃娃的实际回收成本（元）。用 DECIMAL，绝不用 float 存金额
    recovery_cost: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        comment="该只娃娃实际回收成本（元），同SKU每只可不同",
    )
    # 条码内容，根据固定售价 + 实际回收成本生成，后续阶段实现，允许为空
    barcode: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="条码内容，后续阶段生成，允许为空"
    )
    # 该只娃娃实拍图片路径，允许为空
    image_path: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="该只娃娃实拍图片路径，允许为空"
    )
    # 状态：in_stock=在库 / sold=已售（后续阶段可扩展）
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="in_stock",
        server_default="in_stock",
        comment="状态：in_stock=在库, sold=已售",
    )
    # 收货时间
    received_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="收货时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )

    product: Mapped["Product"] = relationship(back_populates="inventories")  # noqa: F821
