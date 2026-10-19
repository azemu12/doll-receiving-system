"""FastAPI 入口。

启动时自动创建数据表（已存在则跳过）并确保图片上传目录存在。
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.admin.products import router as admin_router
from app.api.inventory import router as inventory_router
from app.api.products import router as products_router
from app.api.vision import router as vision_router
from app.core.config import settings
from app.core.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 应用启动：确保三张表存在 + 图片上传目录存在
    init_db()
    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="毛绒娃娃收货系统", version="0.4.0", lifespan=lifespan)

# 确保图片上传目录存在（StaticFiles 挂载时即检查目录）
Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)

# 商品 SKU + 图片 API
app.include_router(products_router)
# 视觉识别 API + 识别页面
app.include_router(vision_router)
# 收货登记 API + /receive、/inventory 页面
app.include_router(inventory_router)
# 管理后台页面
app.include_router(admin_router)
# 上传图片静态访问
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")


@app.get("/health")
def health_check():
    """健康检查。"""
    return {"status": "ok"}
