"""
信息源插件包

每个数据源（如 Boss 直聘）实现为一个 BaseSource 子类，统一对外暴露
`fetch_new_urls()` 接口。目前项目聚焦 Boss 直聘岗位采集，其余源（B 站 /
arXiv）为可选扩展，按需实现 BaseSource 子类后在此注册即可。
"""

from src.sources.base import BaseSource

__all__ = ["BaseSource"]
