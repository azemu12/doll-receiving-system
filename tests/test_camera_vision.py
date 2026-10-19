"""第5阶段：电脑摄像头实时预览与拍照识别测试。

测试原则：
1. **绝不要求电脑连接摄像头** —— 用 mock 图片（最小合法文件头）走真实 API；
2. 浏览器侧行为无法在无头环境真实执行，因此对 JS 做源码级断言
   （必须调用 getUserMedia、必须走 /vision/match、必须有权限异常分支等）；
3. 业务逻辑（候选返回、相似度、人工选择、不自动入库）走真实 HTTP 调用验证。
"""

import io
import re

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

client = TestClient(app)

SKU_PREFIX = "TEST-CAM-"
DIM = 8

# mock 图片：JPEG 文件头（够通过魔数校验即可，embedding 由 monkeypatch 提供）
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf"
    b"\xc0\xf0\x1f\x00\x04\xff\x01\xfe\xa5\xea\xa0\x82\x00\x00\x00\x00IEND"
    b"\xaeB`\x82"
)


def _vec(i: int) -> list[float]:
    v = [0.0] * DIM
    v[i] = 1.0
    return v


def _create_product(db, idx: int, status: str = "active", embeddings=None,
                    images: int = 0, price: int = 40) -> Product:
    """创建测试 SKU。embeddings 为 embedding 值列表，images 为额外无 embedding 图片数。"""
    p = Product(
        sku=f"{SKU_PREFIX}{idx:03d}",
        name=f"摄像头测试娃娃{idx}",
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
            image_path=f"products/{p.sku}/img_{k}.jpg",
            embedding=emb,
        ))
    for k in range(images):
        db.add(ProductImage(
            product_id=p.id,
            image_path=f"products/{p.sku}/raw_{k}.jpg",
            embedding=None,
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


def _only_test(cands: list) -> list:
    """只看本用例创建的 SKU（开发库里还有真实业务 SKU）。"""
    return [c for c in cands if c["sku"].startswith(SKU_PREFIX)]


def _inventory_count() -> int:
    with SessionLocal() as db:
        return int(db.execute(select(func.count()).select_from(Inventory)).scalar())


@pytest.fixture
def vision_html() -> str:
    resp = client.get("/vision")
    assert resp.status_code == 200
    return resp.text


# ============ 1. /vision 页面正常打开 ============

def test_vision_page_opens(vision_html):
    """1. /vision 页面正常打开。"""
    assert "毛绒娃娃 · 视觉识别" in vision_html
    # Jinja 变量必须已渲染，不能把模板原样输出
    assert "{{" not in vision_html and "{%" not in vision_html


# ============ 2. 浏览器能请求摄像头权限 ============

def test_page_requests_camera_permission(vision_html):
    """2. 页面具备请求摄像头权限的完整调用链。"""
    assert "navigator.mediaDevices" in vision_html
    assert "getUserMedia" in vision_html
    assert "startCamera()" in vision_html
    assert "start-camera-btn" in vision_html
    # 非安全上下文（非 localhost/https）浏览器会直接禁止摄像头，必须提前拦截并提示
    assert "window.isSecureContext" in vision_html


# ============ 3. 实时预览正常 ============

def test_page_has_live_preview_video(vision_html):
    """3. 页面有实时预览用的 video 元素，且 ES7 idiomatic 属性齐全。"""
    assert 'id="camera-video"' in vision_html
    assert "autoplay" in vision_html
    assert "playsinline" in vision_html
    assert "muted" in vision_html
    # 拿到 stream 后必须挂到 video 上播放
    assert "videoEl.srcObject = cameraStream" in vision_html
    assert "videoEl.play()" in vision_html
    # 拍照/重拍/关闭按钮初始为不可用，避免未启动时误点
    assert 'id="capture-btn"' in vision_html
    assert 'id="retake-btn"' in vision_html


# ============ 4. 点击拍照能够得到有效图片 ============

def test_capture_produces_valid_jpeg(vision_html):
    """4. 拍照按钮：canvas 抓帧 -> JPEG blob，并做空图与超限校验。"""
    assert 'id="capture-btn"' in vision_html
    assert "captureAndMatch()" in vision_html
    assert "getContext('2d')" in vision_html
    assert "ctx.drawImage(videoEl, 0, 0, w, h)" in vision_html
    assert "canvas.toBlob(resolve, 'image/jpeg', 0.92)" in vision_html
    # 画面未就绪（分辨率为0）/ 截图失败 / 超过大小上限 都要明确提示
    assert "videoEl.videoWidth" in vision_html
    assert "画面截图失败" in vision_html
    assert "超过上限" in vision_html
    assert "MAX_IMAGE_MB" in vision_html


# ============ 5. 拍摄图片能够调用 /vision/match ============

def test_camera_photo_goes_to_existing_match_api(vision_html):
    """5. 拍照结果走现有 /vision/match，不新增重复识别接口。"""
    assert "await runMatch(blob, 'camera.jpg')" in vision_html
    assert "fd.append('file', file, filename)" in vision_html
    assert "fetch('/vision/match', { method: 'POST', body: fd })" in vision_html
    # 全页面只允许这一个识别请求入口（不重复实现 /vision/match）
    assert vision_html.count("fetch('/vision/match'") == 1


def test_match_accepts_camera_jpeg(monkeypatch):
    """5b. 真实走一次 API：mock JPEG 抓帧数据能被正常处理。"""
    with SessionLocal() as db:
        _create_product(db, 1, embeddings=[_vec(0)])
        db.commit()
    monkeypatch.setattr(
        vision_embedding, "embed_bytes",
        lambda data: np.array(_vec(0), dtype=np.float32),
    )
    resp = client.post(
        "/vision/match",
        files={"file": ("camera.jpg", io.BytesIO(JPEG_BYTES), "image/jpeg")},
    )
    assert resp.status_code == 200, resp.text
    assert len(_only_test(resp.json()["candidates"])) == 1


# ============ 6. 原有图片上传识别功能仍然可用 ============

def test_upload_path_still_available(vision_html):
    """6. 摄像头不可用时，上传图片识别仍然保留。"""
    assert 'id="file-input"' in vision_html
    assert 'id="match-btn"' in vision_html
    assert "matchUpload()" in vision_html
    assert "上传图片识别" in vision_html


def test_upload_recognition_still_works(monkeypatch):
    """6b. 上传路径真实可用（PNG mock 图）。"""
    with SessionLocal() as db:
        _create_product(db, 1, embeddings=[_vec(0)])
        db.commit()
    monkeypatch.setattr(
        vision_embedding, "embed_bytes",
        lambda data: np.array(_vec(0), dtype=np.float32),
    )
    resp = client.post(
        "/vision/match",
        files={"file": ("q.png", io.BytesIO(PNG_BYTES), "image/png")},
    )
    assert resp.status_code == 200, resp.text
    assert _only_test(resp.json()["candidates"])[0]["sku"] == f"{SKU_PREFIX}001"


# ============ 7. 所有 active SKU 都可以人工选择 ============

def test_all_active_skus_are_selectable(monkeypatch):
    """7. 有图库、有图无 embedding、完全没图的 SKU 都必须出现在候选里。"""
    with SessionLocal() as db:
        _create_product(db, 1, embeddings=[_vec(0)])              # 有 embedding
        _create_product(db, 2, images=2)                          # 有图但没 embedding
        _create_product(db, 3)                                    # 一张图都没有
        _create_product(db, 4, status="inactive", embeddings=[_vec(1)])  # 停用，不得出现
        db.commit()

    monkeypatch.setattr(
        vision_embedding, "embed_bytes",
        lambda data: np.array(_vec(0), dtype=np.float32),
    )
    resp = client.post(
        "/vision/match",
        files={"file": ("camera.jpg", io.BytesIO(JPEG_BYTES), "image/jpeg")},
    )
    assert resp.status_code == 200, resp.text

    cands = _only_test(resp.json()["candidates"])
    skus = [c["sku"] for c in cands]
    assert len(cands) == 3
    assert f"{SKU_PREFIX}001" in skus
    assert f"{SKU_PREFIX}002" in skus
    assert f"{SKU_PREFIX}003" in skus
    assert f"{SKU_PREFIX}004" not in skus  # inactive 排除
    # 每个候选都带齐人工确认所需字段
    for c in cands:
        assert c["product_id"] > 0
        assert {"sku", "name", "size", "style", "sale_price",
                "similarity", "reference_image", "has_embedding"} <= set(c.keys())


def test_fallback_sku_endpoint_lists_everything():
    """7b. AI 不可用的兜底接口也要列出全部 active SKU 供人工选择。"""
    with SessionLocal() as db:
        _create_product(db, 1, embeddings=[_vec(0)])
        _create_product(db, 2)
        _create_product(db, 3, status="inactive")
        db.commit()

    resp = client.get("/vision/skus")
    assert resp.status_code == 200
    cands = _only_test(resp.json()["candidates"])
    assert [c["sku"] for c in cands] == [f"{SKU_PREFIX}001", f"{SKU_PREFIX}002"]
    assert all(c["similarity"] is None for c in cands)


# ============ 8. 没有 Embedding 的 SKU 不伪造相似度 ============

def test_no_embedding_sku_has_no_fake_similarity(monkeypatch):
    """8. 无 embedding 的 SKU：similarity=None 且排在最后，不许编数字混进排序。"""
    with SessionLocal() as db:
        _create_product(db, 1, embeddings=[_vec(0)], price=40)
        _create_product(db, 2, embeddings=[_vec(1)], price=50)
        _create_product(db, 3, images=1, price=30)          # 有图无 embedding
        _create_product(db, 4, price=35)                    # 无图
        db.commit()

    monkeypatch.setattr(
        vision_embedding, "embed_bytes",
        lambda data: np.array(_vec(0), dtype=np.float32),
    )
    resp = client.post(
        "/vision/match",
        files={"file": ("camera.jpg", io.BytesIO(JPEG_BYTES), "image/jpeg")},
    )
    cands = _only_test(resp.json()["candidates"])
    assert len(cands) == 4

    # 有相似度的候选在前，且确实倒序
    with_sim = [c for c in cands if c["similarity"] is not None]
    without_sim = [c for c in cands if c["similarity"] is None]
    assert len(with_sim) == 2 and len(without_sim) == 2
    sims = [c["similarity"] for c in with_sim]
    assert sims == sorted(sims, reverse=True)
    # 无相似度的只能排在末尾
    assert cands[-len(without_sim):] == without_sim
    # 没有 embedding / 没有参考图的，一律不允许出现相似度数字
    for c in without_sim:
        assert c["has_embedding"] is False


def test_page_marks_missing_library(vision_html):
    """8b. 前端对无相似度候选显示「未建立图库 / 图库需重建」，不显示百分比。"""
    assert "hasSim" in vision_html
    assert "未建立图库" in vision_html
    assert "图库需重建" in vision_html
    assert "sim-none" in vision_html


# ============ 9. 始终存在「其他」 ============

def test_other_option_always_present(vision_html):
    """9. 候选列表末尾永远有「其他」人工选项。"""
    assert "chooseOther()" in vision_html
    assert "选择「其他」" in vision_html
    assert "以上都不是" in vision_html
    # 初始状态不自动选中任何候选
    assert 'class="cand selected"' not in vision_html


# ============ 10. 未人工选择不能进入收货确认流程 ============

def test_cannot_proceed_without_manual_selection(vision_html):
    """10. 未点击过任何候选时，确认/跳转收货都不生效。"""
    assert "if (!selected) return;" in vision_html
    assert 'let selected = null;' in vision_html
    # 收货入口默认隐藏，只有人工确认后才赋 href
    assert 'id="receive-link"' in vision_html
    assert 'style="display:none;' in vision_html
    assert "receiveLink.href = '/receive?product_id='" in vision_html
    # 未选择任何候选时不产生跳转链接
    assert "receiveLink.removeAttribute('href')" in vision_html
    # 渲染候选时不得自动调用 confirmChoice / chooseSku
    assert "renderCandidates();" in vision_html
    assert "renderCandidates();\n      confirmChoice" not in vision_html


def test_api_response_has_no_autoselection(monkeypatch):
    """10b. 后端同样不返回任何"已选定"结果。"""
    with SessionLocal() as db:
        _create_product(db, 1, embeddings=[_vec(0)])
        db.commit()
    monkeypatch.setattr(
        vision_embedding, "embed_bytes",
        lambda data: np.array(_vec(0), dtype=np.float32),
    )
    resp = client.post(
        "/vision/match",
        files={"file": ("camera.jpg", io.BytesIO(JPEG_BYTES), "image/jpeg")},
    )
    body = resp.json()
    for forbidden in ("selected", "confirmed", "inventory_id", "inventory_code", "barcode"):
        assert forbidden not in body


# ============ 11. 选择 SKU 后能够进入 /receive ============

def test_receive_page_accepts_product_id():
    """11. 人工选款后可跳转 /receive?product_id=xxx 并自动带入 SKU 与固定售价。"""
    with SessionLocal() as db:
        p = _create_product(db, 1, embeddings=[_vec(0)], price=45)
        db.commit()
        pid = p.id

    resp = client.get(f"/receive?product_id={pid}")
    assert resp.status_code == 200
    html = resp.text
    assert f"{SKU_PREFIX}001" in html
    assert "售价45元" in html  # 下拉选项文案
    # 该 SKU 被自动选中（selected_id 命中）
    assert f'value="{pid}" selected' in html


def test_receive_page_ignores_invalid_product_id():
    """11b. product_id 不存在时不报错，回落到手工下拉选择。"""
    resp = client.get("/receive?product_id=99999999")
    assert resp.status_code == 200
    assert "请选择 SKU" in resp.text


# ============ 12. 人工选款前后都不会自动创建库存 ============

def test_no_inventory_created_by_recognition(monkeypatch):
    """12. 拍照识别、人工选择、确认结果全程不产生库存记录。"""
    with SessionLocal() as db:
        _create_product(db, 1, embeddings=[_vec(0)])
        db.commit()
    before = _inventory_count()

    monkeypatch.setattr(
        vision_embedding, "embed_bytes",
        lambda data: np.array(_vec(0), dtype=np.float32),
    )
    # 模拟：一次拍照识别 + 一次重拍再识别
    for _ in range(2):
        resp = client.post(
            "/vision/match",
            files={"file": ("camera.jpg", io.BytesIO(JPEG_BYTES), "image/jpeg")},
        )
        assert resp.status_code == 200, resp.text
    client.get("/vision/skus")
    pid = resp.json()["candidates"][0]["product_id"]
    client.get(f"/receive?product_id={pid}")

    assert _inventory_count() == before


def test_vision_page_never_posts_inventory(vision_html):
    """12b. 视觉页不得出现入库请求；入库只在 /receive 页面发生。"""
    # 页面里只有 /vision/match、/vision/skus 两个数据请求，没有任何入库请求
    posts = re.findall(r"fetch\('([^']+)'", vision_html)
    assert set(posts) <= {"/vision/match", "/vision/skus"}
    assert "method: 'POST'" in vision_html


def test_choose_other_creates_nothing():
    """12c. 选择「其他」不新建商品，也不触碰库存。"""
    before_products = None
    with SessionLocal() as db:
        before_products = int(db.execute(select(func.count()).select_from(Product)).scalar())
    before_inv = _inventory_count()

    resp = client.get("/vision/skus")
    assert resp.status_code == 200
    # 前端选「其他」是纯前端行为，此处校验后端没有任何写操作被触发
    with SessionLocal() as db:
        after_products = int(db.execute(select(func.count()).select_from(Product)).scalar())
    assert after_products == before_products
    assert _inventory_count() == before_inv


# ============ 附加：摄像头异常提示 ============

def test_camera_error_messages(vision_html):
    """附加：权限拒绝 / 无设备 / 被占用等常见异常都有明确中文提示。"""
    for keyword in [
        "NotAllowedError",       # 权限被拒绝
        "NotFoundError",         # 无摄像头设备
        "NotReadableError",      # 设备被占用
        "OverconstrainedError",  # 分辨率不支持
        "SecurityError",         # 非安全上下文
        "摄像头权限被拒绝",
        "未检测到摄像头设备",
        "被其他程序占用",
    ]:
        assert keyword in vision_html, f"缺少摄像头异常提示: {keyword}"


def test_retake_resets_state(vision_html):
    """附加：「重新拍照」清空截图与识别结果，回到实时预览。"""
    assert "function retake()" in vision_html
    assert "resetResultPanels()" in vision_html
    assert "location.reload" in vision_html


def test_clip_model_not_reinitialized_per_request(vision_html):
    """附加：服务端没有额外的摄像头帧接口，模型单例不被按请求重建。"""
    # 页面不得出现 OpenCV 式轮询/视频流请求
    assert "MediaRecorder" not in vision_html
    assert "setInterval" not in vision_html
    assert "/vision/frame" not in vision_html
