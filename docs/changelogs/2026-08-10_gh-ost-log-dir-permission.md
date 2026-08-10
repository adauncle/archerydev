# 134 dev 验证发现 — /var/log/archery/gh_ost 目录 root:root 权限

**日期**: 2026-08-10
**作者**: mavis
**类型**: fix（部署层，非代码）

## 背景

DBA 浏览器点 "启动 gh-ost" 按钮 → POST `/gh_ost/start/20/` → 500 弹窗：

```
操作失败: {"ok": false, "error": "启动 gh-ost 失败: [Errno 13] Permission denied:
'/var/log/archery/gh_ost/ghost-28.log'"}
```

## 根因

```
$ ls -ld /var/log/archery /var/log/archery/gh_ost
drwxr-xr-x. 3 archery archery 4096 /var/log/archery
drwxr-xr-x. 2 root    root    4096 /var/log/archery/gh_ost   ← 拥有者 root
```

**gunicorn systemd unit** (`archery-prod-gunicorn.service`) 跑 `User=archery / Group=archery`，
`/var/log/archery/gh_ost/` 拥有者是 `root:root` → archery 用户写不进去。

**历史原因**：
v0.3.0-beta (`2c5a0b7`) 真跑演练时，mavis 用 `root` ssh 到 134 dev 跑 gh-ost 命令，
gh-ost Popen `nohup` 写 log 时**自动创建**了 `gh_ost/` 目录（root 创建 → 拥有者 root:root）。
后续 gunicorn (`archery:archery`) 想再写新 log 文件时，写不进 root 目录。

**Note**：已存在的 log 文件（`ghost-12.log` ~ `ghost-25.log`）都是 `archery:archery` 拥有者，
因为 gh-ost 进程是用 archery 用户跑（systemd service）。但**目录**是 root 建的 → 写新文件失败。

## 修复

```bash
chown -R archery:archery /var/log/archery/gh_ost
```

**验证**：
- `ls -ld /var/log/archery/gh_ost` → `archery:archery` ✅
- `sudo -u archery touch /var/log/archery/gh_ost/test_perm.log` → 成功 ✅

## 110 PROD 影响

| 修复 | 推 110？ |
|------|----------|
| `chown -R archery:archery /var/log/archery/gh_ost` | ✅ 必做（推 v0.3.0 前） |

**110 推 v0.3.0 时**：
- tarball 推完代码后，**SSH 110 root 跑 chown**
- 或者在 promote runbook 加一行

## 操作 SOP（避免下次踩）

**部署 v0.3.0+ 时**：
1. systemd gunicorn 跑什么用户，先看 unit 文件
2. 部署前手动 `chown -R $GUNICORN_USER:$GUNICORN_USER /var/log/archery/gh_ost/`
3. `ls -ld` 验证
4. 启动 gh-ost 演练 + `ls -la /var/log/archery/gh_ost/ghost-*.log` 验证 log 写入

## 相关 commit

无 commit（部署层修复，chown 不入 git）

## 同源教训

v0.3.0-alpha commit `4f34a81` 加的 runner.py 默认 log_dir=`/var/log/archery/gh_ost/`，但**没在文档/SOP 里说清要先 chown**。
应该在 commit 里加一段 README 说明部署要求。

## 相关 memory entry

### gh-ost log dir permission 部署要求 (2026-08-10)
Type: project-context

- **背景**: gh-ost runner 默认 log_dir = `/var/log/archery/gh_ost/`，需要 gunicorn 运行用户（archery:archery）可写
- **踩坑**: 134 dev 8/10 启动 gh-ost 报 Permission denied，根因是历史演练用 root ssh 跑，root 自动创建了 `gh_ost/` 目录（root:root 拥有者）
- **诊断**: `ls -ld /var/log/archery/gh_ost`，拥有者不是 archery 就有问题
- **修法**: `chown -R archery:archery /var/log/archery/gh_ost` + `sudo -u archery touch` 验证
- **SOP**: 部署 v0.3.0+ 时手动 chown + ls -ld 验证 + gh-ost 演练验证 log 写入
- **110 prod 推 v0.3.0 前必做**: 同 chown + 验证
