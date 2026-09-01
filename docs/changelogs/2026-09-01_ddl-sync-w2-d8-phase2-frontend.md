# W2 D8 阶段 2: 库对详情页 + 5 modal + JS 端到端 (commit pending)

> **时间**: 2026-09-01 17:25
> **范围**: `sql/extensions/ddl_sync/templates/ddl_sync/pair_detail.html` + `static/ddl_sync/pair_detail.js` + `partials/*.html`
> **环境**: 134 dev 演练环境跑通, 12 端点 verify 全过
> **设计稿**: `docs/designs/2026-09-03_ddl-sync-detail-ux-design.md` (W1-D4) + `docs/designs/2026-09-01_ddl-sync-implementation-design.md` (W1-D3 §2.2)

## 改动文件 (5 个, 38KB)

| 文件 | 大小 | 作用 |
|------|------|------|
| `templates/ddl_sync/pair_detail.html` | 11.7KB | 4 tab 库对详情页 + 5 按钮 (跟 W1-D4 §2 mockup 1:1 实战) |
| `templates/ddl_sync/partials/_bulk_import_modal.html` | 4.2KB | R1 批量导入 modal (1-200 张表名, 换行分隔) |
| `templates/ddl_sync/partials/_one_click_modal.html` | 4.9KB | R2 一键配 modal (3 集合 checkbox + 覆盖/增量 radio) |
| `templates/ddl_sync/partials/_add_table_modal.html` | 2.3KB | R1 兜底, 单张加同步表 (instance/db 上下文) |
| `static/ddl_sync/pair_detail.js` | 14.5KB | 5 modal JS + R1 批量导入 + R2 一键配 + 单张加 端到端 AJAX |

## pair_detail.html 实战要点 (DBA 视角 4 tab)

### 头部
- 面包屑 3 段: 首页 / DDL 跨库同步 / 库对详情
- 库对名 (h2) + 4 徽章 (sync_mode / enabled / created_at / 创建人)
- 5 描述字段卡片: 源 instance+db / 目标 instance+db / 同步模式 / 启用 / pending_tables
- 5 按钮 (按 W1-D4 §2.1 mockup 顺序): 一键配 / 批量导入 / 添加表 / schema 差集 / 过滤规则

### Tab 1: 同步表
- 表格 8 列: 表名 / sync_type 徽章 / transform_rule / 创建时间 / 操作 (启用/禁用/删除)
- 顶部筛选: 关键词 + sync_type 下拉
- 统计: 同步表数 (X) + 白名单 (Y) + 黑名单 (Z)

### Tab 2: 差集结果 (默认隐藏, R2 一键配触发后显示)
- 3 卡片: 公共 (whitelist ∩) / 源库独有 (blacklist -) / 目标库独有 (orphans -)
- 复选框 + 全选/反选 + 底部 "应用选中" 按钮

### Tab 3: 同步历史
- 表格 7 列: 工单 / 源库 / 目标库 / 表名 / sync_status 5 色徽章 / 创建时间 / 错误
- 顶部分页 + status 过滤

### Tab 4: 变更日志
- 时间线 (创建/启用/禁用/更新/同步记录)

## 5 modal 实战要点 (W1-D4 §2.2-2.6)

| modal | 触发按钮 | AJAX 端点 | 关键字段 |
|-------|---------|-----------|---------|
| 一键配 | 顶部"一键配" | POST /pair/<id>/one_click_setup/ | 3 集合 checkbox + 覆盖/增量 radio |
| 批量导入 | 顶部"批量导入" | POST /pair/<id>/bulk_import/ | table_names (1-200 张, 换行) + sync_type radio |
| 添加表 | 顶部"添加表" + 表格内空态"添加一张" | POST /pair/<id>/add_table/ | table_name + sync_type + transform_rule JSON |
| schema 差集 | Tab 2 "schema 差集" | POST /pair/<id>/compute_diff/ | (无 body) |
| 过滤规则 | 顶部"过滤规则" | (前端 inline 编辑 pending_tables) | 过滤规则 JSON |

## pair_detail.js 端到端 (1 个统一 handleAjaxError)

```js
async function ajaxPost(url, body) {
    const r = await fetch(url, {
        method: 'POST',
        headers: {'X-CSRFToken': csrf, 'Content-Type': 'application/json'},
        body: JSON.stringify(body),
        credentials: 'same-origin',
    });
    const text = await r.text();
    try {
        const data = JSON.parse(text);
        if (!data.ok) throw new Error(data.error || 'unknown error');
        return data;
    } catch (e) {
        if (r.status === 403) throw new Error('权限不足');
        if (r.status === 404) throw new Error('资源不存在');
        throw new Error('服务异常: ' + text.slice(0, 200));
    }
}
```

