"""视觉识别 MVP 测试。

原则：生产代码保留真实 CLIP 模型实现；测试中不下载/加载真实模型，
通过直接写入伪造 embedding 和 monkeypatch 查询向量化函数来测试业务逻辑。
"""

import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.core.database import SessionLocal
from app.main import app
from app.models.inventory import Inventory
from app.models.product import Product
from app.models.product_image import ProductImage
from app.services.vision import embedding as vision_embedding
from app.services.vision.matcher import cosine_similarity, match_query_embedding

client = TestClient(app)

SKU_PREFIX = "TEST-VIS-"
DIM = 8

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf"
    b"\xc0\xf0\x1f\x00\x04\xff\x01\xfe\xa5\xea\xa0\x82\x00\x00\x00\x00IEND"
    b"\xaeB`\x82"
)


def _vec(i: int) -> list[float]:
    """第 i 个单位向量（DIM 维），不同 i 之间正交。"""
    v = [0.0] * DIM
    v[i] = 1.0
    return v


def _create_product(db, idx: int, status: str = "active", embeddings=None,
                    price: int = 40) -> Product:
    """创建测试 SKU，可附带若干图片（embedding 可空）。"""
    p = Product(
        sku=f"{SKU_PREFIX}{idx:03d}",
        name=f"测试娃娃{idx}",
        size="20cm",
        style="普通款",
        sale_price=price,
        status=status,
    )
    db.add(p)
    db.flush()
    for k, emb in enumerate(embeddings or []):
        db.add(ProductImage(
            product_id=p.id,
            image_path=f"products/{p.sku}/test_{k}.jpg",
            embedding=emb,
        ))
    return p


@pytest.fixture(autouse=True)
def cleanup():
    _cleanup()
    yield
    _cleanup()


def _cleanup():
    with SessionLocal() as db:
        products = db.execute(
            select(Product).where(Product.sku.like(f"{SKU_PREFIX}%"))
        ).scalars().all()
        ids = [p.id for p in products]
        if ids:
            db.execute(delete(ProductImage).where(ProductImage.product_id.in_(ids)))
            db.execute(delete(Product).where(Product.id.in_(ids)))
        db.commit()


# ---------- 1. 模块导入 ----------

def test_vision_modules_import():
    """1. vision 模块可以正常导入（不触发模型下载）。"""
    import importlib
    importlib.import_module("app.services.vision.model")
    importlib.import_module("app.services.vision.embedding")
    importlib.import_module("app.services.vision.matcher")
    importlib.import_module("app.vision.build_embeddings")


# ---------- 2/3. embedding 序列化 ----------

def test_serialize_embedding():
    """2. numpy -> JSON 可存的普通 float 列表。"""
    vec = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    data = vision_embedding.serialize_embedding(vec)
    assert isinstance(data, list)
    assert all(isinstance(x, float) for x in data)
    assert data == [1.0, 2.0, 3.0]


def test_deserialize_embedding():
    """3. JSON -> numpy.float32 数组，形状和值正确。"""
    vec = vision_embedding.deserialize_embedding([1.0, 2.0, 3.0])
    assert vec.dtype == np.float32
    assert vec.shape == (3,)
    np.testing.assert_array_equal(vec, np.array([1, 2, 3], dtype=np.float32))


# ---------- 4/5. 相似度 ----------

def test_identical_vector_similarity():
    """4. 相同向量余弦相似度为 1。"""
    q = np.array(_vec(0), dtype=np.float32)
    sims = cosine_similarity(q, q.reshape(1, -1))
    assert sims.shape == (1,)
    assert abs(float(sims[0]) - 1.0) < 1e-6


def test_different_vector_similarity():
    """5. 正交向量相似度为 0，反向向量相似度为 -1。"""
    q = np.array(_vec(0), dtype=np.float32)
    orth = np.array(_vec(1), dtype=np.float32)
    opp = -q
    sims = cosine_similarity(q, np.stack([orth, opp]))
    assert abs(float(sims[0]) - 0.0) < 1e-6
    assert abs(float(sims[1]) + 1.0) < 1e-6


