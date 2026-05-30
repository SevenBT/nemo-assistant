"""
内置工具包 — 统一工具系统的顶层入口。

本包实现了完整的工具生命周期管理：
  - base.py:     ABC 抽象基类，定义所有工具必须实现的接口
  - schema.py:   Schema DSL，用 Python 类声明 JSON Schema 参数定义
  - context.py:  ToolContext 依赖注入容器，向工具提供共享资源
  - registry.py: ToolRegistry 注册中心，统一管理工具的注册/查询/执行
  - loader.py:   pkgutil 自动发现机制，扫描本包下所有工具类并注册
  - script_adapter.py: 将用户自定义脚本工具适配为 BuiltinTool 接口

新增工具只需在本包下创建 .py 文件并继承 BuiltinTool，无需修改其他文件。
"""
