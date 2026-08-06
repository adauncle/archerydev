"""gh-ost 无锁 DDL 二次开发 —— v0.3.0-alpha。

设计参考：docs/designs/2026-08-05_gh-ost-product-design.html

alpha 阶段只交付：
    1. ext_ddl_ghost_task 模型 + admin
    2. 预检 5 道函数（只读不写）
    3. Django template 进度面板 + JS polling
    4. start 端点：alpha 标记 running，不真启 gh-ost 子进程

beta 阶段才真启 gh-ost 子进程 + 演练大表 + 切表。
"""
default_app_config = "sql.extensions.ddl_gh_ost.apps.DdlGhOstConfig"
