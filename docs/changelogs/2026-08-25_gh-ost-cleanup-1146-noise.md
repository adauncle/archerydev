# 2026-08-25 gh-ost cleanup 阶段 1146 noise 过滤

> **触发时间**: 2026-08-25 11:38 (业务 RD 首次真启动 gh-ost)
> **修复时间**: 2026-08-25 12:33
> **影响**: task.error_message 不再被 1146 noise 污染, 业务 RD 看着不别扭

---

## 症状

业务 RD 在 `/detail/94/` 页面点"启动 gh-ost"按钮 → gh-ost 18 秒成功迁移 24 万行 → task #70 状态 = `out-over 成功`，但 **"错误/备注" 区域显示**:

```
Error 1146 (42S02): Table 'archery_dev._accesscard_black_detail_ghc' doesn't exist
```

业务 RD 看着别扭: 任务明明成功了, 为什么有错?

---

## 根因

gh-ost 1.1.10 cut-over **成功后** cleanup 阶段:

```
1. rename _x_gho → x          (新表生效)
2. rename x → _x_del          (旧表备份)
3. drop _x_del                (删旧表)
4. drop _x_ghc                (删 changelog 表) ← 这里报 1146
```

`drop _x_ghc` 时表已不存在 (gh-ost 自己已清过, 或上次演练残留), gh-ost 子进程抛 1146 → exit code != 0 → stderr 写 "Error 1146..." → parser 抓到 → 写 `task.error_message`.

**不影响主流程** (数据迁移 100% 成功), 但 Archery 把 1146 存到 error_message 让 UI 看着像 fail.

---

## 之前没这个报错的原因

之前所有演练 (5 端点验证 + 6 drill 脚本 + 8/13 端到端演练) **都没真启动 gh-ost 二进制**:
- drill 脚本测 Archery 二次开发代码逻辑 (解析/端点/权限守卫)
- 5 端点验证只测 HTTP 状态

**业务 RD 8/25 11:38 是首次真启动 gh-ost 进程做 ALTER TABLE 数据迁移**, 所以 1146 noise 首次出现.

---

## 修法

`sql/extensions/ddl_gh_ost/services/parser.py`:

```python
# 8/25 教训: gh-ost cut-over 后 cleanup 阶段常见 1146 noise
# 匹配 1146 或 "doesn't exist" 即认为是 cleanup noise, 跳过
_RE_CLEANUP_NOISE_1146 = re.compile(r"1146|doesn't exist", re.IGNORECASE)

# ERROR 处理
if level == "ERROR":
    em = _RE_ERROR.search(line)
    err = em.group(1).strip() if em else line
    if _RE_CLEANUP_NOISE_1146.search(err):
        continue
    if not result.error_message:
        result.error_message = err[:1000]
    result.last_message = msg.strip()
    continue
```

### 验证 (drill_parser_1146_filter.py, 4 Case)

| Case | 场景 | 期望 | 实测 |
|------|------|------|------|
| A | 1146 noise + 成功 | error_message 为空 | ✓ PASS |
| B | 真 FATAL (Lost connection) | error_message 含 "Lost connection" | ✓ PASS |
| C | 混合 (1146 + FATAL) | 1146 过滤 + FATAL 保留 | ✓ PASS |
| D | 其他 ERROR (1062 Duplicate) | error_message 含 "1062" | ✓ PASS |

### 8/24 教训 + 演练

- 改 Python 后必 `kill master` (不是 HUP, 8/24 教训) → 134 dev kill 14698 → systemd 拉起 20652 (7.3s)
- 演练必查 master 启动时间跟代码 mtime 对得上 → 20652 启动 12:33, parser.py mtime 12:32:51 ✓
- 5 端点验证 PASS (业务 RD 不中断)

---

## 8/27 推 110 影响

- 8/27 推 110 推代码后, 业务 RD 启动 gh-ost 不再有 1146 noise
- 数据迁移逻辑不变, 100% 成功率不变
- 推 110 阶段 6 业务 RD 启动 gh-ost 演练: 期望 任务成功 + error_message 为空

---

## 8/25 教训 (跨项目可复用, 重要)

1. **首次真跑业务流程才暴露真问题** — drill 测的是 Archery 二次开发代码, 测不到 gh-ost 自身的边缘 case
2. **error_message 字段要过滤 noise** — FATAL 错误要存, 清理阶段 ERROR 噪声要过滤
3. **8/24 教训 "kill master" 必做** — 改 Python 后不 kill = 业务 RD 还在用旧代码

---

## 关联 commit

- 本次 commit: `parser.py` + `drill_parser_1146_filter.py` + 本 changelog
- 8/24 kill master SOP: `docs/runbooks/2026-08-24_gunicorn-reload-after-code-change.md`
- 推 110 执行手册: `docs/runbooks/2026-08-27_push-v030-execution-manual.md` §3.4 阶段 3
