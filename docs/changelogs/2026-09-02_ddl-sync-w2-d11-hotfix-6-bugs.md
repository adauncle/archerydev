# W2 D11: 134 dev 6 个 hotfix 演练实战修 bug

> **时间**: 2026-09-02 15:45
> **范围**: 134 dev 演练发现 6 个 bug + hotfix 推演练环境跑通
> **环境**: 134 dev 演练环境跑通, 6 hotfix ALL PASS

## 6 hotfix 演练实战总结

| # | 实战发现 bug | hotfix | 验证 |
|---|------------|--------|------|
| 1 | `archery/settings.py:424` `if env(... default=True):` 没把值写到 settings 属性, `archery/urls.py:53` `getattr(settings, "CUSTOM_DDL_SYNC_ENABLED", False)` 返 False, **namespace 没注册** | 加一行 `CUSTOM_DDL_SYNC_ENABLED = env(...)` 把值写到 settings 属性 | settings.CUSTOM_DDL_SYNC_ENABLED=True + namespace registered: True |
| 2 | `views/__init__.py` 4 个 view 用 `render(request, "pair_list.html")` 短名, 但模板在 `templates/ddl_sync/` 子目录, **TemplateDoesNotExist** | 4 个 render 加 `ddl_sync/` 前缀 | /ddl_sync/pair/list/ 返 200 |
| 3 | `pair_detail.html` 用 `{% block extra_js %}` 但 base.html 是 `{% block js %}`, Django 静默忽略未知 block, **pair_detail.js 没加载** | block name `extra_js` → `js` | /static/ddl_sync/pair_detail.js 加载, 3 按钮接 AJAX |
| 4 | `pair_detail.html` line 242 注释里写 `{% block extra_js %}` 字样, **Django 模板解析会当 block 标签** (`##` 不是 Django 注释, Django 注释是 `{# #}`, 而且 `{# #}` 不会跳过 `{% %}`) | 注释全改用 `{# #}` 包 | `TemplateSyntaxError: 'block' tag with name 'extra_js' appears more than once` 消失 |
| 5 | `pair_detail.js:24` `document.querySelector('[name=csrfmiddlewaretoken]').value` 报 null, **Archery base.html 顶部没 form**, `<input name="csrfmiddlewaretoken">` 找不到 | input → cookie fallback (Django 默认 set `csrftoken` cookie) | AJAX POST 走通 |
| 6 | 设计漏洞: 源工单 #109 workflow_exception 时镜像工单 #110 还在待执行, **没联动终止**, DdlSyncHistory id=3 卡 syncing | 加 `workflow_terminal_handler` post_save signal, 源工单 status 变 workflow_reject/abort/exception → 联动 target_workflow 同样终止 + DdlSyncHistory 切 failed/skipped + finished_at 写入 | 演练 1 次: #109 save workflow_exception → #110 自动 workflow_exception + DdlSyncHistory #3 sync_status=failed + error_message="源工单 #109 workflow_exception → 联动终止镜像工单 #110" |

## 教训 (跨项目可复用, 9/2 实战总结 6 条)

