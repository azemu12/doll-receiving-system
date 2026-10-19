"""集中导入所有模型，确保 Base.metadata 注册完整。"""

from app.models.product import Product
from app.models.product_image import ProductImage
from app.models.inventory import Inventory

__all__ = ["Product", "ProductImage", "Inventory"]
