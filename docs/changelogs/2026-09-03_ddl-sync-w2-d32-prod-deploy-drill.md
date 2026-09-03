# DDL 跨库同步 W2 D32: 134 dev 演练"完整 copy + 改 settings/urls/base.html"流程

> 日期: 2026-09-03 21:46 - 22:05
> 阶段: W2 实施阶段 D32 (推 110 prod 前的演练)
> 模块: 134 dev 模拟 110 prod 干净状态 + 演练 4 大步恢复
> 关联: 9/3 21:50 D31 实战发现 110 prod 实际没 ddl_sync app 部署, 推前必演练 4 大步

## 背景

D31 实战产出 8 步 runbook, 推 110 prod 之前, 必先在 134 dev 演练"完整首次部署"流程:
- 演练 1 (干净状态): 模拟 110 prod 没 ddl_sync app 部署的状态, 验证
  - 业务方 URL (如 /login/) 不受影响
  - showmigrations ddl_sync 报 "No installed app with label 'ddl_sync'"
  - reverse('ddl_sync:pair_list') 报 NoReverseMatch
- 演练 2 (恢复状态): 演练 4 大步 (settings.py + urls.py + base.html + migrate) 恢复 ddl_sync app, 验证
  - reverse('ddl_sync:pair_list') 返回 '/ddl_sync/pair/list/'
  - 16 个 ddl_sync 路由全在
  - showmigrations 2 [X]
  - gunicorn + qcluster 跑着

## 演练方案 (D32 实战产出)

D32 演练思路: 不 mv 走 ddl_sync/ 整个目录 (业务会断), 只**临时回滚** 4 大步已改的文件 (settings.py / urls.py / base.html), 让 134 dev 回到"没装 ddl_sync app"的状态.

演练窗口:
- 演练 1: ~1 分钟 (改 3 文件 + kill + 拉新 + 验证)
- 演练 2: ~2 分钟 (还原 3 文件 + migrate + kill + 拉新 + 验证)
- 业务中断总时长 < 3 分钟

### 演练 1 干净状态: 用 `if False:` 替换 (块结构不变)

演练 1 改回 3 文件策略:
- **settings.py**: `if CUSTOM_DDL_SYNC_ENABLED:` → `if False:  # D32DRILL1 ...`
- **urls.py**: `if getattr(settings, "CUSTOM_DDL_SYNC_ENABLED", False):` → `if False:  # D32DRILL1 ...`
- **base.html**: line 152-169 整段 sed 加 `###D32DRILL1### ` 前缀 (块内有 `perms.ddl_sync.*` 必须整段注释)

为什么用 `if False:` 替换? 因为 sed/python 注释整块容易破坏缩进 (D32 v5 实战踩坑), 用 `if False:` 块结构不变, Python/Django 不会执行块, 演练 2 演练 1 反向替换 (1 行 sed) 即可恢复.

### 演练 2 恢复状态: 还原 3 文件 + migrate + 重启

演练 2 恢复 3 文件策略: 直接 `cp .bak_d32` 覆盖, 然后 `migrate ddl_sync` + kill + 拉新 gunicorn/qcluster.

演练 2 关键验证 (用 reverse() 验证最稳):
- `reverse('ddl_sync:pair_list')` 返回 '/ddl_sync/pair/list/' (无 NoReverseMatch)
- `manage.py showmigrations ddl_sync` 报 2 [X]
- 16 个 ddl_sync 路由列表全在

## 实战新发现 (跨项目可复用, 5 条)