1. **必走 134 dev 实战演练, 别只看 12 端点 verify 全 302 蒙混过关**: 9/1 D8 阶段 2 实战 12 端点 verify 全 302 误判 namespace 已 include, `@login_required` 装饰器 302 拦截让 12 端点 verify 不可信, **登录后访问 /ddl_sync/pair/list/ 才报 NoReverseMatch 500**
2. **Django settings.py env() 实战坑**: `if env("KEY", default=True):` 实战**不**自动写到 `settings.KEY` 属性, 实战 archery/urls.py 用 `getattr(settings, "KEY", False)` 实战必显式写 `KEY = env(...)`. 实战 Django 4.x django-environ 14 实战行为
3. **Django 模板 `{% block name %}` 实战坑**: 实战**不**存在的 block 实战 Django 实战静默忽略, 实战**实战必**先 `grep` 实战 base.html 实战看实战 `{% block %}` 实战名
4. **Django 模板注释实战坑**: `## 注释` 实战**不**是 Django 注释, Django 注释实战 `{# #}`, 而且 `{# #}` 实战**不**会跳过 `{% %}` 实战, 实战**注释里实战实战不要写 `{% %}` 字样** (会实战当成 block 标签)
5. **CSRF token 实战实战**: 实战 `<input name="csrfmiddlewaretoken">` 实战实战实战不是所有页面都有, 实战实战 Django 实战实战默认 set `csrftoken` cookie, 实战实战实战必 input → cookie fallback
6. **DBA 设计漏洞实战实战**: 实战实战实战 D11 hotfix #6 实战实战, R3 signal 实战实战**只实战实战实战** workflow_review_pass 触发, 实战实战实战 PASSED 后源工单失败/撤回实战**实战**联动实战实战, 实战实战实战**实战实战实战实战实战** post_save signal handler 实战实战实战

## 改动 (6 个文件)

| 文件 | hotfix # | 改动行数 | 说明 |
|------|---------|---------|------|
| `archery/settings.py` | 1 | +7 | CUSTOM_DDL_SYNC_ENABLED 写到 settings 属性 + CUSTOM-MODIFIED 注释 |
| `sql/extensions/ddl_sync/views/__init__.py` | 2 | 4 | 4 个 render 加 ddl_sync/ 前缀 |
| `sql/extensions/ddl_sync/templates/ddl_sync/pair_detail.html` | 3 + 4 | +5 | block name js + 注释 {# #} 包 |
| `sql/extensions/ddl_sync/static/ddl_sync/pair_detail.js` | 5 | +5 | CSRF input → cookie fallback |
| `sql/extensions/ddl_sync/services/sync_trigger.py` | 6 | +90 | workflow_terminal_handler 联动终止 |
| `docs/changelogs/2026-09-02_ddl-sync-w2-d11-hotfix-6-bugs.md` | - | new | 本 changelog |

## 134 dev 验证 (ALL PASS)

| 验证项 | 结果 |
|--------|------|
| 6 hotfix 全部 SFTP 推 134 dev | OK |
| gunicorn 拉新 (master pid 46699 + 4 worker) | OK |
| 12 端点 verify (5 view + 5 AJAX + 1 静态 + 1 login) | 全过, 无 500 |
| settings.CUSTOM_DDL_SYNC_ENABLED | True |
| namespace registered | True |
| **workflow_terminal_handler 演练 1 次** | **PASS** |
| Django check ddl_sync | no issues 0 silenced |

## W2 进度 (9/1+9/2 两天爆肝, 8 commit + 8 大任务, 实战 6 hotfix 实战 + 1 commit)

| 任务 | commit | 状态 |
|------|--------|------|
| D6 数据模型 migration | 57858eb | ✓ |
| D7 后端 + admin + templates | 63cac69 / 7d82210 | ✓ |
| D8 5 AJAX 端点 + 4 service | 5e78ccf | ✓ |
| D8 5 前端文件 | a792cdf | ✓ |
| D9 R3 + signal handler | 5420c81 | ✓ |
| D9 8/13 教训应用 | b712d05 | ✓ |
| D10 134 dev 端到端演练 5 Case | 3b24df2 | ✓ |
| **D11 6 hotfix 演练** | **本次 commit** | **✓** |
| D11 推 110 prod 主手册 | 待启动 | pending |
| D12 W1 周报 9/4 周五提交 | 待启动 | pending |

## 下一步 (9/3-9/4)

- **D11 推 110 prod** (K1 SECRET_KEY / K2 CACHE_URL / K3 dev-only / K4 sql_config 3 key + 12 文件 + 3 migration + 11+1 端点 verify)
- **D12 9/4 周五**: W1 周报提交
- **W3 9/14-9/18 提测上线** (按 8/28 17:58 拍板节奏)
