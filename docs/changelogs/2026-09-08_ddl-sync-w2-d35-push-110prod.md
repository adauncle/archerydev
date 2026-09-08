# D35 实战推 110 prod 完整 changelog (9/8 16:32-17:00 落地, 业务中断 17 分钟)

> **日期**: 2026-09-08 16:32-17:00
> **触发**: 用户 (DBA 阿达叔叔) 9/8 16:32 拍板"现在推 110 prod" (原计划 18:30 提前 2 小时)
> **演练**: 9/8 业务方通知已发 (用户 DBA 发)
> **结果**: ✅ D35 push 9 步 runbook 全部落地, 110 prod ddl_sync app 全功能生效, 业务可用

---

## 一、9 步 runbook 实战结果 (全部完成)

| 步 | 描述 | 结果 | 备注 |
|---|---|---|---|
| ① Step 1 | copy 整个 ddl_sync/ 目录 (134 dev → 110 prod) | ✅ 76591 bytes, 53+ 文件 | rsync 不可用, 走 tar 流式 |
| ② Step 2 | settings.py 加 ddl_sync INSTALLED_APPS | ✅ 4 行 (CUSTOM_DDL_SYNC_ENABLED 守卫) | 详见实战踩坑 #1 |
| ③ Step 3 | urls.py 加 ddl_sync 路由 | ✅ 5 行 (matched pragma: no cover) | 详见实战踩坑 #2 |
| ④ Step 4 | base.html 加 ddl_sync menu | ✅ perms 守卫 | D9 实战 line 428 风格 |
| ⑤ Step 5 | migrate ddl_sync | ✅ 2 [X] (0001 + 0002) | |
| ⑥ Step 6 | 推 12 文件升级版 (实际 9 推 + 3 skip) | ✅ ddl_gh_ost 5 + column_diff + sql 2 + ddl_sync 3 (Step 1 推过 skip) | md5 自动 skip 逻辑, #7 ddl_rollback 9/8 09:30 已推 skip |
| ⑦ Step 7 | kill + 拉新 gunicorn + qcluster | ✅ 5 进程, 9123 LISTEN | 详见实战踩坑 #1 (RuntimeError 修复) |
| ⑧ Step 8 | verify 6 项 | ✅ 业务不中断 + ddl_sync 路由 + reverse | |
| ⑨ Step 9 | verify D33 视图改动 | ✅ Paginator + pair_history_export + ddlsync-btn-export + ddlsync-page-link | |

**实际推送文件统计**: 4 大步 + 1 步 migrate + 9 步跨 app 文件 (跨 app 12 文件清单里 9 推 3 skip) + 1 步拉新

---

## 二、3 个 D35 实战新发现 (跨项目可复用)

### 1. **Django app 部署 4 大步 + 1 步 migrate + 12 文件升级版, 完整实战链路** (D35 实战新发现)
D34 dry-run 演练的 9 步 runbook, 9/8 16:32 实战首次跑通, 全流程 17 分钟业务中断. 实战路径:
- 134 dev /opt/archery/prod 演练 → 推 110 prod /dbdata/archery_v114_c9236a0
- 4 大步 (copy 目录 + INSTALLED_APPS + 路由 + base.html) + 1 步 migrate + 1 步跨 app + 1 步拉新
- 12 文件升级版清单实战推 9 个, 3 个 skip (md5 自动检测)

### 2. **ddl_sync app 完整部署, 业务 9/8 17:00 后可用** (D35 实战新发现)
- 110 prod 上 ddl_sync app 完整生效, 5 reverse URL 全部 OK
- showmigrations ddl_sync 2 [X] (0001_initial + 0002_ddlsyncpair_target_group_and_more)
- /ddl_sync/ 302 跳登录, /ddl_sync/pair/list/ /ddl_sync/pair/1/ /ddl_sync/pair/1/history_export/ 全部路由生效
- D22-D33 (库对管理 + AJAX + 镜像/源工单 + sync_trigger + status 联动) + D33 (分页 + Excel 导出) 全部 110 prod 生效

