# W2 D18 — DDL 跨库同步 镜像/源工单 alert 块 (9/2 22:30)

## 背景

9/2 21:43 业务 RD 验证 D15 字符集 implicit/explicit 修复生效后, 顺手看
镜像工单 (wf#119) 发现 3 个 UX 缺口:

1. **没有"🤖 DDL 跨库同步"标识** — 用户拿到镜像工单不知道这是 v0.5.0 自动生成的
2. **没有源工单 link** — 镜像工单页看不到"这是从 wf#118 来的", 用户看不出工单从哪来
3. **没有 DdlSyncHistory.sync_status 同步状态显示** — 用户不知道"现在同步到哪一步"

9/2 22:09 用户拍板方案 A: **只修 UX (alert 块), 数据层不一致先排查**。

## 134 dev 演练发现的现状

实际渲染 `/detail/119/` 镜像工单 (Django test client + force_login):
- ✓ `workflow_name [镜像] test` 出现
- ✓ SQL 完整 (`ALTER TABLE accesscard_black_detail add COLUMN test1...`)
- ✓ 目标库 `hly_accesscard_history` 显示
- ✓ source instance `hly_accesscard` 显示
- ✓ status `workflow_abort` (跟 DB 一致)
- ❌ 源工单 link 0 个
- ❌ "镜像" 标识 0 次
- ❌ 目标库没强调
- ❌ DdlSyncHistory 同步状态 0 个

## 修法 (2 文件)

### sql/views.py

`detail()` 函数在 `manual = SysConfig().get("manual")` 之后加 DdlSyncHistory
双向查询:

```python
## CUSTOM-MODIFIED: v0.5.0 D9 阶段 1 DDL 跨库同步 镜像/源工单 alert 标识
## 业务: 业务 RD 拿到镜像工单时知道这是 v0.5.0 自动生成的, 能跳回源工单
## 实战: D18 9/2 验证 /detail/119/ 发现镜像工单页没有 "🤖 镜像工单" 标识
## try/except 兜底: ddl_sync app 不可用 / 任何异常都不让 detail 500
ddl_sync_as_target = None
ddl_sync_as_source = []
try:
    from sql.extensions.ddl_sync.models import DdlSyncHistory
    ddl_sync_as_target = (
        DdlSyncHistory.objects
        .filter(target_workflow_id=workflow_id)
        .select_related("pair", "source_workflow", ...)
        .order_by("-created_at")
        .first()
    )
    ddl_sync_as_source = list(
        DdlSyncHistory.objects
        .filter(source_workflow_id=workflow_id)
        ...
    )
except Exception:
    logger.exception("ddl_sync history lookup failed")
```

context 字典加 2 个 key:
```python
"ddl_sync_as_target": ddl_sync_as_target,
"ddl_sync_as_source": ddl_sync_as_source,
```

### sql/templates/detail.html

line 22 (`<input type="hidden" id="editSqlContent" ...>`) 之后插入 2 个 alert 块:

#### 镜像工单 alert (蓝色, `ddl_sync_as_target`):

```html
{% if ddl_sync_as_target %}
<div class="alert alert-info" style="margin-top: 10px;">
    <strong>🤖 DDL 跨库同步 - 镜像工单</strong>
    &nbsp; <span class="label label-default">v0.5.0 自动生成</span>
    <p>本工单由
        <a href="/detail/{{ ddl_sync_as_target.source_workflow_id }}/">
            wf#{{ ddl_sync_as_target.source_workflow_id }} (name)
        </a>
        在源库 instance / db_name 通过 DDL 同步触发。
    </p>
    <p>目标库: <code>target instance / db</code> |
        同步状态: <span class="label label-info">label</span> |
        库对: name | 表: table_name</p>
    {% if error_message %}<p style="color: #a94442;">错误信息: {{ error_message }}</p>{% endif %}
</div>
{% endif %}
```

#### 源工单 alert (黄色, `ddl_sync_as_source`):

```html
{% if ddl_sync_as_source %}
<div class="alert alert-warning" style="margin-top: 10px;">
    <strong>📡 DDL 跨库同步 - 已配置</strong>
    &nbsp; <span class="label label-default">v0.5.0 联动中</span>
    <p>本工单已配置跨库同步, 共触发 N 个镜像工单:</p>
    <ul>
        {% for h in ddl_sync_as_source %}
        <li>
            <a href="/detail/{{ h.target_workflow_id }}/">wf#id (name)</a>
            → target / db · 状态 label · 表 table
        </li>
        {% endfor %}
    </ul>
</div>
{% endif %}
```

#### 隐藏 input (8/26 字段 diff inline 区域联动)

顺手加 2 个 hidden input 配合 8/26 21:34 字段 diff inline 区域:

```html
<input type="hidden" id="sqlInstanceId" value="{{ instance_id_for_diff }}"/>
<input type="hidden" id="dbNameForDiff" value="{{ db_name_for_diff|safe }}"/>
```

(注: 134 dev 实际跑 8/26 21:34 老版本 inline 区域有 JS bug, 9/2 17:30
D12 修过。110 prod 仍是 7/19 上游版没 inline 区域。)

## 134 dev 演练 (Django test client)

演练前:
- 134 dev gunicorn master pid 12382 跑 8h+, 实战必 kill 拉新

演练后:

| 端点 | content-length | alert 块渲染 | 源/镜像 link |
|------|---------------|-------------|-------------|
| `/detail/119/` (镜像工单) | 93059 | 🤖 镜像工单 (1) + v0.5.0 自动生成 (2) | /detail/118/ ✓ |
| `/detail/118/` (源工单) | 92864 | 📡 已配置 (1) + v0.5.0 联动中 (1) | /detail/119/ ✓ |

**双向 link 全部通**, 业务 RD 现在能:
- 拿到镜像工单 → 看到 🤖 标识 + 源工单 link → 跳回 wf#118 看源 DDL
- 源工单页 → 看到 📡 已配置 + 镜像工单列表 → 跳到 wf#119 看同步状态

## 134 dev 部署

- SFTP 推 `views.py` (md5 `824795a4...` = local) + `detail.html` (md5 `f65eaf34...` = local)
- 备份 `/backup/d18_20260902_2225/` (views.py.bak 41315 bytes + detail.html.bak 98229 bytes)
- 134 dev gunicorn pids: 15628 (master) + 15630/15651/15652/15653 (4 worker, 22:30 拉新)
- 9003 端口 LISTEN ✓
- systemd status: active

## 实战踩坑 (D18 实战总结)

1. **gunicorn 启动 paramiko timeout** (D12 实战踩过复用): `setsid nohup ... & disown`
   在 paramiko channel 不立即返回, 实战 30s+ 超时. 修法 timeout=5 立即
   抛 PipeTimeout, 后续 `sleep 4; pgrep` 验证
2. **Python f-string `or` 优先级**: 实战 f-string 里 `(x or "")` 实际
   解析成 `x or ()`, SyntaxError. 必须双层括号 `((x or ''))`. 跟
   D8 阶段 2 实战 1 复用
3. **134 dev 走 /opt/archery/prod**: venv 在 prod 目录, dev 目录没 venv.
   9/1+9/2 W2 D6-D17 实战统一路径
4. **detail.html 编辑时 indent 别动**: 编辑器自动改 indent 空格
   会让 git diff 看着吓人 (-1753/+1849) 实际只插入 60 行. 实战用 Python
   脚本按行号精准插入, 不用 edit 工具

## 110 prod 状态 (待推)

- 110 prod `detail.html` 仍是 7/19 上游版 (md5 `82198afe...`)
- 没有字段 diff inline 区域 (8/26 实战) 也没有 alert 块 (本次)
- 110 prod 推 detail.html 时机: 等用户拍板 (跟 D12 实战发现 110 prod
  detail.html 是上游版 一致, 推 110 必须带 detail.html 一起)

## 推 110 prod 时机 (D18 实战新发现)

实战上 110 prod 应该:
- 推 2 文件: `views.py` + `detail.html` (跟 134 dev 实战一致)
- 8/26 21:34 字段 diff inline 区域 + 9/2 D15 fix JS ReferenceError + 9/2
  D18 alert 块 3 个功能一起推 (commit 0a04775 + 2a04a12 + 本次)

## 同源 entry

- W2 D9 阶段 1 sync_trigger.py (commit 5420c81, 9/1 18:00 R3 走当前配置实施)
- W1-D4 §2.2 业务库 DDL 工单详情页"本表已配置同步" 设计稿 (8/28 14:47)
- 8/13 AJAX 守卫教训 (try/except 兜底防御)
- 9/1 W2 D7 base.html 侧边栏套路 (4 perm 4 判定 + 菜单守卫)

## W2 进度 (9/2 一天爆肝 9 步)

- D6 ✓ (9/1 14:45): 3 张表 migration
- D7 ✓ (9/1 16:15): 库对管理 CRUD + admin + 2 template + base.html
- D8 ✓ (9/1 17:45): 5 AJAX 端点 + 4 service + pair_detail + 5 modal + JS
- D9 ✓ (9/1 18:15): R3 走当前配置 + signal + 8/13 教训应用修补
- D10 ✓ (9/2 10:30): 134 dev 端到端演练 5 Case + UnboundLocalError hotfix
- D11 (9/2 11-15): 134 dev 实战踩坑 6 hotfix
- D12 ✓ (9/2 17:30): 134 dev detail/119 JS ReferenceError 修复
- D13 ✓ (9/2 18:30): 多表 DDL 字段 diff bug 修复
- D14 ✓ (9/2 19:40): 推 110 prod 修复汪银和工单 (commit ed1c20c)
- D15 ✓ (9/2 20:30): 字符集 implicit/explicit 区分 (commit e939ffe)
- D16 ✓ (9/2 21:10): 推 D15 修复实战 110 prod c9236a0 (commit 289adc7)
- D17 ✓ (9/2 21:43): 验证 110 prod D15 修复实战生效
- **D18 ✓ (9/2 22:30): DDL 跨库同步 镜像/源工单 alert 块 (本次)**

## 下次推 prod checklist 必加 (D18 实战新发现)

1. **镜像工单 UX 必走 detail.html + views.py 2 文件**: 单一文件改 50% 行
   (D18 实战 8 行 context + 60 行 alert 块) 就够, 不用动 8/26 字段 diff
   inline 区域 (8/26 21:34 + 9/2 17:30 D12 修过) 也不冲突
2. **detail.html 改时必用 Python 脚本按行号精准插入**: 编辑器自动 indent
   空格会让 git diff 看着吓人, 实战 insert_after = line index, 然后
   lines[:idx+1] + alert + lines[idx+1:] 一次拼接
3. **镜像/源工单双向 alert 必加, 不能只加镜像工单侧**: 实战用户视角
   拿到镜像工单想跳回源工单, 源工单也想看触发了几个镜像工单
4. **ddl_sync app 不可用时 detail 页面不能 500**: 必 try/except 兜底,
   让 alert 块静默不显示, 跟 W1-D3 §9.3 实战 1 signal handler 兜底同套路
