# 毛绒娃娃收货系统（第5阶段：电脑摄像头实时预览 + 拍照识别）

抖音电商毛绒娃娃收货系统。当前阶段包含：数据库、商品 SKU 管理、商品参考图图库、CLIP 视觉识别、**电脑摄像头实时预览 + 拍照识别 + 人工确认 SKU → 录入实际回收成本 → 创建单只库存 → 自动取固定售价 → 生成业务条码**。

收货流程只做：摄像头拍照/上传图片 → AI 给出候选 → **人工确认 SKU** → 输入回收成本 → 创建 inventory → 生成编号与条码 → 展示结果。

**尚未实现**：标签打印、打印机驱动、自动调用标签软件、Excel 收货台账导出、销售、利润分析、AI 自动确认、自动改售价、新旧/吊牌判断。

## 业务规则（核心）

1. **SKU（products 表）决定固定售价**：如 S001 = 星黛露 20cm 普通款 = 40 元。
2. **同一 SKU 的每一只实物成本可以不同**：每只娃娃在 inventory 表中单独一条记录，记录自己的实际回收成本。
3. 有无吊牌、新旧程度**不参与**售价判断。
4. products 表**不存**任何一只娃娃的实际回收成本。

示例：

| inventory_code | sku  | recovery_cost | 售价（来自 products） |
| -------------- | ---- | ------------- | --------------------- |
| D000001        | S001 | 18            | 40                    |
| D000002        | S001 | 21            | 40                    |
| D000003        | S001 | 16            | 40                    |

## 目录结构

```
app/
    main.py               # FastAPI 入口 + /health 健康检查
    core/
        config.py         # 读取 .env 的配置
        database.py       # SQLAlchemy engine / SessionLocal / Base / 建表
    models/
        product.py        # Product      -> products 表（SKU 主档）
        product_image.py  # ProductImage -> product_images 表（SKU 识别图片）
        inventory.py      # Inventory    -> inventory 表（每只娃娃一条记录）
    schemas/
        __init__.py       # 第2阶段再填充 Pydantic 模型
    api/
        __init__.py       # 第2阶段再填充路由
    templates/
        vision.html           # /vision 摄像头实时预览 + 拍照识别 + 候选人工选择
        receive.html          # /receive 收货登记
        inventory_list.html   # /inventory 库存查询
    vision/
        build_embeddings.py   # 批量生成 SKU 参考图 embedding
tools/
    check_camera_js.js        # 可选：Node + DOM 桩，无摄像头也能跑前端摄像头逻辑
tests/
    test_database.py          # 数据库基础测试
    test_products.py          # 商品 CRUD 测试
    test_product_images.py    # 商品图片上传/删除测试
    test_vision.py            # 视觉识别（embedding/相似度/AI候选）测试
    test_inventory.py         # 收货入库、单只成本、条码测试
    test_camera_vision.py     # 第5阶段：摄像头拍照识别测试
.env                      # 本地真实配置（不提交）
.env.example              # 配置模板
requirements.txt
```

## 快速开始（Windows）

### 1. 创建虚拟环境并安装依赖

```powershell
cd e:\xiaopiaoxitong
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 创建 MySQL 数据库

用 root 登录 MySQL 后执行（库名与 .env 中的 DB_NAME 一致）：

```sql
CREATE DATABASE doll_system DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

命令行方式：