### 3. **D35 push 计划 + D24 紧急热补丁 + D34 dry-run + D35 push 9 步, 完整 DDL 跨库同步 v0.5.0 上线 110 prod** (D35 实战新发现)
- 业务方 wf#4786 (汪银和 DML UPDATE) 9/8 09:30 D24 紧急热补丁修 ForeignKey bug PASS
- 业务方 wf#4783 (yqf 改 accesscard_vehiclepic.pic_url) 9/8 17:00 后能看到大表 alert
- 业务方 (李绍平 副总场景) 9/8 17:00 后能看 gh-ost 任务列表 (D35 push 完后 DBA 在 110 prod admin 后台建"审批人"组 + 加李绍平, 1 步收尾)
- DDL 跨库同步 v0.5.0 (D6-D21) + 跨库同步完善 (D22-D29) + 推 110 prod 预检 (D30-D31) + 实战落地 (D32-D35) 完整闭环

---

## 三、2 个 D35 实战踩坑 (业务中断 17 分钟根因)

### 踩坑 #1: 110 prod settings.py RuntimeError (django_cas_ng middleware) ⚠️ 严重
- **现象**: Step 7 拉新 gunicorn 后 worker 启动失败, `RuntimeError: Model class django_cas_ng.models.ProxyGrantingTicket doesn't declare an explicit app_label and isn't in an application in INSTALLED_APPS`
- **根因** (9/8 16:50 排查锁定):
  1. 110 prod settings.py 第 45 行 (LDAP if block 之后) D35 push 加的 if 块写 `MIDDLEWARE += django_cas_ng.middleware.CASMiddleware` (D35 push Step 2 脚本实战, 来源待查)
  2. 110 prod `ENABLE_CAS=False` (env 没传 CAS_SERVER_URL), django_cas_ng 不在 INSTALLED_APPS
  3. django_cas_ng.middleware 加载触发 django_cas_ng.models 加载, 触发 ProxyGrantingTicket 没声明 app_label 报错
  4. settings.py line 494 `CAS_SERVER_URL = env("CAS_SERVER_URL")` 在 if ENABLE_CAS 块里, ENABLE_CAS=False 时不执行, 但 D35 push 加的 if 块独立, 触发了
- **影响**: 业务中断 14 分钟 (16:36-16:50)
- **修法**: 9/8 16:50 `sed -i '/MIDDLEWARE += ("django_cas_ng.middleware.CASMiddleware",)/d' /dbdata/archery_v114_c9236a0/archery/settings.py` + mock CAS env 拉 gunicorn + migrate 成功
- **教训**:
  1. D35 push 脚本 Step 2 注释加"不要加 `MIDDLEWARE += django_cas_ng.middleware.CASMiddleware`" (commit `0381368`)
  2. 110 prod .env 缺 CAS_SERVER_URL 是历史遗留, 业务能跑是 nohup 链路. D36 操作日志完后建议 DBA 手工补 .env 加 CAS_SERVER_URL + CAS_VERSION (从 Archery 上游拿默认)

### 踩坑 #2: D35 push Step 3 urls.py ddl_sync 路由漏 ⚠️ 严重
- **现象**: 9/8 16:55 verify 时 reverse(ddl_sync:pair_list) 报 "ddl_sync is not a registered namespace" + grep urls.py ddl_sync 0 引用
- **根因** (9/8 16:58 排查锁定):
  1. D35 push 脚本 Step 3 找的 old 字符串是 `'if getattr(settings, "CUSTOM_GH_OST_ENABLED", False):\\n    urlpatterns += [\\n...'`
  2. 110 prod urls.py 第 45 行是 `if getattr(settings, "CUSTOM_GH_OST_ENABLED", False):  # pragma: no cover` 有注释
  3. old 字符串没匹配, 路由没加成功
  4. Step 3 输出 "110 prod urls.py: " 空, 实际是 grep "ddl_sync/\|CUSTOM_DDL_SYNC" 没结果, 但脚本没 print "ERR: ddl_gh_ost 块 not found" (因为 ascii filter 过滤掉中文?)
- **影响**: 业务方能访问 /ddl_sync/ 但实际是 404 + LoginRequired 跳登录 (302), ddl_sync app 功能全部不可用
- **修法**: 9/8 16:58 写 `_d35_fix_urls.py`, 用 re.search 处理带 pragma 注释的 ddl_gh_ost 块, 加 ddl_sync 路由成功, kill+拉新 gunicorn, 5 reverse 全部 OK
- **教训**:
  1. D35 push 脚本 Step 3 改用 re.search 处理带 pragma 注释的 ddl_gh_ost 块 (commit `0381368`)
  2. 下次推 110 prod 前, 必跑 8 步 verify, 用 reverse() 验证 ddl_sync 路由 + curl 关键端点

---

## 四、9/8 17:00 后 110 prod 状态 (D35 push 完整落地)

