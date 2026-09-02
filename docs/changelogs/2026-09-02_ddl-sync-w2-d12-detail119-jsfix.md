# W2 D12 - 134 dev detail/119 JS ReferenceError 修复 (9/2 17:00)

## 症状

9/2 16:10 业务 RD 反馈 detail/119 报:

```
jquery.min.js:2  Uncaught ReferenceError: hly_accesscard_history is not defined
    at HTMLDocument.<anonymous> (http://172.20.2.134:9003/detail/119/:1955:26)
```

业务 RD、DBA、OA 管理员都看不到镜像工单 SQL 字段 diff inline 区域 (空白)。

## 根因 (134 dev 实战排查 9/2 17:00-17:10)

**134 dev 跑的 `detail.html` 是 8/26 21:34 commit `0a04775` 版本(有 inline 区域但有 JS bug),8/26 21:57 commit `2a04a12` 修复没推过去。**

8/26 推 110 prod 时 detail.html **不在推 110 范围** (推 110 范围瘦身后只推 gh-ost + 字段 diff sqlsubmit.html),所以 110 prod detail.html 一直保留 7/19 上游 v1.14.0 老版本 (没 inline 区域,没新功能,也没 bug)。

9/1+9/2 W2 D7-D11 实战推 ddl_sync 目录时也没补推 detail.html (ddl_sync 目录独立)。

实战 md5 对比 (9/2 17:00):

| 主机 | detail.html md5 | mtime | views.py md5 | mtime |
|------|----------------|-------|--------------|-------|
| 134 dev | `3bbf3cec1ba0818b1cef49763ec2341e` | 8/26 21:22 | `897666103fed613d25bdc2a843dc26b8` | 8/25 09:47 |
| 110 prod | `82198afe9d10071f74c86a6a3f53ea48` | **7/19 00:01** | `4fc7371e9f1431a1d9d65c61ad5b9230` | 7/19 00:01 |
| local HEAD | `5b40a9cae5d60b7aad87c2e765541368` | - | `781c238eaae3954ae8532834971f20eb` | - |

## 134 dev detail.html 1680-1690 实际内容 (老版本,踩坑)

```javascript
var sqlContent = {{ workflow_detail.sql_workflow_content|default:""|escapejs|default:"''" }};
var instanceId = {{ workflow_detail.instance_id|default:0 }};
var dbName = {{ workflow_detail.db_name|default:""|escapejs|default:"''" }};
fetchColumnDiff(sqlContent, instanceId, dbName);
```

- `|escapejs` 是 Django 4.0+ 已 deprecated 的 filter, 实际处理就是不过滤
- `db_name = "hly_accesscard_history"` 渲染时 `|default:""` 不触发, `|escapejs` 也不转, 最终输出裸字符串 `hly_accesscard_history`
- JS 把 `hly_accesscard_history` 当成变量名 (未定义), 报 ReferenceError, 中断 fetchColumnDiff 调用

## 修法 (2a04a12 commit 已修, 但 134 dev 没推)

**2a04a12 commit (8/26 21:57) 修法**:
- `views.py` 加 `import json` + 3 个 context 变量 (`sql_content_for_diff` / `instance_id_for_diff` / `db_name_for_diff`), 用 `json.dumps()` 包装
- `detail.html` 改用 `{{ var|safe }}` 渲染 (json.dumps 已 escape, 不依赖 template filter)

```javascript
var sqlContent = {{ sql_content_for_diff|safe }};
var instanceId = {{ instance_id_for_diff|default:0 }};
var dbName = {{ db_name_for_diff|safe }};
```

实际渲染 (D12 9/2 17:30 实战):
```
1729: var sqlContent = "ALTER TABLE accesscard_black_detail add COLUMN test1 VARCHAR(256)  not null  DEFAULT 'test1' COMMENT 'test1';";
1730: var instanceId = 2;
1731: var dbName = "hly_accesscard_history";  ← 带引号, JS 正常
```

## 134 dev 修复实战 5 步 (DBA 二次开发 6 步套路 + SFTP 推子目录 mkdir)

| 步骤 | 操作 | 实战发现 / 踩坑 |
|------|------|----------------|
| 1 | **备份** 134 dev 现场 (mtime=20260902_171202) | detail.html.bak_20260902_171202 + views.py.bak_20260902_171202 |
| 2 | **SFTP 推** 本地 detail.html + views.py 到 /tmp/_push_*.{html,py} | root 推到 /tmp, owner=root |
| 2.1 | `sudo -u archery mv` /tmp/_push_*.html → 目标 | **踩坑**: 报 `mv: cannot move ... Operation not permitted` (archery 用户无 root owner 文件 mv 权限) |
| 2.2 | **修法**: `cp /tmp/_push_*.html` + `chown archery:archery` 改用 root 直接操作 | OK |
| 3 | chown -R archery:archery | OK |
| 4 | 清 __pycache__ | `find /opt/archery/prod -type d -name __pycache__ -exec rm -rf {} +` (0 个剩余) |
| 5 | kill 老 gunicorn + nohup 拉新 (D7 阶段 1 实战套路) | 第一次 `setsid nohup` 失败 (9003 端口被老 gunicorn 占), 第二次用 `nohup ... & disown` 脱钩 OK |
| 6 | **14 端点 verify** + Django check + 重新 render detail/119 验证 | 全过, var dbName 带引号 |