```powershell
mysql -u root -p -e "CREATE DATABASE doll_system DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

### 3. 配置 .env

复制 `.env.example` 为 `.env`（项目里已生成一个 `.env`），把 `DB_PASSWORD` 改成你的 MySQL root 密码：

```
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=你的MySQL密码
DB_NAME=doll_system
DB_CHARSET=utf8mb4
```

### 4. 启动 FastAPI

```powershell
uvicorn app.main:app --reload
```

启动时会自动建表（三张表已存在则跳过）。验证：

- 浏览器打开 http://127.0.0.1:8000/health ，应返回 `{"status":"ok"}`
- 接口文档：http://127.0.0.1:8000/docs

### 5. 运行测试

先确认 .env 已填好、数据库已创建，然后：

```powershell
pytest -v
```

覆盖：数据库连接/建表、商品 CRUD、SKU 重复/售价非整数校验、逻辑删除、图片上传/列表/删除
（含本地文件删除）、inactive 过滤、视觉识别候选与相似度、收货入库/单只成本/条码、
摄像头拍照识别（第5阶段）。测试数据会自动清理（`TEST-` 前缀）。

> 注意：测试针对的是 MySQL 开发库， pytest 用例只断言自己创建的 `TEST-` / `TEST-VIS-` /
> `TEST-CAM-` 前缀数据，不会受库里 S001 等真实业务 SKU 影响。

可选：前端摄像头逻辑的无摄像头验证（需 Node >= 16，mock getUserMedia + canvas）：

```powershell
node tools/check_camera_js.js
```

### 6. 插入测试数据

```powershell
python -m app.seed
```

会插入 5 个 SKU：S001 星黛露(40)、S002 星黛露特别款(50)、S003 三岁(30)、S004 氧氧(35)、S005 洛奇奇(45)。已存在则跳过。

## 商品管理后台

启动后浏览器访问：

- 商品列表/新增：http://127.0.0.1:8000/admin/products
- 商品详情（编辑 + 上传/删除参考图片 + Embedding 状态）：http://127.0.0.1:8000/admin/products/{id}
- 收货登记：http://127.0.0.1:8000/receive
- 库存查询：http://127.0.0.1:8000/inventory

## 第3阶段：视觉识别使用流程

### 1. 安装视觉依赖（首次）

视觉功能使用 CLIP（open_clip_torch + torch）。CPU 版安装（体积小，约 200MB，推荐）：

```powershell
.venv\Scripts\pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
.venv\Scripts\pip install open_clip_torch pillow numpy
```

如果有 NVIDIA 显卡想用 GPU，则安装 CUDA 版 torch（参见 https://pytorch.org/get-started/locally/ 选择对应命令），代码会自动检测 CUDA。

### 2. 上传 SKU 参考图片

在商品详情页（如 http://127.0.0.1:8000/admin/products/2 ）为每个款式上传尽量多角度的参考图，一个 SKU 可上传几十张。

### 3. 生成 Embedding（首次必须）

```powershell
# 只为还没有 embedding 的图片生成（已有则跳过）
python -m app.vision.build_embeddings

# 强制全部重新生成（换模型/换权重后使用）
python -m app.vision.build_embeddings --force
```

首次运行会自动下载 CLIP 预训练权重 **ViT-B-32 / openai（约 350MB）**，只需下载一次，之后从本地缓存加载。模型在进程内只加载一次。

终端会逐张输出 `SKU / 图片 / OK / dim=512`，最后给出总数/成功/失败/跳过汇总；失败图片会列出原因（如文件不存在）。

> 网络不通时可设置 HuggingFace 镜像：`$env:HF_ENDPOINT="https://hf-mirror.com"`（openai 权重走 Azure CDN，一般可直连）。

### 4. 打开视觉识别页面（摄像头实时预览）

必须用 **`http://127.0.0.1:8000` 或 `http://localhost:8000`** 访问，浏览器才允许摄像头权限
（用局域网 IP 或 https 之外的地址打开，浏览器会直接禁用 `getUserMedia`）。

```powershell
uvicorn app.main:app --reload
```

浏览器访问：**http://127.0.0.1:8000/vision**

页面布局：

| 区域 | 内容 |
| ---- | ---- |
| 左侧 | 摄像头实时画面、摄像头状态、「启动摄像头」「拍照识别」「重新拍照」「关闭摄像头」按钮，以及备用的「上传图片识别」 |
| 右侧 | 最近一次拍摄的照片、全部 active SKU 候选列表、已选款式信息、收货入口 |

