"""视觉识别服务。

- model.py：CLIP 模型加载、设备选择、进程内单例生命周期
- embedding.py：图片 -> embedding，以及 embedding 的 JSON 序列化
- matcher.py：查询 embedding 与 SKU 参考图 embedding 的相似度聚合排序
"""
