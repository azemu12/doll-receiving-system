"""ProductImage 模型：SKU 视觉识别参考图片（product_images 表）。"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ProductImage(Base):
    """SKU 对应的视觉识别参考图片。

    一个 SKU 可以有多张图片，供后续 AI 识别“这只娃娃属于哪个 SKU”使用。
    embedding 为图片特征向量，第1阶段未实现视觉识别，允许为 NULL。
    """

    __tablename__ = "product_images"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 所属 SKU，关联 products.id
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"), nullable=False, comment="所属 SKU，关联 products.id"
    )
    # 图片存储路径
    image_path: Mapped[str] = mapped_column(String(255), nullable=False, comment="图片存储路径")
    # 特征向量。第1阶段未实现视觉识别，允许为空
    embedding: Mapped[list | None] = mapped_column(
        JSON, nullable=True, comment="图片特征向量，第1阶段允许为空"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )

    product: Mapped["Product"] = relationship(back_populates="images")  # noqa: F821

    @property
    def image_url(self) -> str:
        """前端可访问的图片 URL（由 FastAPI /uploads 静态目录提供）。"""
        return f"/uploads/{self.image_path}"
