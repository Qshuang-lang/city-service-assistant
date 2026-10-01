# -*- coding: utf-8 -*-
"""
pytest 全局配置：将项目根目录（D:\\car）加入 sys.path，
保证 tests 包内可稳定导入 city_service_assistant.*（与 pytest.ini 的 pythonpath 双保险）。
"""
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