## 14 端点 verify (9/2 17:30)

```
/login/                       -> HTTP:200
/                             -> HTTP:302
/admin/                       -> HTTP:302
/dbaprinciples/               -> HTTP:302
/sqlworkflow/                 -> HTTP:302
/ddl_sync/                    -> HTTP:302
/ddl_sync/pair/list/          -> HTTP:302
/ddl_sync/pair/1/             -> HTTP:302
/ddl_sync/pair/1/compute_diff/ -> HTTP:302
/ddl_sync/pair/1/one_click_setup/ -> HTTP:302
/ddl_sync/pair/1/bulk_import/ -> HTTP:302
/ddl_sync/pair/1/add_table/   -> HTTP:302
/ddl_sync/history/            -> HTTP:302
/static/ddl_sync/pair_detail.js -> HTTP:200
```

Django check ddl_sync: `System check identified no issues (0 silenced).`

## 134 dev 修复后 gunicorn pids

| PID | PPID | ETIME | 角色 |
|-----|------|-------|------|
| 12280 | 1 | - | 老的 (残留, kill 后应该没了) |
| 12282 | 1 | - | **新 master** |
| 12376 | 12282 | - | **新 worker 1** |
| 12377 | 12282 | - | **新 worker 2** |
| 12378 | 12282 | - | **新 worker 3** |
| 12381 | 12282 | - | **新 worker 4** |

## 110 prod 状态 (9/2 17:35)

- 110 prod `detail.html` 仍然是 7/19 上游 v1.14.0 老版本 (`82198afe...`)
- 没 inline 区域, 也没 JS bug
- 用户没明确要求修, **等用户拍板**

## 避坑 4 条 (D12 实战总结, 跨项目可复用)

1. **SFTP 推子目录** (D11 D7 D12 实战复用): SFTP 推 /tmp 后用 sudo -u archery mv 会因 owner=root 失败 (`Operation not permitted`), 实战用 **root 直接 cp + chown** 绕过
2. **gunicorn 拉新要 disown** (D12 实战新发现): `setsid nohup cmd > log 2>&1 &` 让 paramiko exec_command 等到超时 (默认等命令结束), 实战用 `nohup cmd & disown` 立即脱钩
3. **Django settings LOGGING 相对路径** (D12 实战新发现): `filename: "logs/archery.log"` 相对路径, Django 用 cwd 解析, 必 `cd /opt/archery/prod` 再跑 Python (不然报 `PermissionError: '/root/logs/archery.log'`)
4. **detail.html 推 110 范围明确** (D12 实战总结): 8/26 推 110 prod 没推 detail.html, 因为 1d4fbf6 (8/26 16:46) 拍板推 110 范围瘦身只推 gh-ost + 字段 diff (sqlsubmit.html). 实战 8/26 21:40+21:57 又有 0a04775 + 2a04a12 改 detail.html, 8/26 19:00 推 110 时这俩 commit 还没出来, 之后也没补推. 实战发现 110 prod detail.html 一直是 7/19 上游版

## 关联 commit

- 8/26 21:34 `0a04775` - feat(detail.html): 8/26 detail 页字段 diff inline 区域
- 8/26 21:57 `2a04a12` - fix(detail.html + views.py): 8/26 字段 diff JS ReferenceError 修复
- 9/2 17:30 `D12` (本次) - chore(deploy): SFTP 推 134 dev detail.html 修复 detail/119 JS ReferenceError

## 关联脚本

- `scripts/_archive/_d11_wf119_grep.py` - 看 134 dev view 端实际代码
- `scripts/_archive/_d11_wf119_render.py` - 134 dev render 验证
- `scripts/_archive/_d11_prod_md5_check.py` - 134+110 detail.html md5 对比
- `scripts/_archive/_d11_push_detail_fix.py` - 推文件主脚本 (踩坑: sudo mv 失败, 用 root cp)
- `scripts/_archive/_d11_emergency_fix.py` - 紧急 root cp + chown + 拉新
- `scripts/_archive/_d11_run_one_shot.py` - one_shot.sh 上传 + 跑
- `scripts/_archive/_d11_kill_restart2.py` - kill 老 gunicorn + nohup ... & disown 拉新 + 端点 verify
- `scripts/_archive/_d11_one_shot_v3.sh` - 14 端点 verify + render 验证 + Django check
- `scripts/_archive/_d11_render_v3.py` - 实战 render 脚本 (archery 用户 + cd /opt/archery/prod)

## 134 dev 备份

- `/opt/archery/prod/sql/templates/detail.html.bak_20260902_171202` (88510 bytes, 8/26 21:22 老版)
- `/opt/archery/prod/sql/views.py.bak_20260902_171202` (38775 bytes, 8/25 09:47 老版)

## 同源 entry

- 9/2 16:10 业务 RD mkq 反馈 detail/119 报 JS ReferenceError
- 8/26 21:51 业务 RD 反馈 detail/4747 同样 JS ReferenceError (2a04a12 已修)
- 8/24 实战 mkq 反馈 gh-ost 任务详情没字段 diff
- 8/13 AJAX 守卫教训 (403 必返 JSON)
