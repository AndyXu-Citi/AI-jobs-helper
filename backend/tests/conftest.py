"""
pytest 共享 fixtures。

把项目根目录（backend/）加入 sys.path，使测试文件能用
`from src.xxx import ...` 的导入风格。
"""
import os
import sys

# 让 tests/ 能 import src.*（项目根加入 path）
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
