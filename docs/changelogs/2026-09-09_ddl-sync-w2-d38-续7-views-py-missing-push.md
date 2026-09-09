# D38 续 7: 110 prod 漏推 sql/views.py 缺 DDL 跨库同步 alert 块 (2026-09-09 16:38)

## 业务方反馈 (9/9 16:38 截图 4 张)
- 110 prod 源工单 wf#4791 详情页 (`/detail/4791/`) 缺 "DDL 跨库同步 - 已配置" 联动中块
- 110 prod 镜像工单 wf#4792 详情页 (`/detail/4792/`) 缺 "DDL 跨库同步 - 镜像工单" 自动生成块
- 134 dev 同样工单能正常显示这两块 (业务方对比验证)

## 根因
D35 push 9/8 16:32 实战只推了 ddl_sync app 目录 + settings.py + urls.py + base.html, **没推 sql/views.py**.

110 prod 部署时间线:
- 8/13 W1 阶段 1 实战推 134 dev + 110 prod (views.py 是 8/13 那时的版本 = 2a04a12 8/26)
- 9/2 D18 + 9/3 D19 改 `sql/views.py` 加 alert 块上下文 (`ddl_sync_as_target` / `ddl_sync_as_source`)
- 9/2 + 9/3 实战只推了 134 dev (D32 v5 演练流程)
- 9/8 D35 push 9 步 runbook 没列 sql/views.py 在推送清单 (只 4 大步: app + settings + urls + base.html)
- **110 prod `sql/views.py` 一直停在 8/26 版本**

md5 验证 (2026-09-09 16:42):
| 文件 | Windows 本地 | 134 dev | 110 prod | 状态 |
|------|------------|---------|---------|------|
| `sql/views.py` | `95147d47...9c6df` | `95147d47...9c6df` | `781c238e...f20eb` | **MISMATCH** |
| `archery/settings.py` | `96f4d308...64aa` | `96f4d308...64aa` | `c8dae15b...e15b` | MISMATCH (D35 手工 sed 改 + 110 prod 又被 sed 修过) |
| `archery/urls.py` | `f1261013...8619` | `f1261013...8619` | `faafb54c...b54c` | MISMATCH (D35 手工加 include) |
| `common/templates/base.html` | `b607f6b3...1a0c` | `b607f6b3...1a0c` | `9e258076...8076` | MISMATCH (D35 手工加 ddl_sync menu) |
| `sql/templates/detail.html` | `4a5c6ec1...5d4b` | `4a5c6ec1...5d4b` | `4a5c6ec1...5d4b` | OK |
| `sql/extensions/ddl_sync/...` | (全部一致) | | | OK |

## 修法
1. scp 推 `sql/views.py` 到 110 prod `/dbdata/archery_v114_c9236a0/sql/views.py`
2. chown archery:archery
3. pkill gunicorn + setsid nohup 重启
4. 演练 force_login 业务方 archery + mkq 看 wf#4791 + wf#4792 详情页 alert 块

## 实战新发现 (跨项目可复用, 3 条)
1. **推 110 prod 必三环境 md5 对比 + 列推送清单** (D38 续 7 实战新发现) - D35 push 9 步 runbook 漏列 `sql/views.py` 导致 110 prod 漏推. 跨项目推 110 prod (生产) 必先列推送清单 (用 git diff 跨 commit 算所有改动文件), 三环境 scp 完做 md5sum 对比
2. **D35 手工 sed 改的 settings/urls/base.html 没 commit 到 git** (D38 续 7 实战新发现) - D35 push 时手工 sed 改 3 文件 + sed 删错行修复, 但从来没 commit. 134 dev 跟 Windows 本地 working tree 一致 (手工改完未提交), 110 prod 也是手工改版但又经过 sed 修过. 跨项目手工改上游文件必 commit (即使只 1 行注释, 避免后续 sync 上游时丢失)
3. **ddl_sync_as_target / ddl_sync_as_source 是 D18 9/2 9/3 业务上下文关键变量** (D38 续 7 实战新发现) - 源工单详情页 alert 块需要 `ddl_sync_as_source` (DdlSyncHistory list), 镜像工单需要 `ddl_sync_as_target` (DdlSyncHistory single). 跨项目做"联动标识"功能, 必同步改 view context + template `{% if %}` 守卫 + 推 prod 一起, 不要只改 template 不改 view

## 演练计划
- 110 prod force_login 业务方 mkq 看 wf#4791 详情页应显示 "DDL 跨库同步 - 已配置" 块
- 110 prod force_login 业务方 mkq 看 wf#4792 详情页应显示 "DDL 跨库同步 - 镜像工单" 块
- 134 dev 同样验证 (确认没破坏 134 dev 行为)

## 部署清单
- 1 文件 scp 推 110 prod
- 110 prod gunicorn pkill + setsid nohup 重启
- 演练 2 工单 x 1 用户 (mkq)

## W2 状态
D6 → ... → D37 → D38 → D38 补充 → D38 续 → D38 续 2 → D38 续 3 → D38 续 4 → D38 续 5 → D38 续 6 → **D38 续 7 (110 prod 漏推 sql/views.py 补推)**
