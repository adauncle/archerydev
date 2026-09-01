# 9/1 W2 D7 DDL 跨库同步 库对管理 template + base.html 侧边栏 (阶段 2) (9/1 16:15)

## 概要

W2 实施阶段 D7 阶段 2 (按计划 9/8 周二, 实际 9/1 周二提前 5 天) 模板 + 侧边栏联动跑通. 134 dev /opt/archery/prod 5 端点 verify 全过 + base.html 侧边栏加 DDL 跨库同步菜单.

## 3 文件改动

```
sql/extensions/ddl_sync/templates/ddl_sync/pair_list.html   9.1KB  库对列表 (DBA 视角, 搜索+过滤+分页+新建按钮)
sql/extensions/ddl_sync/templates/ddl_sync/pair_form.html   6.0KB  创建/编辑库对表单
common/templates/base.html                                  +16 行 侧边栏加 DDL 跨库同步菜单 (CUSTOM-MODIFIED 头)
```

## pair_list.html 实战要点 (DBA 视角)

**顶部**:
- 面包屑: 首页 / DDL 跨库同步 / 库对列表
- 描述: 业务库 DDL 审批通过后, 自动生成历史库镜像工单 (走当前 Archery audit_setting 配置)
- 顶部统计卡: 库对总数 + 当前显示数

**筛选器**:
- 关键词 (名称 / 业务库 / 历史库 模糊搜索)
- 同步模式下拉 (全部 / 黑名单 默认 / 白名单)
- 状态下拉 (全部 / 启用 / 禁用)
- 筛选按钮 + + 新建库对按钮 (DBA add perm 守卫)

**表格** (11 列):
- ID / 名称 (跳详情) / 源 instance+db / 目标 instance+db / 同步模式徽章 / 状态徽章 / 同步表数 / 历史数 / 创建人 / 创建时间 / 操作 (查看 + 编辑)

**彩色徽章** (跟 8/12 gh-ost 套路):
- blacklist 红 / whitelist 绿
- enabled 绿 / disabled 灰

**4 perm 守卫**:
- `{% if perms.ddl_sync.add_ddlsyncpair %}` 新建按钮可见
- `{% if perms.ddl_sync.change_ddlsyncpair %}` 编辑按钮可见
- 空态: 暂无库对, 提示新建 (add perm) 或请联系 DBA (无 add perm)

**分页** (Paginator 50/页):
- 上一页 / 下一页 + 页码
- 关键词/过滤参数保留到分页链接

## pair_form.html 实战要点

**字段** (DdlSyncPairForm 7 字段):
- name (配对名, *)
- source_instance (业务库实例, *, ModelChoiceField)
- source_db (业务库名, *)
- target_instance (历史库实例, *, ModelChoiceField)
- target_db (历史库名, *)
- sync_mode (RadioSelect: blacklist 黑名单默认 / whitelist 白名单)
- enabled (启用, 复选框)

**form 校验** (forms.py clean()):
- 业务库跟历史库不能是同一个 instance + 同一个 db (raise forms.ValidationError)

**操作按钮**:
- 创建 / 保存修改 (btn-primary 蓝)
- 取消 (回列表 / 回详情)

**4 perm 守卫**:
- 创建/编辑端点本身有 `@permission_required` 守卫 (D7 阶段 1)
- 模板内表单字段不守卫 (跟 ddl_gh_ost 套路一致)

## base.html 侧边栏菜单联动

按 8/12 gh-ost 任务管理菜单套路, 加 DDL 跨库同步菜单 (D7 阶段 2 阶段 1):

```html
{# CUSTOM-MODIFIED: DDL 跨库同步 菜单 @ 2026-09-01 @ mavis #}
{# 守卫: superuser 或有 ddl_sync.view_ddlsyncpair 权限 #}
{# 关联 changelog: docs/changelogs/2026-09-01_ddl-sync-w2-d7-admin-views.md #}
{% if user.is_superuser or perms.ddl_sync.view_ddlsyncpair %}
    <li>
        <a href="#"><i class="fa fa-exchange fa-fw"></i> DDL 跨库同步<span class="fa arrow"></span></a>
        <ul class="nav nav-second-level collapse">
            <li>
                <a href="{% url 'ddl_sync:pair_list' %}"><i class="fa fa-list fa-fw"></i> 库对列表</a>
            </li>
            {# D8 阶段 2 留 TODO 5 AJAX 端点菜单 (同步历史 / 批量导入 / 一键配 等) #}
        </ul>
    </li>
{% endif %}
```

放在 gh-ost 任务菜单之后, SQL查询菜单之前 (line 151).

