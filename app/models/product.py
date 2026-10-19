"""Product 模型：商品款式/SKU 主档（products 表）。"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Product(Base):
    """商品款式/SKU 主档。

    一个 sku 代表一种具体款式（名称 + 尺寸 + 款式共同确定），
    sku 一旦确定，售价 sale_price 就是固定的，与单只实物的回收成本无关。

    注意：本表不保存任何一只娃娃的实际回收成本，实际回收成本在 inventory 表中。
    """

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # SKU 编号，唯一，如 S001（S001=星黛露20cm普通款，S002=星黛露20cm特别款）
    sku: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, comment="SKU 编号，唯一，如 S001"
    )
    # 商品名称，如：星黛露
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="商品名称，如：星黛露")
    # 尺寸，如：20cm
    size: Mapped[str] = mapped_column(String(32), nullable=False, comment="尺寸，如：20cm")
    # 款式，如：普通款 / 特别款
    style: Mapped[str] = mapped_column(String(32), nullable=False, comment="款式，如：普通款/特别款")
    # 固定售价（元）。所有娃娃售价都是整数，所以用 Integer
    sale_price: Mapped[int] = mapped_column(Integer, nullable=False, comment="固定售价（元），整数")
    # 状态：active=在售 / inactive=停用
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="active",
        server_default="active",
        comment="状态：active=在售, inactive=停用",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )

    # 一个 SKU 有多张识别参考图片、多只库存娃娃
    images: Mapped[list["ProductImage"]] = relationship(back_populates="product")  # noqa: F821
    inventories: Mapped[list["Inventory"]] = relationship(back_populates="product")  # noqa: F821

    @property
    def image_count(self) -> int:
        """该 SKU 已有的参考图片数量。"""
        return len(self.images) if self.images is not None else 0
