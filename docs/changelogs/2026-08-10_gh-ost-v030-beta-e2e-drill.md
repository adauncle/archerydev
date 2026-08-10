# v0.3.0-beta —— gh-ost 端到端真跑（precheck + enable + start + cut-over success）

**日期**: 2026-08-10
**作者**: mavis
**类型**: feat（端到端演练，v0.3.0-beta 闭环）

## 背景

v0.3.0-beta 前端 UI 集成 (`6c44926` / `2129221` / `853bf6a` / `461152d` / `281fbeb`) 完成后，
DBA 浏览器走 detail.html "启用 gh-ost" 按钮 → precheck → enable → 进度面板 iframe
→ 点"启动 gh-ost" → 端到端跑通 cut-over 成功。

## 端到端流程（wf=20, task_id=33）

```
1. POST /gh_ost/precheck/20/  → 200 ok=True passed=True "5/5 通过"
2. POST /gh_ost/enable/20/    → 200 ok=True task_id=33 status=queued
3. POST /gh_ost/start/20/     → 200 ok=True status=running pid=47284
4. 立即查 task:                 status=running ghost_pid=47284
5. 5s 后查 task:                status=SUCCESS progress_pct=100 current_stage=done  ← cut-over!
6. GET  /gh_ost/status/20/    → 200 status=success
```

**真跑通** gh-ost 完整 5 阶段：
1. precheck (5/5 通过)
2. inspector / applier / streamer 三连接建立
3. 影子表创建 (`_accesscard_account_gho/_del/_ghc`)
4. row copy (20 行小表，瞬间完成)
5. **cut-over** (atomic rename，progress=100%)

## 排查过程（2 个新踩坑）

### 坑 1: /var/log/archery/gh_ost 目录 root:root 拥有者

**症状**: 启动 gh-ost 500 → `Permission denied: '/var/log/archery/gh_ost/ghost-XX.log'`

**根因**: v0.3.0-beta 真跑演练时 mavis 用 `root` ssh 跑 gh-ost，gh-ost 自动创建
`/var/log/archery/gh_ost/` 目录（root:root 拥有者）。gunicorn 跑 `archery:archery`
写不进。

**修复**: `chown -R archery:archery /var/log/archery/gh_ost`

**SOP**: 部署 v0.3.0+ 时手动 chown + ls -ld 验证 + gh-ost 演练验证

### 坑 2: /tmp/gh-ost.*.sock 残留端口冲突

**症状**: 启动 gh-ost 500 → `bind: address already in use` （不是 Permission denied）

**根因**:
- 8/6 12:57 演练残留 `/tmp/gh-ost.archery_dev.accesscard_account.sock`（root:root 拥有者）
- gh-ost 进程 zombie (`archery 30192 [gh-ost] <defunct>`)，socket 文件未清理
- 新启动 gh-ost 报 bind error

**修复**:
```bash
rm -f /tmp/gh-ost.*.sock
# 同时清理 _gho/_del/_ghc 影子表
mysql -udbops -e "DROP TABLE IF EXISTS archery_dev._accesscard_account_gho"
```

**SOP**: 每次演练后清理 `/tmp/gh-ost.*.sock` + 影子表

## 134 dev 状态

```
$ ls -ld /var/log/archery /var/log/archery/gh_ost
drwxr-xr-x. 3 archery archery 4096 /var/log/archery
drwxr-xr-x. 2 archery archery 4096 /var/log/archery/gh_ost   ← chown 修后

$ ls -la /tmp/gh-ost.*.sock
(empty, 清理后)

$ mysql -udbops archery_dev -e "SHOW TABLES LIKE '_accesscard%'"
(empty, 清理后)
```

## 110 PROD 影响

**110 推 v0.3.0 前必做**：
1. `chown -R archery:archery /var/log/archery/gh_ost` (避开坑 1)
2. `rm -f /tmp/gh-ost.*.sock` (避开坑 2)
3. `mysql ... -e "DROP TABLE IF EXISTS <db>._*_gho"` (残留影子表清理)

**promote runbook** 加这 3 步。

## 端到端验证总结

| 阶段 | 端点 | 状态 | 备注 |
|------|------|------|------|
| precheck | POST /gh_ost/precheck/20/ | ✅ 5/5 通过 | binlog=ROW / 磁盘 1.16TB / 权限 / SQL / 表类型 |
| enable | POST /gh_ost/enable/20/ | ✅ task_id=33 queued | K2 重新加密 + 写 task |
| start | POST /gh_ost/start/20/ | ✅ status=running pid=47284 | Popen + nohup + log to /var/log/archery/gh_ost/ghost-33.log |
| poller | daemon thread 3s | ✅ progress=100% | parser 解析 gh-ost stdout |
| cut-over | atomic rename | ✅ success | 影子表 drop + 主表 rename |
| final | GET /gh_ost/status/20/ | ✅ status=success | 整个链路 ~5s (小表 20 行) |

## 相关 commit

- `4f34a81` feat(gh-ost): v0.3.0-alpha 骨架
- `2c5a0b7` feat(gh-ost): v0.3.0-beta 真跑 8 件（后端）
- `6c44926` / `2129221` feat(gh_ost): v0.3.0-beta detail.html 启用按钮 + iframe
- `853bf6a` fix(gh_ost): progress 页 @xframe_options_exempt
- `461152d` fix(gh_ost): progress.html admin URL + target=_blank
- `281fbeb` fix(gh_ost): "查看 admin 详情" 仅 superuser
- `042dee3` docs(changelog): gh-ost log dir 权限
- **本文件** — v0.3.0-beta 端到端真跑成功 + 2 坑修复 SOP