- 按相似度从高到低显示全部 active SKU（含参考图、SKU、固定售价、相似度）
- **未建立 Embedding 的 SKU 仍可人工选择**，排在列表最后，标记「未建立图库」，**不会伪造相似度**
- **系统永远不会自动选择第一名**，必须人工点击「选择这个款式」或最后一项「其他」

### 5. 视觉匹配 API

```
POST /vision/match
Content-Type: multipart/form-data
字段：file（jpg/jpeg/png/webp，≤10MB）
```

返回示例：

```json
{
  "query_image": "",
  "candidates": [
    {"product_id": 2, "sku": "S001", "name": "星黛露", "size": "20cm", "style": "普通款",
     "sale_price": 40, "similarity": 0.9600,
     "reference_image": "/uploads/products/S001/xxx.jpg",
     "has_embedding": true, "image_count": 3},
    {"product_id": 5, "sku": "S004", "name": "氧氧", "size": "20cm", "style": "普通款",
     "sale_price": 35, "similarity": null,
     "reference_image": "", "has_embedding": false, "image_count": 0}
  ]
}
```

- 只返回 active SKU，**全部返回**（不做 Top5 截断）
- 有 embedding 的按 similarity 倒序在前；没有可用 embedding 的排在最后，`similarity=null`
- 整个图库都没建 embedding 时返回 400，detail 含 `build_embeddings` 提示；前端会
  自动退化为调用 `GET /vision/skus` 列出全部 SKU 供人工选择
- 查询图片只在内存处理，不写入图库、不保存永久文件

### 5b. 候选兜底 API（AI 不可用时）

```
GET /vision/skus
```

返回全部 active SKU（SKU / 名称 / 尺寸 / 款式 / 固定售价 / 参考图数），`similarity` 一律 `null`。
用于摄像头或 AI 不可用时，仍能人工选择款式继续收货。

### 视觉模型说明

| 项目 | 说明 |
| ---- | ---- |
| 模型 | OpenAI CLIP，经 open_clip_torch 加载：`ViT-B-32` / 权重 `openai` |
| embedding 维度 | 512（L2 归一化，存于 product_images.embedding，JSON） |
| 设备 | 配置 `VISION_DEVICE=auto`：有 CUDA 用 GPU，否则 CPU |
| 模型配置位置 | `.env`：VISION_MODEL_NAME / VISION_PRETRAINED / VISION_DEVICE |
| 相似度 | 余弦相似度；一个 SKU 多张图时取**最高相似度**（见 matcher.py 注释） |

## 第5阶段：电脑摄像头拍照识别（当前阶段）

### 1. 打开视觉识别页

浏览器访问 **`http://127.0.0.1:8000/vision`**（必须是 localhost / 127.0.0.1）。

### 2. 启动电脑自带摄像头

点击左侧「启动摄像头」→ 浏览器弹窗中选「允许」。
状态栏会显示当前状态：未启动 / 正在启动 / **已就绪（1280×720）** / 各类异常原因。

> 默认使用电脑自带摄像头，不需要额外安装 OpenCV 或其他摄像头服务；
> 摄像头打开后视频只在浏览器本地显示，**不做实时视频流识别**，
> 只有点击「拍照识别」时才抓一帧 → JPEG → 调用现有 `/vision/match`。

### 3. 拍照识别

把娃娃放进取景框 → 点击「拍照识别」→ 右侧显示拍摄照片与候选列表。
不满意就点「重新拍照」，照片和识别结果会一起清空，回到实时预览。

### 4. AI 给出候选 + 人工选款

拍照后右侧显示候选列表：有 embedding 的按相似度倒序，未建立图库的排在最后并标「未建立图库」。
**系统永远不会自动选择第一名**，必须人工点击「选择这个款式」或最后一项「其他」。

### 5. 摄像头不可用时的备用链路

