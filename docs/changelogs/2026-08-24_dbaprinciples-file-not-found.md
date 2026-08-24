# 2026-08-24 `/dbaprinciples/` 500 修复

## 症状
- 业务用户访问 `http://172.20.2.134:9003/dbaprinciples/` 报 500
- 异常: `FileNotFoundError at /dbaprinciples/`
- 异常值: `[Errno 2] No such file or directory: '/opt/archery/prod/docs/docs.md'`
- 异常位置: `/opt/archery/prod/sql/views.py, line 871, in dbaprinciples`
- 触发时间: 2026-08-24 17:12:48
- 延伸影响: **所有 Archery 端点**都 500 (因为 sql/views.py 整个文件 SyntaxError, gunicorn worker 加载失败)

## 根因 (两层)

### 第一层:Archery 上游缺 docs/docs.md
Archery 上游 `sql/views.py:870` (dbaprinciples 视图) 写死读 `docs/docs.md`,但仓库里**根本没这个文件**。

### 第二层 (更严重):我之前 scp 推过去的 docstring 漏闭合,导致整个 sql/views.py SyntaxError
我 17:00 左右修 dbaprinciples 视图时,写了 3 行 docstring:
```python
def dbaprinciples(request):
    """SQL文档页面 - 显示 MySQL 数据库设计规范。  ← 只开了 """ 没闭合!

    ## CUSTOM-MODIFIED: 8/24 修 FileNotFoundError @ 2026-08-24 @ mavis
    ## 关联: docs/changelogs/2026-08-24_dbaprinciples-file-not-found.md
    ## 根因 (8/24): ...
    ## 修法: ...
    candidates = [  ← 这行开始被认为是 docstring 内容,直到下一个 """ 才闭合
        ...
```

`"""` 共 79 个,**奇数不闭合**!Python parser 在 line 990 看到 `"""数据导出提交前预检，按各引擎查询规则校验并统计导出行数。"""` 时,因为 line 868 的 `"""` 还开着,整段被解析为字符串字面值,line 990 内的中文 `，` (U+FF0C) 被认为是 Python 代码的非法字符 → SyntaxError。

**134 dev prod 的 gunicorn worker 每次请求都 import sql.views, SyntaxError 触发 500。所以 `/login/` 也 500,/dbaprinciples/ 跳 /login/ 后 500。**

**这是我之前 scp 没本地 py_compile 验证的锅。**

## 修法

`sql/views.py:866-898` 改成多 candidate 兜底 + **docstring 正确闭合**:
```python
@permission_required("sql.menu_document", raise_exception=True)
def dbaprinciples(request):
    """SQL文档页面 - 显示 MySQL 数据库设计规范。

    ## CUSTOM-MODIFIED: 8/24 修 FileNotFoundError @ 2026-08-24 @ mavis
    ## 关联: docs/changelogs/2026-08-24_dbaprinciples-file-not-found.md
    ## 根因 (8/24): Archery 上游 views.py:870 读 docs/docs.md, 但仓库里没这个文件
    ##       134 dev 实际有 docs/upstream/docs.md (项目自己维护的 MySQL 设计规范)
    ## 修法: 优先读 docs/upstream/docs.md, 兜底读 docs/architecture.md, 都没有显示友好提示
    """  ← 关键: 这里 """ 闭合了 docstring
    candidates = [
        os.path.join(settings.BASE_DIR, "docs/upstream/docs.md"),
        os.path.join(settings.BASE_DIR, "docs/architecture.md"),
    ]
    md = None
    for file in candidates:
        if os.path.exists(file):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    md = f.read().replace("\n", "\\n")
                logger.info("dbaprinciples 读 %s (%d chars)", file, len(md))
                break
            except OSError as exc:
                logger.warning("dbaprinciples 读 %s 失败: %s", file, exc)
                continue
    if md is None:
        md = (
            "# 文档暂未提供\n\n"
            "请运维管理员将 MySQL 数据库设计规范放到以下任一位置:\n\n"
            "- `docs/upstream/docs.md`\n"
            "- `docs/architecture.md`\n\n"
            "推荐放 `docs/upstream/docs.md` (跟 134 dev 一致)。\n"
        )
    return render(request, "dbaprinciples.html", {"md": md})
```

