"""测试数据种子脚本。

用途：插入一批用于开发/测试的 SKU 数据，不写入正式业务逻辑。

运行：
    python -m app.seed

已存在的 SKU 会跳过，可重复执行。
"""

from sqlalchemy import select

from app.core.database import SessionLocal, init_db
from app.models.product import Product

# 测试数据：sku, name, size, style, sale_price
SEED_PRODUCTS = [
    ("S001", "星黛露", "20cm", "普通款", 40),
    ("S002", "星黛露", "20cm", "特别款", 50),
    ("S003", "三岁", "20cm", "普通款", 30),
    ("S004", "氧氧", "20cm", "普通款", 35),
    ("S005", "洛奇奇", "20cm", "普通款", 45),
]


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        for sku, name, size, style, sale_price in SEED_PRODUCTS:
            exists = db.execute(
                select(Product).where(Product.sku == sku)
            ).scalar_one_or_none()
            if exists:
                print(f"[跳过] SKU {sku} 已存在")
                continue
            db.add(
                Product(
                    sku=sku,
                    name=name,
                    size=size,
                    style=style,
                    sale_price=sale_price,
                    status="active",
                )
            )
            print(f"[新增] SKU {sku} | {name} {size} {style} | ¥{sale_price}")
        db.commit()
        print("\n完成。可在 http://127.0.0.1:8000/admin/products 查看。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
