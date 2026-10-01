# -*- coding: utf-8 -*-
"""
城市公共服务智能助手 - 单元测试包

本包内所有测试均为离线 pytest 单测（不依赖真实 API / MySQL / Milvus），
通过 mock 外部依赖（Database、httpx、LLM、data_provider）验证业务逻辑。

运行方式（在项目根目录 D:\\car 下执行）：
    python -m pytest
"""