# ---------- 6/7/8. matcher 聚合、过滤、容错 ----------

def test_sku_multiple_images_aggregate_to_one_candidate():
    """6. 一个 SKU 多张图片必须聚合成一个候选，相似度取 max。"""
    with SessionLocal() as db:
        # SKU A 有两张图：一张与查询完全一致，另一张正交
        p = _create_product(db, 1, embeddings=[_vec(0), _vec(1)])
        _create_product(db, 2, embeddings=[_vec(2)])
        db.commit()
        pid = p.id

        cands = match_query_embedding(np.array(_vec(0), dtype=np.float32), db)
        # 两个 SKU -> 两个候选（而不是三张图片三个候选）
        assert len(cands) == 2
        assert [c.sku for c in cands] == [f"{SKU_PREFIX}001", f"{SKU_PREFIX}002"]
        # SKU A 取两张图的最大相似度 = 1.0
        assert abs(cands[0].similarity - 1.0) < 1e-6
        assert cands[0].reference_image.endswith("test_0.jpg")
        assert cands[0].sale_price == 40


def test_inactive_sku_excluded():
    """7. inactive SKU 不进入候选。"""
    with SessionLocal() as db:
        _create_product(db, 1, status="active", embeddings=[_vec(0)])
        _create_product(db, 2, status="inactive", embeddings=[_vec(0)])
        db.commit()

        cands = match_query_embedding(np.array(_vec(0), dtype=np.float32), db)
        skus = [c.sku for c in cands]
        assert f"{SKU_PREFIX}001" in skus
        assert f"{SKU_PREFIX}002" not in skus


def test_sku_without_embedding_skipped():
    """8. 没有 embedding 的 SKU 被跳过，不导致崩溃。"""
    with SessionLocal() as db:
        _create_product(db, 1, embeddings=[_vec(0)])  # 有 embedding
        _create_product(db, 2, embeddings=[])        # 一张图都没有
        p3 = _create_product(db, 3, embeddings=[])
        db.add(ProductImage(product_id=p3.id, image_path="products/x.jpg", embedding=None))
        db.commit()

        cands = match_query_embedding(np.array(_vec(0), dtype=np.float32), db)
        assert [c.sku for c in cands] == [f"{SKU_PREFIX}001"]


def test_dimension_mismatch_skipped():
    """附加：embedding 维度与当前模型不一致的 SKU（如换模型后的旧库）被跳过。"""
    with SessionLocal() as db:
        _create_product(db, 1, embeddings=[_vec(0)])  # 8 维，与查询一致
        _create_product(db, 2, embeddings=[[1.0, 0.0, 0.0, 0.0]])  # 4 维旧 embedding
        db.commit()

        cands = match_query_embedding(np.array(_vec(0), dtype=np.float32), db)
        assert [c.sku for c in cands] == [f"{SKU_PREFIX}001"]


# ---------- 9-15. API 与页面 ----------

