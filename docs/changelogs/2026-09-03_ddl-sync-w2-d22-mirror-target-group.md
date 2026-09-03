# DDL 跨库同步 W2 D22: 镜像工单 group_id 走历史库组 (DBA 显式配 target_group)

> 日期: 2026-09-03 14:30
> 阶段: W2 实施阶段 (D22, 9/3 14:00 业务 RD 反馈 + 排查根因 + 实战修通)
> 模块: `sql/extensions/ddl_sync/`
> 关联: W1-D3 §5.1 设计稿原意 + D9 实战避坑 1

## 背景

W1-D3 §5.1 设计稿拍板: 镜像工单审批流走**历史库组** (target_instance.group_id),
走当前 `WorkflowAuditSetting (SQL_REVIEW)` 拿审流配置, 0 额外代码.

D9 实战发现 **Archery Instance 是 ManyToMany `ResourceGroup`, 没 group_id 字段**,
D9 实战避坑 1 fallback 走 `source_workflow.group_id` (业务组),
**违反了"走历史库审批流"的设计**.

## 症状 (9/3 14:00 用户反馈 + D22 排查)

用户期望"镜像工单走历史库的审批流", 但:
- 截图: /config/ 工单审核配置页, 组选 "prod core for 历史库", 当前审批流程 = DBA (单一审批)
- 但 D9 实战创建出来的镜像工单 (wf#121 演练) 走的是 group 25 "测试组" → audit_auth_groups='14,3'
- 不是用户期望的 group 22 "prod core for 历史库" → '3'

## 根因

D9 实战 `sync_trigger.py` (W1-D3 §5.1 拍板 + 8/27 实战避坑):
```python
group_id=source_workflow.group_id,      # 业务组, 错
group_name=source_workflow.group_name,   # 业务组, 错
```

Archery `sql.models.Instance.resource_group = ManyToManyField(ResourceGroup)`,
**Instance 没 group_id 字段** (M2M 关联, 一个 instance 可属于多个组, 设计上不该硬选一个).

D9 实战时不知道"prod core for 历史库"这个组跟历史库 instance 的关联,
退而求其次用 source_workflow.group_id (业务组), 导致镜像工单**走业务组审流**.

D9 实战 D10 演练 1 (Case C) 实战发现这个 fallback:
- wf#106 (业务库) → wf#107 (镜像工单) → audit_handler.create_audit() 走 group 8 配的 fallback
- group 8 没配 WorkflowAuditSetting, fallback 留空 audit_auth_groups
- 实战避坑 3: "MySQL audit_setting 没配 fallback", 走业务组没配审流就留空

**真正根因**:
- 设计上要"走历史库组", 但 Archery Instance 是 M2M ResourceGroup, 不能硬选一个
- D9 没新加字段, fallback 用 source_workflow.group_id
- **缺 DBA 显式配 target_group 的入口**

## 修法

DBA 拍板 A 方案 (9/3 14:05 拍板): **DdlSyncPair 加 `target_group` 字段 (FK ResourceGroup) + `target_group_name` (CharField)**, DBA 配库对时显式选.

### 1. models.py 加字段 (DdlSyncPair)
```python
target_group = models.ForeignKey(
    "sql.ResourceGroup", on_delete=models.PROTECT,
    related_name="sync_pair_target_group",
    null=True, blank=True,
    verbose_name=_("镜像工单审批组"),
    help_text="DBA 配库对时显式选 (Instance 是 M2M ResourceGroup, 不能自动猜); 走当前 group_id 的 WorkflowAuditSetting (SQL_REVIEW) 拿审流",
)
target_group_name = models.CharField(_("镜像工单审批组名"), max_length=100, blank=True, default="")
```

### 2. forms.py DdlSyncPairForm 加字段
```python
target_group = forms.ModelChoiceField(
    queryset=ResourceGroup.objects.all().order_by("group_id"),
    label="镜像工单审批组",
    help_text="DBA 显式选 (Instance 是 M2M ResourceGroup, 不能自动猜); 走当前 group_id 的 WorkflowAuditSetting (SQL_REVIEW) 拿审流, 如 'prod core for 历史库' (DBA 单一审批)",
)

def clean(self):
    ...
    # D22: 镜像工单审批组必填 (没填会导致 sync_trigger fallback 走 source_workflow.group_id,
    # 走业务组审批, 违反"镜像工单走历史库审批流"设计)
    if not target_group:
        raise forms.ValidationError(
            "镜像工单审批组必填 (DBA 显式选, 走历史库组审批流, "
            "不能 fallback 走业务组, 否则 wf#121 那种 bug 会重现)"
        )

def save(self, commit=True):
    # D22: 同步 target_group_name (跟 group_id 配对, 给 SqlWorkflow.group_name 用)
    instance = super().save(commit=False)
    if instance.target_group:
        instance.target_group_name = instance.target_group.group_name
    if commit:
        instance.save()
        self.save_m2m()
    return instance
```

### 3. pair_form.html 加下拉
在 `target_db` 字段后加 `target_group` 下拉, label = "镜像工单审批组" 必填.

### 4. pair_detail.html 显示当前 target_group
在历史库名行后加:
```html
<tr>
  <th>镜像工单审批组</th>
  <td>
    {% if pair.target_group %}
      <strong>{{ pair.target_group.group_name }}</strong>
      <span class="text-muted">(group_id={{ pair.target_group.group_id }})</span>
    {% else %}
      <span class="ddlsync-badge ddlsync-badge-warning">未配</span>
      <span class="text-danger">⚠ D22 升级前的老库对, 镜像工单当前走 source_workflow.group_id (业务组), 违反设计, 需手动配</span>
    {% endif %}
  </td>
</tr>
```

### 5. sync_trigger.py 改用 pair.target_group
```python
# D22: pair.target_group 必填, 没配直接抛错 (DBA 拍板 A 方案: 强制配, 不 fallback 走业务组)
if not pair.target_group:
    raise TargetGroupNotConfiguredError(
        f"DdlSyncPair id={pair.id} ({pair.name}) 没配 target_group, "
        f"镜像工单不能走业务组 (违反 D22 设计), "
        f"请 DBA 在配库对页 pair_form.html 显式选镜像工单审批组 (如 'prod core for 历史库')"
    )
target_group = pair.target_group  # ResourceGroup object

target_workflow = SqlWorkflow.objects.create(
    ...
    group_id=target_group.group_id,           # D22: 改走历史库组
    group_name=target_group.group_name,       # D22: 改走历史库组
    ...
)
```

`workflow_passed_handler` 现有 `except Exception` 已自动捕获 `TargetGroupNotConfiguredError`,
写 DdlSyncHistory sync_status='failed' + error_message="创建镜像工单失败: DdlSyncPair id=N 没配 target_group, 请 DBA 配..."
(消息已经够清晰, 不需要单独 except 路径)

## 验证 (9/3 14:30 134 dev 演练)

### 演练 1: 老镜像工单 SQL UPDATE 兜底

`scripts/_archive/_d22_verify_schema.py` 演练 1:
- 配 pair#1.target_group = group 22 (prod core for 历史库)
- SQL UPDATE wf#121 group_id=22 + group_name="prod core for 历史库"
- 删老 audit (group 25 配的) + 重新 create_audit
- 查 wf#121 audit_auth_groups

演练 1 实战结果:
```
wf#121 改前: group_id=25, group_name=测试组, audit_auth_groups='14,3'
wf#121 改后: group_id=22, group_name=prod core for 历史库
deleting old audit (audit_auth_groups='14,3')
create_audit 成功
wf#121 改后: group_id=22, audit_auth_groups='3'
audit 改后: group_id=22, audit_auth_groups='3'
```

**wf#121 走 group 22 '3' = "prod core for 历史库" DBA 单一审批** ✅

### 演练 2: 新镜像工单走 sync_trigger 真实路径

`scripts/_archive/_d22_verify_schema.py` 演练 2:
- 调 `create_target_workflow(source_swf=wf#120, pair#1, transformed_ddl)` (D22 走 pair.target_group)
- source_swf group_id=25 (业务组), pair.target_group=group 22 (历史库组)
- 期望 target_wf group_id=22, audit_auth_groups='3'

演练 2 实战结果:
```
source_wf: id=120, workflow_name=test, group_id=25
create_target_workflow 成功: target_wf id=126
  group_id=22, group_name=prod core for 历史库
  instance=测试 MySQL 8.0, db_name=hly_accesscard_history
  audit.audit_auth_groups='3'
  workflow.audit_auth_groups='3'
```

**D22 新镜像工单 wf#126 走 group 22 '3' = "prod core for 历史库" DBA 单一审批** ✅

演练 2 临时建的 wf#126 已删 (cleanup 脚本验证 wf#126 deleted).

### 验证 3: /ddl_sync/pair/1/ 渲染

`scripts/_archive/_d22_cleanup_and_restart.py` 验证:
- gunicorn 拉新 (master + 4 worker)
- /ddl_sync/pair/1/ 渲染
- target_group "prod core for 历史库" + group_id=22 显示正常
- Status: 200, length: 58607

```
target_group name displayed              count=1
target_group group_id displayed          count=1
source instance name                     count=15
target instance name                     count=13
```

✅ pair_detail.html 镜像工单审批组行渲染正常

## 改动文件 (6 个)

| 文件 | 改动 |
|------|------|
| `sql/extensions/ddl_sync/models.py` | DdlSyncPair 加 `target_group` (FK ResourceGroup) + `target_group_name` (CharField) |
| `sql/extensions/ddl_sync/migrations/0002_ddlsyncpair_target_group_and_more.py` | 自动生成, + Add field target_group + target_group_name |
| `sql/extensions/ddl_sync/forms.py` | DdlSyncPairForm 加 target_group ModelChoiceField + clean 必填校验 + save 同步 target_group_name |
| `sql/extensions/ddl_sync/templates/ddl_sync/pair_form.html` | target_db 字段后加 target_group 下拉 (必填) |
| `sql/extensions/ddl_sync/templates/ddl_sync/pair_detail.html` | 历史库名行后加"镜像工单审批组"显示行 + 警示老库对未配 |
| `sql/extensions/ddl_sync/services/sync_trigger.py` | 新增 `TargetGroupNotConfiguredError` + create_target_workflow 改走 pair.target_group |

## 同源 entry

- 8/31 v0.5.0-alpha 设计稿 (W1-D3 §5.1 拍板: 走历史库组)
- 9/1 W2 D9 sync_trigger 初版 (避坑 1: Instance 是 M2M ResourceGroup fallback 业务组)
- 9/1 W2 D10 Case C 演练 1 (实战发现 group 8 没配 fallback 留空 audit_auth_groups)
- 9/2 D18-D21 镜像工单 UX 完整链路 (commit 55ec7fa → a4abf01 → 6d41605 → 5de07ba)
- 9/3 D21 sync_trigger.py review_content placeholder (commit 5de07ba)

## D22 实战新发现 (跨项目可复用, 5 条)

1. **Archery Instance 是 ManyToMany ResourceGroup 没 group_id 字段** (D9 实战避坑 1): 二次开发要"走某个组"必须新加字段, 不能 fallback 走 source_workflow.group_id
2. **二次开发"走某个组"必走显式配字段, 不 fallback**: 业务方拍板"走 A 组"就必配, 不允许 fallback 走默认 (否则 D22 那种"走业务组"违反设计的 bug 反复出现)
3. **DBA 拍板 A 方案 (新加字段 + 显式配) 比 B (自动找) 干净**: Instance M2M 关联, 自动找 group_name 含 "历史库" 依赖名字约定, 改名就挂; 新加字段 + DBA 显式配是 schema 级显式, 不依赖数据约定
4. **D22 老库对 SQL UPDATE 兜底套路**: D22 实战给 wf#121 (老的镜像工单) 手动 SQL UPDATE group_id + delete 老 audit + 重新 create_audit, 实战可行 (DBA 演练 1 已验证), 老镜像工单走新审批流
5. **D22 实战 1+2 演练证明 Django ORM 演练 2 临时工单必清理**: 演练 2 建的 wf#126 不是真实同步产生的, 演练完必 delete 避免污染数据 (cleanup 脚本 verify wf#126 deleted)

## D22 实战踩坑 (3 条)

1. **D22 makemigrations 必带 ddl_sync app label**: `python manage.py makemigrations ddl_sync` 不能 makemigrations 不带 label, 会生成所有 app 的 migration 误报冲突
2. **PowerShell GBK 终端 unicode escape regex 演练问题**: 演练 3 /ddl_sync/pair/1/ 验证 "D22 new label" count=0 (PowerShell GBK 终端 unicode escape 编码问题, 不是数据问题), 用 ASCII label 替代更稳 (跟 D21 实战踩坑 3 复用)
3. **D22 老库对 migration 必加 null=True**: 老的 DdlSyncPair 行 (D22 之前) 不会有 target_group 字段值, 必 null=True + blank=True 让 migration 不破坏老数据; 然后 DBA 手动配新值 (演练 1 SQL UPDATE 走新审批流)

## 待办

1. 推 110 prod (D22 一次性推 6 文件 + migration 0002):
   - models.py + migration 0002 + forms.py + sync_trigger.py + pair_form.html + pair_detail.html
   - 推前必查 110 prod pair 表是不是空, 空就 makemigrations + migrate, 已有 pair 行就 migration 走完 manual UPDATE 配 target_group
2. 110 prod 推完后 D22 老 pair SQL UPDATE 兜底: 找 prod 配的 pair, SQL UPDATE target_group + 老镜像工单 group_id + delete audit + 重新 create_audit
3. wf#119/wf#121 status 分裂根因排查 (D18 实战挂账):
   - wf#118=workflow_finish, wf#119=workflow_abort, DdlSyncHistory#8=syncing
   - wf#120=workflow_finish, wf#121=workflow_abort, DdlSyncHistory#9=syncing
   - D22 实战演练 1 给 wf#121 改 group 22 + 重新 create_audit, status 还是 workflow_abort (演练发现 status 没改), D11 联动终止 signal 设计漏洞待 D23 排查
4. 110 prod 推完后 D23: 排查 wf#121 status=workflow_abort 根因 (D11 联动终止 signal 应该改 status, 但实战只 update_fields=['status'], D11 设计漏洞)

## D22 实战后 W2 状态

D6 数据模型 → D7 库对管理 → D8 AJAX 端点 + 前端 → D9 R3 + signal → D10-D12 134 dev 演练 → D13 多表 diff → D14 推 110 prod → D15 字符集 → D16 推 D15 修复 → D17 验证 → D18 alert 块 → D19 alert SQL → D20 挪位置 → D21 placeholder → **D22 镜像工单 group_id 走历史库组 (target_group 字段)**

## D22 实战后 134 dev gunicorn pids

5054 (master) + 4 worker 5057/5073/5074 (D22 cleanup 拉新)

## D22 实战后 134 dev pair#1

- pair#1.target_group = ResourceGroup id=22 "prod core for 历史库"
- pair#1.target_group_name = "prod core for 历史库"
- 老镜像工单 wf#121 group_id=22, audit_auth_groups='3' (DBA 单一审批, 演练 1 SQL UPDATE + 重新 create_audit)
- 134 dev 演练临时 wf#126 已删 (cleanup 验证)

## D22 实战备份

`/backup/d22_20260903_1430/sync_trigger.py.bak` (待 134 dev backup 路径)
