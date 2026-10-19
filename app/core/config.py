"""应用配置。

所有敏感信息（数据库密码等）一律从项目根目录的 .env 读取，
不允许写死在代码里。
"""

from functools import lru_cache
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # MySQL 连接信息（对应 .env 中的同名键）
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = ""
    DB_NAME: str = "doll_system"
    DB_CHARSET: str = "utf8mb4"

    # 图片上传根目录（相对项目根目录）
    UPLOAD_DIR: str = "uploads"

    # ===== 视觉识别配置 =====
    # 模型名称与权重来源（open_clip 支持的模型，如 ViT-B-32 / ViT-B-16）
    VISION_MODEL_NAME: str = "ViT-B-32"
    VISION_PRETRAINED: str = "openai"
    # 设备选择：auto=有 CUDA 用 GPU，否则 CPU；也可强制 cpu / cuda
    VISION_DEVICE: str = "auto"
    # 识别查询图片大小上限（MB）
    VISION_MAX_IMAGE_MB: int = 10

    @property
    def database_url(self) -> str:
        """SQLAlchemy 连接串，密码做 URL 转义以兼容特殊字符。"""
        return (
            f"mysql+pymysql://{self.DB_USER}:{quote_plus(self.DB_PASSWORD)}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset={self.DB_CHARSET}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
