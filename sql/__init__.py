# sql 模块
# 占位文件 —— 合入上游 Archery 源码后会被替换
# 上游结构：
#   sql/
#     models.py          # SQL 审核/工单/资源相关模型
#     views.py           # 视图
#     serializers.py     # DRF 序列化器
#     urls.py            # 路由
#     tasks.py           # Celery 异步任务
#     engines/           # 数据库引擎（MySQL/PG/Oracle/...）
#     binlog2sql/        # binlog 解析
#     ...
#     extensions/        # 内部二次开发扩展（保持隔离）