def test_match_api_returns_all_active_skus_sorted(monkeypatch):
    """9-12. API 正常处理图片：返回所有 active SKU（非 Top5）、倒序、含售价。"""
    with SessionLocal() as db:
        # 6 个 active SKU，每个一个“方向”；另加 1 个 inactive 干扰
        for i in range(DIM):
            _create_product(db, i + 1, embeddings=[_vec(i)], price=100 + i)
        _create_product(db, 99, status="inactive", embeddings=[_vec(0)])
        db.commit()

    # 查询向量 = 第 5 个方向（idx=4），期望对应 SKU 排第一
    query = np.array(_vec(4), dtype=np.float32)
    monkeypatch.setattr(vision_embedding, "embed_bytes", lambda data: query)

    resp = client.post(
        "/vision/match",
        files={"file": ("q.png", io.BytesIO(PNG_BYTES), "image/png")},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # 10. 返回全部测试 SKU（8个），而不是只返回 5 个；inactive 不出现
    cands = only_test_skus(data["candidates"])
    assert len(cands) == DIM
    # active 之外：真实业务的 inactive SKU 同样不出现在完整候选里
    all_skus = [c["sku"] for c in data["candidates"]]
    assert f"{SKU_PREFIX}099" not in all_skus
    # 全部 active SKU（含本用例之外）都应可被人工选择，且 inactive 一律排除
    assert len(all_skus) >= DIM

    # 11. 按 similarity 降序
    sims = [c["similarity"] for c in cands]
    assert sims == sorted(sims, reverse=True)
    assert cands[0]["sku"] == f"{SKU_PREFIX}005"
    assert abs(cands[0]["similarity"] - 1.0) < 1e-6

    # 12. 包含 sale_price 等字段
    first = cands[0]
    assert set(["sku", "name", "size", "style", "sale_price", "similarity",
                "reference_image"]) <= set(first.keys())
    assert first["sale_price"] == 104


def test_match_does_not_create_inventory_or_autoselect(monkeypatch):
    """14/15. 匹配阶段不自动选择、不创建 inventory。"""
    with SessionLocal() as db:
        _create_product(db, 1, embeddings=[_vec(0)])
        db.commit()
    before = client_get_inventory_count()

    monkeypatch.setattr(
        vision_embedding, "embed_bytes",
        lambda data: np.array(_vec(0), dtype=np.float32),
    )
    resp = client.post(
        "/vision/match",
        files={"file": ("q.png", io.BytesIO(PNG_BYTES), "image/png")},
    )
    assert resp.status_code == 200
    body = resp.json()
    # 返回的是候选列表，没有任何“已确认/已选择”的自动决策字段
    assert "selected" not in body and "confirmed" not in body and "inventory_id" not in body
    assert client_get_inventory_count() == before


def client_get_inventory_count() -> int:
    with SessionLocal() as db:
        return int(db.execute(select(func.count()).select_from(Inventory)).scalar())


def only_test_skus(cands: list) -> list:
    """从候选里筛出本用例自己创建的 SKU。

    数据库是共享的开发库（存在 S001 等真实业务 SKU），第5阶段起 /vision/match
    会返回【全部】active SKU，因此断言必须只看本用例创建的这批，避免受外部数据影响。
    """
    return [c for c in cands if c["sku"].startswith(SKU_PREFIX)]


def test_match_without_any_embedding_gives_hint(monkeypatch):
    """所有 active SKU 都没有 embedding 时，返回明确的建库提示。

    开发库里可能存在其它带 embedding 的业务 SKU，这里把 has_any_embedding
    强制为 False，精确复现「图库整体未建」的场景。
    """
    with SessionLocal() as db:
        _create_product(db, 1, embeddings=[])
        db.commit()
    monkeypatch.setattr(
        vision_embedding, "embed_bytes",
        lambda data: np.array(_vec(0), dtype=np.float32),
    )
    monkeypatch.setattr("app.api.vision.has_any_embedding", lambda db: False)
    resp = client.post(
        "/vision/match",
        files={"file": ("q.png", io.BytesIO(PNG_BYTES), "image/png")},
    )
    assert resp.status_code == 400
    assert "build_embeddings" in resp.json()["detail"]


def test_match_rejects_non_image(monkeypatch):
    """附加：非图片文件直接拒绝。"""
    with SessionLocal() as db:
        _create_product(db, 1, embeddings=[_vec(0)])
        db.commit()
    resp = client.post(
        "/vision/match",
        files={"file": ("fake.png", io.BytesIO(b"not an image"), "image/png")},
    )
    assert resp.status_code == 400


def test_vision_page_has_other_and_no_autoselect():
    """13. 前端必须存在“其他”选项，且初始状态不自动选中任何候选。"""
    resp = client.get("/vision")
    assert resp.status_code == 200
    html = resp.text
    assert "其他" in html
    assert "选择这个款式" in html
    # 初始没有任何候选被选中
    assert 'class="cand selected"' not in html
    assert "chooseOther" in html
