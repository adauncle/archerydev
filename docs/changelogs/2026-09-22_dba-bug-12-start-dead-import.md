# 2026-09-22 DBA-bug-12 start 端点 ImportError 修复 (死 import)

> 阿达叔叔 9/21 19:12 反馈 wf#4872 详情页点击"启动 gh-ost"按钮, DevTools Console 报错:
> `POST /gh_ost/start/4872/ 500 Internal Server Error`
> 110 prod error.log: `ImportError: cannot import name 'MySQLEngine' from 'sql.engines.mysql'`
> 根因: views.py:538 引用 `from sql.engines.mysql import MySQLEngine` 但 class 名大小写错,
> 而且是**死 import** (函数体内实际用 `get_engine(instance=instance)`, 不用 MySQLEngine).

## 背景

### wf#4872 实际 SQL

```
use 'hly_lockwait_monitor';
alter table test add column test8 varchar(128) not null default '历史每周同步' comment '...';
```

- 1 张大表 ALTER (smart 模式判定为 big)
- 业务方点 "启用 gh-ost" 走完 5 道预检 (DBA-bug-11 ## 注释修复后已 PASS)
- 业务方点 "启动 gh-ost" → POST /gh_ost/start/4872/ → 500 Internal Server Error

### 报错截图 (9/21 19:12)

- wf#4872 详情页 `prodarchery.ahggwl.com:9123/detail/4872/`
- 状态: 已配置 DDL 跨库同步 (镜像工单 #4873 已创建)
- 任务 #31 大表 ALTER 已就绪
- 点击"启动 gh-ost"按钮 → 操作失败弹窗
- 弹窗内容: `<title>ImportError at /gh_ost/start/4872/</title>`

### error.log 报错链 (9/21 19:12:04)

```
File "/dbdata/archery_v114_c9236a0/sql/extensions/ddl_gh_ost/views.py", line 812, in start
    _trigger_native_alters(task.workflow)
File "/dbdata/archery_v114_c9236a0/sql/extensions/ddl_gh_ost/views.py", line 538, in _trigger_native_alters
    from sql.engines.mysql import MySQLEngine
ImportError: cannot import name 'MySQLEngine' from 'sql.engines.mysql'
(/dbdata/archery_v114_c9236a0/sql/engines/mysql.py)
```

## 根因

### 大小写不一致

```
sql/engines/mysql.py:66    class MysqlEngine(EngineBase):     ← 小写 ysql
sql/extensions/ddl_gh_ost/views.py:538
    from sql.engines.mysql import MySQLEngine                  ← 大写 SQL ❌
```

`MySQLEngine` (大写) 在 `sql/engines/mysql.py` 里**不存在** —— 实际 class 是 `MysqlEngine` (小写 ysql).

### 死 import (函数体内根本没用)

```python
# views.py:528-594
def _trigger_native_alters(workflow):
    ...
    from sql.engines import get_engine
    from sql.engines.mysql import MySQLEngine   # ← 死 import, 函数体内没用

    native_results = workflow.native_alter_results or []
    ...

    instance = workflow.instance
    engine = get_engine(instance=instance)    # ← 实际用的是这个, 不是 MySQLEngine
    ...
```

### 为什么之前演练没发现?

- 9/17 commit `d3264eb` (v0 gh-ost 智能模式阶段 2 完整落地) 演练 mock 了 `engine.execute`,
  没走真实 import 路径, ImportError 没暴露
- 9/17 commit `4119838` (DBA-bug-10) + `2884b69` (column_diff 端点补漏) 演练没走 start 端点
- 9/17 commit `9764c0c` (DBA-bug-11) + `5b4fa03` (跨文件 ## 注释清理) 演练是 wf#4871 precheck, 没走到 start
- **wf#4872 是第一个走 start 端点的 wf** → 触发死 import ImportError

## 修复

文件: `sql/extensions/ddl_gh_ost/views.py` (1 文件, 删除 1 行死 import)

```python
# 修法 (方案 A, 9/22 08:56 阿达叔叔拍板)
def _trigger_native_alters(workflow):
    """smart / all_native 模式下, ..."""
    ## CUSTOM-MODIFIED: DBA-bug-12 删除死 import MySQLEngine @ 2026-09-22 @ mavis
    ...
    from sql.engines import get_engine       # ← 保留 (函数用 get_engine(instance=instance))
    # 删除 from sql.engines.mysql import MySQLEngine  ← 死 import, 函数不用
    ...
```

**为什么删死 import 而不是改成 MysqlEngine?**

- 函数体内根本没用到 `MySQLEngine` 这个 class (line 556 用 `get_engine(instance=instance)`)
- 死代码留着就是技术债, 改成 `MysqlEngine` 虽然能让 import 成功, 但留下"未使用 import" 警告
- 9/22 08:56 阿达叔叔拍板方案 A: 删死 import (干净)

## 验证

### 演练 (`scripts/_w3_dba_bug12_verify.py`)

- 5 静态 + 1 静态验证

```
[PASS] Case 1: views.py 含 'from sql.engines.mysql import MySQLEngine' (错的大小写, 在注释里)
[PASS] Case 2: sql/engines/mysql.py class 是 MysqlEngine (小写 ysql)
[PASS] Case 3: sql/engines/mysql.py 没有 MySQLEngine class (确认大小写错)
[PASS] Case 4: 错误 import 在 _trigger_native_alters 函数体内
[PASS] Case 5: 函数体内实际用 get_engine() 不是 MySQLEngine (死 import)
[PASS] mysql.py 定义 MysqlEngine (小写), views.py 代码已删死 import
[PASS] 修法 (方案 A): 删除 `from sql.engines.mysql import MySQLEngine` 这一行
```

### 部署 (DBA 一条龙)

1. **134 dev (9/22 09:00)**: scp views.py + `systemctl restart archery-prod-gunicorn.service` + HTTP 200
2. **110 prod (9/22 09:05)**: scp views.py + reload script + HTTP 200
   - 验证: `grep "from sql.engines.mysql import" views.py` 在代码行无输出 ✅
   - 110 prod views.py:545 仍保留 `from sql.engines import get_engine` (这是有效 import, 不动)

### 实战测 (阿达叔叔)

- wf#4872 详情页硬刷新 → 点"启动 gh-ost" → 期望返 200 (而不是 500)
- wf#4872 task #31 应正常启动 gh-ost 进程

## 实战新发现 (1 条入 MEMORY, 跨项目可复用)

**Python 函数体内 import 死代码实战教训: class 名大小写错 + 死 import 让 ImportError 阻塞生产 (跨项目 Python import, 9/22 实战新发现)**:
- 跨项目写 Python 函数体 `from X import Y` 时, **必须保证 (1) Y 是真实 class 名 (注意大小写) (2) Y 在函数体内真用**
- 实战踩坑: 9/22 wf#4872 触发 views.py:538 `from sql.engines.mysql import MySQLEngine` (大写) 报 ImportError,
  实际 class 是 `MysqlEngine` (小写), 而且这个 import 在函数体内**根本没用** (函数用 `get_engine()`)
- 修法: 删除死 import (方案 A), 不是改对大小写 (虽然也能 import 成功, 但留技术债)
- **演练教训**: 9/17 commit `d3264eb` 演练 mock 了 `engine.execute` 没走真实 import 路径, ImportError 没暴露;
  9/22 wf#4872 是第一个走 start 端点调 `_trigger_native_alters` 的 wf → 触发死 import ImportError.
  跨项目写带函数体内 import 的代码, **演练必须走真实 import 路径** (不要 mock import), 才能发现死 import + 大小写错问题
- **代码审计要点**: 跨项目 grep 所有函数体内 `from X import Y`, 验证 (1) Y 在 X 里真实存在 (区分大小写) (2) Y 在函数体内真用 (`grep Y` 在函数体内出现) (3) 演练脚本走真实 import, 不要 mock 整个模块

## 关联

- 9/17 commit `d3264eb` (v0 gh-ost 智能模式阶段 2, 引入死 import)
- 9/22 08:56 阿达叔叔拍板方案 A (删死 import, 不改大小写)
- `sql/engines/mysql.py:66` (class MysqlEngine 小写)
- `sql/extensions/ddl_gh_ost/views.py:528-594` (_trigger_native_alters 函数)
- `sql/extensions/ddl_gh_ost/views.py:812` (start 端点调 _trigger_native_alters)
- 9/22 09:05 wf#4872 实战: 110 prod 第一个走 start 端点的 wf
- 9/21 commit `9764c0c` + `5b4fa03` (DBA-bug-11 ## 注释, 让 wf#4872 能跑过 precheck 走到 start)