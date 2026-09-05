"""模型管理中心（原案 1.2 / W10）：清单、状态解析、下载、本地导入。

手动导入是一等能力：用户从浏览器（ModelScope/HF 镜像）下载后放入
`<data>/models/<kind>/<model_dir>`，importer 扫描登记即生效——网络不可达不阻塞使用。
"""

from __future__ import annotations