左侧保留「上传图片识别」，上传 jpg/jpeg/png/webp 同样走 `/vision/match`。

### 摄像头权限与设备异常排查

| 现象 / 报错 | 原因 | 处理 |
| ----------- | ---- | ---- |
| 状态栏：摄像头权限被拒绝 `NotAllowedError` | 点了「拒绝」或系统层关闭了权限 | 点击地址栏左侧摄像头/锁形图标 → 允许摄像头；Windows：设置 → 隐私和安全性 → 相机 → 允许应用访问相机 |
| 状态栏：未检测到摄像头设备 `NotFoundError` | 没有可用摄像头或被禁用 | 设备管理器 → 摄像机/照相机，确认自带摄像头未被禁用；或改用上传图片 |
| 状态栏：被其他程序占用 `NotReadableError` | 相机、腾讯会议、钉钉等已占用设备 | 关闭占用摄像头的软件后重试 |
| 状态栏：不支持请求的分辨率 `OverconstrainedError` | 驱动不支持请求的分辨率 | 重试；仍失败改上传图片 |
| 状态栏：非安全上下文 / 不支持摄像头接口 | 用局域网 IP 或旧浏览器打开 | 改用 `http://127.0.0.1:8000` 或 Chrome / Edge |
| 页面：`AI 图库尚未建立 Embedding` | 图库没跑过建库脚本 | 上传参考图后运行 `python -m app.vision.build_embeddings`，在此之前仍可人工选款 |

### 第5阶段实现要点

- 摄像头走浏览器 `navigator.mediaDevices.getUserMedia()`，`<video>` 实时预览，
  `<canvas>` 抓帧 → `toBlob('image/jpeg', 0.92)` → `FormData` → `POST /vision/match`
- **不引入 OpenCV、不新增服务端视频流接口**；CLIP 模型仍是单例，不会每次请求重建
- 候选列表 = 有 embedding 的按相似度倒序 + 未建立图库的排最后（`similarity=null`）
- 整条链路只在人工点击后才发生，**不会自动选款、不会自动创建库存**

## 第4阶段：收货登记流程（收货 → 单只库存 → 条码）

### 1. 打开视觉识别页

浏览器访问 **http://127.0.0.1:8000/vision** 。

### 2. 拍摄/上传娃娃图片

摄像头拍照（见第5阶段），或在没有摄像头时用「上传图片识别」。

### 3. AI 返回全部 SKU 候选

按相似度从高到低展示所有 active SKU，含参考图、SKU、固定售价、相似度；
未建立图库的 SKU 排在最后。**系统永远不会自动选择第一名**。

### 4. 人工选择正确款式

点击对应卡片上的「选择这个款式」，或最后固定的「其他」。

### 5. 点击进入收货

确认后会看到「进入收货登记」按钮，跳转到 `/receive?product_id=xxx`，自动带入 SKU、名称、尺寸、款式、固定售价。

### 6. 输入该只娃娃实际回收成本

只能填成本（>=0，最多两位小数）。**固定售价来自 SKU 主档，收货页不可修改**。

### 7. 确认入库

点击「确认入库」，后端 `POST /inventory` 创建库存。

### 8. 系统生成 inventory_code

由数据库自增 id 派生，格式 `D000001`、`D000002` ……唯一、稳定递增、并发安全。

### 9. 系统生成 barcode

规则：`0 + 售价十位 + 任意两位数字xx + 成本(两位) + 售价个位`，如售价40/成本18 → `04xx180`。创建时生成一次并保存到 `inventory.barcode`，之后读取不再变化。

成功后页面展示：库存编号、SKU、商品、尺寸、款式、回收成本、固定售价、条码。

> 当前版本还没有：自动打印、销售、利润。

### 收货 API

```
POST /inventory
Content-Type: application/json
{"product_id": 1, "recovery_cost": "18"}        # 或 {"sku": "S001", "recovery_cost": 18}
```