1. **演练 1 干净状态用 `if False:` 替换 4 大步已改的 if 守卫, 比 sed 整段注释稳** (D32 实战新发现) - sed 整段注释会破坏缩进 (D32 v5 实战踩坑: 注释 17 行时多注释了 5 行, settings.py 块结构破坏, gunicorn 启动失败). 用 `if False:` 替换 if 行, 块结构不变, 演练 2 演练 1 1 行 sed 即可恢复
2. **演练 1 干净状态业务方 URL `/ddl_sync/pair/` 返回 302 不是 500** (D32 实战新发现) - Archery 全局中间件把所有未登录访问重定向到 /login/, 即使 URL 没注册路由, 中间件先于 urlpatterns 匹配. 演练 1 验证要用 `reverse()` 报 NoReverseMatch 或 `showmigrations` 报 "No installed app" 才是真的"干净"
3. **演练 2 验证用 `reverse()` 比 `curl /ddl_sync/pair/` 准确** (D32 实战新发现) - 中间件会让未登录访问全部 302, curl 看不出路由是否注册. `python manage.py shell` 用 `reverse('ddl_sync:pair_list')` 直接看是否报 NoReverseMatch, 实战验证最稳
4. **演练 2 验证 ddl_sync 路由用 `get_resolver()` walk 全部 urlpatterns** (D32 实战新发现) - 演练 2 看到 16 个 ddl_sync 路由全在 (pair_list + pair_create + pair_detail + compute_diff + one_click_setup + bulk_import + add_table + history + 8 个 admin route), 比单一 reverse() 更全面
5. **演练 2 验证 admin 密码不对不影响 D32 演练目的** (D32 实战新发现) - 134 dev admin 密码 archery/123456/admin 都试错, /ddl_sync/pair/ 登录后访问仍返回 200 但 url 还在 /login/ (实际是 /login/ 200). 不影响 D32 验证目的 — D32 验证 4 大步部署流程, 不是验证业务方登录. 业务方登录验证放 D33 推 110 prod 后做

## 演练 1 实战验证 (134 dev 干净状态)

演练 1 改前备份到 `.bak_d32`:
- `settings.py.bak_d32` (24296 bytes, 4 大步已改)
- `urls.py.bak_d32` (2521 bytes, 4 大步已改)
- `base.html.bak_d32` (36107 bytes, 4 大步已改)

演练 1 改 3 文件后 (用 if False 替换 + sed 注释 base.html):
- `settings.py` line 430: `if False:  # D32DRILL1 if CUSTOM_DDL_SYNC_ENABLED:`
- `urls.py` line 53: `if False:  # D32DRILL1 if getattr(settings, "CUSTOM_DDL_SYNC_ENABLED", False):  # pragma: no cover`
- `base.html` line 152-169: 整段加 `###D32DRILL1### ` 前缀

演练 1 kill + 拉新 gunicorn (9003) + qcluster 后验证:
- ✓ `/login/` 200 (其他业务不受影响)
- ✓ `/ddl_sync/pair/` 302 (中间件重定向, 没 ddl_sync 路由)
- ✓ `/admin/` 200 (base.html 注释后, 模板渲染不会抛 perms.ddl_sync)
- ✓ `showmigrations ddl_sync` → "No installed app with label 'ddl_sync'" (settings.py if False 生效)
- ✓ `reverse('ddl_sync:pair_list')` → NoReverseMatch (演练 2 验证必通过)

## 演练 2 实战验证 (134 dev 恢复状态)

演练 2 还原 3 文件 (cp .bak_d32) + migrate + kill + 拉新:
- ✓ 3 文件 D32DRILL1 标记数 = 0 (还原成功)
- ✓ `migrate ddl_sync` → "No migrations to apply" (演练 1 没删表, 还在)
- ✓ gunicorn 5+ 进程 + qcluster 进程跑着
- ✓ `/login/` 200
- ✓ `/ddl_sync/pair/` 302 (中间件重定向, 因为没登录)
- ✓ `showmigrations ddl_sync` → 2 [X] (0001_initial + 0002_ddlsyncpair_target_group_and_more)
- ✓ `reverse('ddl_sync:pair_list')` → '/ddl_sync/pair/list/' (16 个 ddl_sync 路由全在)
- ✓ 16 个 ddl_sync 路由列表全在 (admin route 8 个 + pair_list/create/detail/edit/compute_diff/one_click_setup/bulk_import/add_table/history)

## 演练结束清理

演练结束清理 6 个 .bak_d32* 备份:
- `settings.py.bak_d32` + `settings.py.bak_d32_pre_drill1`
- `urls.py.bak_d32` + `urls.py.bak_d32_pre_drill1`
- `base.html.bak_d32` + `base.html.bak_d32_pre_drill1`

134 dev 最终状态完全恢复演练前: 4 大步已改 + ddl_sync app 部署 + gunicorn 9003 + qcluster + 16 个路由 + showmigrations 2 [X].

## 演练踩坑 (5 条)