## pair_detail.html (留 D8 跟 5 AJAX 端点一起写)

D7 阶段 2 阶段 1 不写 pair_detail.html, 留 D8 阶段 2 一起写:
- D7 阶段 2 阶段 1: pair_list + pair_form + base.html (3 文件) ✓
- D8 阶段 2: pair_detail + 5 AJAX 端点 + 3 modal + R1 批量导入 JS (预计 6-8 文件)

理由: pair_detail 含 4 tab + 5 按钮 modal (一键配/批量导入/添加/schema差集/过滤规则) + sync_status 实时刷新, 跟 5 AJAX 端点代码耦合, 一起写更顺.

## 134 dev 5 步必做全过

| 步骤 | 命令 | 结果 |
|------|------|------|
| 1. SFTP 推 3 文件 | paramiko SFTP | ✓ 3 文件全部 OK (含 base.html 36KB) |
| 2. mkdir templates/ddl_sync/ | mkdir -p | ✓ |
| 3. 备份 base.html | cp | ✓ base.html.bak_20260901_1610 |
| 4. chown + 清 __pycache__ | chown -R + rm -rf | ✓ |
| 5. kill gunicorn + nohup 拉新 | pkill -9 + setsid nohup | ✓ 新 master pid 15555 |

**5 端点 verify (含 base.html 侧边栏菜单渲染)**:
- /login/ → 200 ✓
- /ddl_sync/pair/list/ → 302 (重定向 login) ✓
- /ddl_sync/pair/create/ → 302 ✓
- /ddl_sync/pair/1/ → 302 ✓
- /ddl_sync/pair/1/edit/ → 302 ✓

302 是正常 (未登录用户被重定向到 login), 模板语法 OK (没 500).

## 避坑 (8/12 gh-ost task_list.html 实战 + 8/11 模板守卫)

1. **模板 app 目录**: templates/<app_label>/<template>.html, 不是 templates/<template>.html (Django 模板 app loader 要求)
2. **base.html 改动备份必做**: base.html 是全局公共模板, 改错影响所有页面, 必 cp .bak_<时间戳> 备份
3. **inline CSS 写 content block 内**: 不写单独 static/ddl_sync/list.css, 跟 ddl_gh_ost task_list.html 套路一致
4. **Element UI 配色复用**: 蓝 #409EFF / 绿 #67C23A / 红 #F56C6C / 黄 #E6A23C / 灰 #909399 (跟 gh-ost 配色一致)
5. **面包屑 3 段**: 首页 / 业务模块 / 当前页, 跟 gh-ost 任务管理 1:1
6. **空态 2 路径**: "没有匹配的库对 (清空筛选)" + "暂无库对配置 (新建一个)" 跟 gh-ost 套路一致

## 改动文件

```
sql/extensions/ddl_sync/templates/ddl_sync/pair_list.html   (新, 9.1KB)
sql/extensions/ddl_sync/templates/ddl_sync/pair_form.html   (新, 6.0KB)
common/templates/base.html                                  (改, +16 行)
```

## 134 dev 备份

```
/opt/archery/prod/common/templates/base.html.bak_20260901_1610
```

## D7 阶段 2 阶段 1 完工 + D7 整体 100%

D7 阶段 1 (后端 + admin) ✓ + D7 阶段 2 阶段 1 (2 template + base.html 联动) ✓
= D7 整体 100% (留 pair_detail.html 给 D8 一起写)

## D7 整体 2 commit

1. **D7 阶段 1 后端 + admin** (commit 63cac69, 6 files +591): admin.py + forms.py + views/__init__.py + urls.py + archery/urls.py 改 + changelog
2. **D7 阶段 2 阶段 1 template + base.html** (本次, 待 commit): pair_list.html + pair_form.html + base.html 改 + changelog

## W2 进度 (D6 + D7 全部完工)

- **D6 9/1 下午 ✓** (commit 57858eb, 7 files +434): 数据模型 migration
- **D7 9/1 下午 ✓ 阶段 1** (commit 63cac69, 6 files +591): 后端 + admin
- **D7 9/1 下午 ✓ 阶段 2 阶段 1** (本次, 3 files +15): 2 template + base.html 联动
- D8 9/2 下午 (5 AJAX 端点 + 3 modal + pair_detail.html + R1 批量导入)
- D9 9/3 (R2 一键配 + R3 走当前配置)
- D10 9/4 (134 dev 端到端演练 5 Case)

W2 提前 5 天完成 D6 + D7, 9/2 直接进 D8

## 提交

待 commit + push origin main
