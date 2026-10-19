"""数据库核心：engine、SessionLocal、Base、建表函数。"""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,  # 取连接前先 ping，避免 MySQL 长连接失效报错
    pool_recycle=3600,
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    """所有 ORM 模型的公共基类。"""


def get_db():
    """FastAPI 依赖：每个请求一个 Session，用完自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """创建全部数据表（已存在则跳过）。需要先导入所有模型。"""
    import app.models  # noqa: F401  导入以确保模型注册到 Base.metadata

    Base.metadata.create_all(bind=engine)
