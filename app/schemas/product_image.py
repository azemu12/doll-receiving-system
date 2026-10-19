"""商品图片的 Pydantic 模型。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ProductImageResponse(BaseModel):
    id: int
    product_id: int
    image_path: str
    image_url: str = ""
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