## 验证
- 本地 `py_compile sql/views.py` OK ✓
- 134 dev prod `py_compile sql/views.py` OK (`OK_PARSE_CLEAN`) ✓
- 134 dev prod `import sql.views` 成功 (无 SyntaxError) ✓
- Django test client 验证:
  - `/login/` 匿名访问 → 200 ✓
  - `/dbaprinciples/` admin 登录 → 200 ✓
- HTTP 端到端:
  - `curl http://172.20.2.134:9003/login/` → 200 ✓
  - `curl http://172.20.2.134:9003/dbaprinciples/` → 302 → /login/ (正常未登录) ✓

## 部署
- sftp 上传本地 `sql/views.py` → 134 dev `/opt/archery/prod/sql/views.py`
- 134 dev prod 目录 mtime: 2026-08-24 18:00:55 (size 38775 bytes)
- 134 dev 没 systemd unit, gunicorn master 仍在 13665 (没 kill),但因为 wsgi module 重新加载机制,新代码立即生效
- 备份原坏代码: `/opt/archery/prod/sql/views.py.bak.20260824_175325` (38767 bytes)

## 134 dev SSH 异常 (17:18-17:55)
- archery user 从外网 (172.20.x.x) SSH 登录失败,key 被拒
- 同一 key 从 110 prod (172.20.2.110) 也被拒
- 但 root 走 password 可以登录 (用户提供 root 密码 CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW)
- sshd_config 没限制 AllowUsers, /home/archery/.ssh/authorized_keys 内容正确 (有这把 ED25519 key)
- 根因待查,可能是 PAM / 前置防火墙 / Match block

## 教训 (跨项目可复用, 8/24 重大踩坑)
1. **【致命教训】改 Python 代码后必须本地 `py_compile` 验证,再 scp 推!** 任何 docstring / 多行字符串 / 注释里的 `"""` 都要数配对
2. **【诊断教训】"X 端点 500" 可能是**整个应用加载失败**,不是 X 端点本身 bug**。先 curl 测 `/login/` 这种最简单端点,看是否 200。如果连 /login/ 都 500,说明是 module loading 错
3. **【诊断教训】""" 配对检查工具**: `python -c "with open('f.py','r',encoding='utf-8') as f: c = f.read(); n = c.count(chr(34)*3); print(n, 'paired' if n%2==0 else 'unpaired')"`
4. **【诊断教训】gunicorn worker 加载 module 失败时,所有 HTTP 端点都返 500** (因为 import 失败), 看 gunicorn stderr 不一定看到
5. **【架构教训】134 dev 跟 prod 目录分离**:
   - `/opt/archery/dev/` 是 git 仓库 (md5 4fc7371e...)
   - `/opt/archery/prod/` 是部署副本 (md5 7443abe6...)
   - gunicorn 从 prod 加载, dev/prod 不一致
   - 推 110 时要 deploy 脚本同步 dev → prod,不能直接 scp
6. **【流程教训】134 dev 没 systemd unit (跟 110 prod 一样)**, gunicorn master 启动后没自动拉起, kill master 后只能手动 nohup 起
7. **【应急教训】SSH 登录被拒时**: 不要反复 retry,直接问用户要 root password (5 分钟搞定,比排查 sshd config 快 10 倍)

## 同源 entry
- 8/24 教训: gunicorn HUP 不重载 Python 代码 (kill -HUP 没用,要 kill master)
- 8/24 教训: Django template 读文件要 try/except 兜底 (修这个 bug 的本意)
- 8/24 column_diff 修法 2 (modal 模板位置): "Django 模板读文件要 try/except" 延伸

## 推 110 时要做
1. 推代码前先 `py_compile` 验证
2. deploy 脚本同步 `/opt/archery/dev/` → `/opt/archery/prod/`,不要直接 scp
3. 推完后 admin 视角验 `/login/` `/dbaprinciples/` 都 200
4. 推 110 必做步骤 13 改成"推完必须走 Django test client 模拟关键端点 (不能只 curl /login/)"

## 关键 git commit
- `fix(dbaprinciples): 8/24 修 docs/docs.md FileNotFoundError + 修我之前 scp 推的 docstring SyntaxError`
- 关联: `docs/changelogs/2026-08-24_dbaprinciples-file-not-found.md`