- `recovery_cost`：Decimal，>=0，最多两位小数；客户端不要传 `sale_price`（传了也会被忽略，售价只读 SKU 主档）。
- 只有 **active** 状态的 SKU 才能入库。
- 成本为整数且在 0~99 元时可生成条码；成本含小数（如 18.50）或超出 0~99 时，条码为 `null`（当前规则无法编码，见 `app/services/barcode.py`）。

返回示例：

```json
{
  "inventory_code": "D000001",
  "sku": "S001",
  "name": "星黛露",
  "size": "20cm",
  "style": "普通款",
  "recovery_cost": "18.00",
  "sale_price": 40,
  "barcode": "0442180",
  "status": "in_stock",
  "received_at": "2026-09-29T12:00:00"
}
```

### 库存查询页

浏览器访问 **http://127.0.0.1:8000/inventory** ，支持按 SKU、商品名称、库存编号搜索，默认按收货时间倒序。

## 第2阶段 API

### 商品 SKU

| 方法 | 路径 | 说明 |
| ---- | ---- | ---- |
| POST | /products | 新增商品（sku 唯一，sale_price 整数） |
| GET | /products | 列表，可带 `?status=active` 过滤 |
| GET | /products/{id} | 详情 |
| PUT | /products/{id} | 修改（sku 不可改） |
| DELETE | /products/{id} | 逻辑删除：status 改为 inactive |

### 商品图片（一个 SKU 可多张）

| 方法 | 路径 | 说明 |
| ---- | ---- | ---- |
| POST | /products/{id}/images | 上传图片（jpg/jpeg/png/webp，校验真实图片内容） |
| GET | /products/{id}/images | 图片列表 |
| DELETE | /products/{id}/images/{image_id} | 删除图片（数据库记录 + 本地文件） |

图片保存到 `uploads/products/{sku}/`，通过 `/uploads/{image_path}` 静态访问。

## 数据表说明

### products（SKU 主档）

| 字段       | 类型         | 说明                                   |
| ---------- | ------------ | -------------------------------------- |
| sku        | String(32)   | SKU 编号，唯一，如 S001                |
| name       | String(64)   | 商品名称，如：星黛露                   |
| size       | String(32)   | 尺寸，如：20cm                         |
| style      | String(32)   | 款式，如：普通款 / 特别款              |
| sale_price | Integer      | 固定售价（元），整数                   |
| status     | String(16)   | active=在售 / inactive=停用，默认 active |

### product_images（SKU 识别图片）

| 字段       | 类型       | 说明                                         |
| ---------- | ---------- | -------------------------------------------- |
| product_id | FK         | 关联 products.id，一个 SKU 可有多张图片      |
| image_path | String(255)| 图片路径                                     |
| embedding  | JSON       | 特征向量，第1阶段允许为 NULL（视觉识别未实现）|

### inventory（单只娃娃库存）

| 字段           | 类型          | 说明                                                 |
| -------------- | ------------- | ---------------------------------------------------- |
| inventory_code | String(32)    | 单只娃娃唯一编号，如 D000001                         |
| product_id     | FK            | 关联 products.id                                     |
| recovery_cost  | DECIMAL(10,2) | 该只娃娃实际回收成本（元），同 SKU 每只可不同        |
| barcode        | String(64)    | 条码，后续阶段生成，允许为 NULL                      |
| image_path     | String(255)   | 该只娃娃实拍图片，允许为 NULL                        |
| status         | String(16)    | 默认 in_stock（在库）                                |
| received_at    | DateTime      | 收货时间                                             |

## 暂未实现（后续阶段）

标签打印、打印机驱动、自动调用标签软件（HPRT N31 + 现有标签软件）、Excel 收货台账导出、
收货工作台整合（第6阶段）、销售表、利润分析、定价表、AI 自动确认、自动修改售价、
新旧程度/吊牌判断、用户权限、复杂前端。