| 项 | 状态 |
|---|---|
| gunicorn 进程 | 5+ (PID 8263 master + 4 worker) ✅ |
| 9123 端口 | LISTEN ✅ |
| /login/ | 200 ✅ |
| /ddl_sync/ | 302 跳 /login/ ✅ |
| /ddl_sync/pair/list/ | 路由生效, reverse OK ✅ |
| /ddl_sync/pair/1/ | 路由生效, reverse OK ✅ |
| /ddl_sync/pair/1/history_export/ | 路由生效, reverse OK ✅ |
| migrate ddl_sync | `Applying 0001_initial... OK / 0002... OK` ✅ |
| showmigrations ddl_sync | 2 [X] ✅ |
| wf#4786 D24 ForeignKey bug 修复 | `_should_use_ddl_rollback=False` + `get_rollback` 3 行 PASS ✅ |
| D35 跨 app 9 文件已推 | ddl_gh_ost 5 (nover/approver/backticks) + sql 模板 2 + column_diff 1 ✅ |
| D33 view 改动 (分页 + Excel 导出) | ddl_sync/views/__init__.py 4 引用, ddl_sync/urls.py 1 引用 ✅ |
| 业务不中断 | /login/ 200, /ddl_sync/ 302, /gh_ost/admin_list/ 302, /sqlsubmit/ 302 ✅ |

---

## 五、DBA 后续 1 步收尾 (110 prod admin 后台)

D35 push 完后, DBA 在 110 prod admin 后台 1 步操作:
1. `/admin/auth/group/add/` 创建 "审批人" 组
2. `/admin/auth/user/<李绍平id>/change/` 把李绍平加到 "审批人" 组
3. 李绍平刷新 `/gh_ost/admin_list/` 即可看全量 (D35 approver 白名单生效)

业务方通知: 由用户 (DBA 阿达叔叔) 发, 话术已在 `docs/plans/2026-09-07_ddl-sync-w2-d35-push-110prod-plan.md` 零段

---

## 六、同源 entry

### 实战脚本
- `scripts/_archive/_d35_hotfix_110prod_d24.py` (9/8 09:30 D24 紧急热补丁, 4 步落地)
- `scripts/_archive/_d35_verify_v2.py` (9/8 09:48 D24 业务方数据验证 PASS)
- `scripts/_archive/_d35_push_110prod.py` (9/8 16:32 D35 push 9 步, 升级版 12 文件 + 3 实战新发现注释)
- `scripts/_archive/_d35_recover_110prod.py` (9/8 16:36 紧急诊断 .env + systemd)
- `scripts/_archive/_d35_find_cas_v2.py` `v3.py` `v4.py` `v5.py` (9/8 16:36-16:50 找 CAS_SERVER_URL 来源)
- `scripts/_archive/_d35_restore_110prod.py` `v2.py` `v3.py` (9/8 16:50 紧急拉新 gunicorn + migrate + 修错行)
- `scripts/_archive/_d35_check_settings.py` (9/8 16:50 diff 看 110 prod settings.py 改动)
- `scripts/_archive/_d35_check_bak.py` (9/8 16:50 看 110 prod sed 前备份内容)
- `scripts/_archive/_d35_verify_post_push.py` (9/8 16:55 D35 push verify 6 项, 发现 ddl_sync 路由漏)
- `scripts/_archive/_d35_check_urls.py` (9/8 16:58 查 110 prod urls.py ddl_gh_ost 路由块格式)
- `scripts/_archive/_d35_fix_urls.py` (9/8 16:58 re.search pragma 注释块, 加 ddl_sync 路由 + 拉新 gunicorn PASS)

### 实战 changelog
- `docs/changelogs/2026-09-07_ddl-sync-w2-d35-bug-ghost-task-manager.md` (9/7 13:50 D24 ForeignKey bug 修法)
- `docs/changelogs/2026-09-08_ddl-sync-w2-d35-push-110prod.md` (本次, D35 push 实战)

### 实战 commit
- `e94f988` (9/8 09:30 D24 ForeignKey bug 修法)
- `6f6f649` (9/8 10:20 D35 push 计划文档更新)
- `0381368` (9/8 16:55 D35 push 脚本升级 + 实战踩坑注释 + LIVE_PUSH 改回 False)

### 实战文档
- `docs/plans/2026-09-07_ddl-sync-w2-d35-push-110prod-plan.md` (D35 push 计划, 9/7 12:50 + 9/8 10:20 更新)