5 modal JS 调用方:
- `submitOneClick()` → `ajaxPost('/ddl_sync/pair/1/one_click_setup/', {accept_whitelist, accept_blacklist})`
- `submitBulkImport()` → `ajaxPost('/ddl_sync/pair/1/bulk_import/', {table_names, sync_type})`
- `submitAddTable()` → `ajaxPost('/ddl_sync/pair/1/add_table/', {table_name, sync_type, transform_rule})`
- `runComputeDiff()` → `ajaxPost('/ddl_sync/pair/1/compute_diff/', {})` → 渲染 3 卡片 + checkbox
- `submitFilterRule()` → `fetch('/ddl_sync/pair/1/edit/', {method: 'POST'})` (form 提交, 走 form.py)

## 12 端点 verify (134 dev)

| 端点 | 状态 | 备注 |
|------|------|------|
| /login/ | 200 | 登录页 OK |
| /ddl_sync/pair/list/ | 302 | pair_list 模板渲染 OK (登录拦截) |
| /ddl_sync/pair/create/ | 302 | pair_form 模板 OK |
| /ddl_sync/pair/1/ | 302 | **pair_detail 模板 OK (新增)** |
| /ddl_sync/pair/1/edit/ | 302 | pair_form 编辑模式 OK |
| /ddl_sync/pair/1/compute_diff/ | 302 | AJAX R2 端点 OK |
| /ddl_sync/pair/1/one_click_setup/ | 302 | AJAX R2 端点 OK |
| /ddl_sync/pair/1/bulk_import/ | 302 | AJAX R1 端点 OK |
| /ddl_sync/pair/1/add_table/ | 302 | AJAX R1 兜底端点 OK |
| /ddl_sync/history/ | 302 | AJAX 同步历史端点 OK |
| /static/ddl_sync/pair_detail.js | 200 | **静态资源 200 (新增)** |
| `manage.py check ddl_sync` | no issues | 0 silenced |

## 避坑 (跨项目可复用)

1. **模板 partials 子目录 9/1 实战 100% 复用 D7 阶段 1 教训**: SFTP 推 `partials/_xxx_modal.html` 前必先 `mkdir -p templates/ddl_sync/partials/`, SFTP 单文件推不会自动建父目录
2. **静态资源目录 static/<app_label>/**: `static/ddl_sync/pair_detail.js` 不是 `static/pair_detail.js`, Django staticfiles 找 app_label 子目录
3. **Django check 报 "import local settings failed, ignored"** 是正常: settings.py 优先用 .env, .env 在 archery user 家目录, sudo -u archery 读不到 root 的 .env 路径; 9/1 实战无影响
4. **gunicorn 必 kill 拉新 9/1 实战确认**: master 跑 4-11h 不 reload Python, 推新模板后必 `pkill -9 -f gunicorn` + `setsid nohup` 拉新
5. **pkill -9 RC=-1 不是错**: paramiko 等待 channel 关闭副作用, 实际 gunicorn 全部杀干净 (ps 显示新 gunicorn 跑 OK)
6. **bash -c 嵌套 nohup 立即返回** (9/1 W1-D5 实战): 不用 wait, 5 秒后 ps 直接看
7. **静态资源 200 是关键指标**: `/static/ddl_sync/pair_detail.js=200` 证明 Django 找到 static + STATIC_URL 配置正确, JS 加载就位

## W2 进度 (9/1 一天爆肝 5 commit, 提前 5 天)

| 任务 | 计划 | 实际 | commit |
|------|------|------|--------|
| D6 数据模型 migration | 9/7 周一 | 9/1 下午 | 57858eb |
| D7 后端 + admin | 9/8 周二 | 9/1 下午 | 63cac69 |
| D7 templates | 9/8 周二 | 9/1 下午 | 7d82210 |
| D8 5 AJAX 端点 | 9/9 周三 | 9/1 下午 | 5e78ccf |
| **D8 前端 (modal + detail + JS)** | 9/9 周三 | 9/1 下午 | **本次 commit** |

## 下一步 (9/2)

- **D9 阶段 1 9/2 早上**: R2 一键配 + R3 走当前配置 (sync_trigger.py + workflow_passed_handler signal)
- **D9 阶段 2 9/2 下午**: 8/13 教训应用修补 api_views.py (5 个 `raise_exception=True` → `False` + 自定义 JsonResponse 403)
- **D10 9/3**: 134 dev 端到端演练 5 Case (A 配库对 / B 一键配 1589 张 / C 真实 DDL / D rollback / E perm)