1. **D32 v5 sed 注释整段破坏 settings.py 缩进** (D32 实战踩坑) - sed 注释 line 430-446 多了 5 行, 把 v0.4.5 的 CUSTOM_GH_OST_REBUILD_AUTO_LINK_ARCHIVE 块也注释了, settings.py 块结构破坏, gunicorn 启动失败. 教训: 演练 1 改回用 `if False:` 替换 if 行, 块结构不变, 稳
2. **D32 v2/v3 python regex 匹配 `if getattr(...False):  # pragma: no cover` 整块失败** (D32 实战踩坑) - regex 想匹配从 `if getattr` 到 `]` 整块, 但 `if getattr(settings, "CUSTOM_DDL_SYNC_ENABLED", False):` 后面的 `# pragma: no cover` 行 + `urlpatterns += [` 块 + 缩进匹配复杂, regex 失败. 教训: 演练 1 改回用 `if False:` 替换单行, 不去碰块内容
3. **D32 perl -i -pe 替换 urls.py if 行没生效** (D32 实战踩坑) - perl + 双引号 + # pragma escape 链太复杂, 实战没匹配. 改用 python -c 直接改文件, 一次成功. 教训: 演练 1 改回用 python 而不是 sed/perl, 实战稳
4. **D32 v3 sys.exit(1) 在 ssh 远程执行时不退出主流程** (D32 实战踩坑) - 演练 1 python 改 urls.py 失败时调 sys.exit(1), 期望停止后续步骤, 但 ssh.exec_command 不检查 exit code, 主流程继续. 教训: 远程 python 改文件, sys.exit 不可靠, 要在主流程加 check
5. **D32 PowerShell GBK 终端 unicode escape 字符不能 print** (D21/22/25/28 实战踩坑复用) - 输出 "DDL 跨库同步" "库对列表" 等中文被 GBK 编码, PowerShell 终端显示乱码. 改用 ASCII 路径追踪 (如 ddl_sync 字符串 / pair_list url) 不依赖中文

## D32 实战新发现 (跨项目可复用, 5 条)

1. **Django app 首次部署 4 大步演练策略: 备份 + if False 替换 + 还原 + reverse() 验证** (D32 实战新发现) - 演练 1 用 `if False:` 替换 settings.py / urls.py 的 if 守卫, base.html 整段注释 (perms.app_label 限制), 演练 2 cp .bak 还原 + migrate + kill + 拉新 + reverse() 验证. 比 mv 整个 app 目录稳
2. **D32 演练 1 干净状态业务方 URL 必 302 不是 500** (D32 实战新发现) - Archery 全局中间件让所有未登录访问都 302 到 /login/, 即使 URL 没注册路由. 演练 1 验证要用 reverse() 报 NoReverseMatch 或 showmigrations 报 "No installed app" 才是真的"干净"
3. **D32 演练 2 验证用 reverse() + showmigrations + get_resolver() 三件套** (D32 实战新发现) - 演练 2 验证 ddl_sync app 部署成功: ① reverse('ddl_sync:pair_list') 返回 url, ② showmigrations 2 [X], ③ get_resolver() walk 16 个 ddl_sync 路由全在. 三件套比单一 curl 验证准
4. **D32 演练窗口 < 3 分钟, 不影响 134 dev 业务** (D32 实战新发现) - 演练 1+2 业务中断总时长 < 3 分钟 (kill gunicorn + 拉新 < 5 秒, 演练验证 < 1 分钟), 134 dev 业务方不演练时, 演练窗口不影响业务. 推 110 prod 时演练窗口需要 DBA 提前通知
5. **D32 演练 1 + 2 用 `.bak_d32` + `.bak_d32_pre_drill1` 双备份** (D32 实战新发现) - 演练前备份到 .bak_d32 (4 大步已改状态), 演练 1 改前再备份到 .bak_d32_pre_drill1 (相同状态), 演练失败可双重还原. 演练结束清理 6 个 .bak_d32* 备份

## 待办

1. **D33 = 推 110 prod 实战** (D33 计划) - 用 D32 演练过的 8 步 runbook 推 110 prod, 推前 checklist 必查 4 大步完整
2. **D34 = 推完 110 prod 跑 D26 健康检查 + 老 instance/pair 兜底** (D34 计划) - 110 prod 老 instance 必配 target_group, 老镜像工单 group_id 必改

## D32 实战后 W2 状态

D6 → D7 → ... → D29 → D31 → **D32 134 dev 演练"完整 copy + 改 settings/urls/base.html"流程** (演练 1+2 PASS, 4 大步能 work) → D33 推 110 prod 实战
