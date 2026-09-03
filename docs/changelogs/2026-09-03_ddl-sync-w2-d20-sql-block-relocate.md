# W2 D20 — 镜像工单 SQL 块从 alert 块挪到 8/26 inline 区域 (9/3 11:05)

## 背景

D19 9/3 10:15 推了镜像工单 alert 块 SQL 显示 (commit `a4abf01`),
业务 RD 验证能看到了。

9/3 11:04 业务 RD 反馈: **"sql不应该用原本的位置展示吗"**

用户意思: SQL 块不应该在 alert 块里 (二次开发加的突兀位置), 应该跟
Archery 原本设计挨着,体验更原生。

## 实战根因

- D19 把 SQL 块放在镜像工单 alert 块内 (蓝色块里), 体验突兀
- Archery 原本设计: SQL 藏在 "工单详情-展开全部" 主表子表 (line 1116
  `detailView: true` + `detailFormatter` 渲染完整 SQL)
- 等审批时主表空 → 子表展不开 → 用户看不到 SQL
- D19 修法绕过了 Archery 主表设计, 抢了 alert 块的位置, 跟原本设计冲突

## 修法 (单文件 detail.html)

### 1. 删除 alert 块里的 SQL 块 (D19 加的, 449 字节)

```python
# 实战用 re 删除
old_sql = re.search(r"\n    \{\% if mirror_sql_content \%\}.*?\{\% endif \%\}\n", d, re.DOTALL)
d = d.replace(old_sql.group(), "\n")
```

### 2. 在 8/26 21:34 字段变更检测 inline 区域 (line 688 `<div id="column-diff-result">`) 之后插新 SQL 块

```html
<div id="column-diff-result" style="display:none; margin-top:14px;"></div>

{# CUSTOM-MODIFIED: D20 镜像工单 SQL 内容直接显示 (9/3 11:05 实战) @ 2026-09-03 @ mavis #}
{# 业务: 业务 RD 拿到镜像工单想知道"这工单到底要执行什么 SQL" #}
{# 修法: SQL 块挪到 8/26 inline 字段变更检测区域旁边 (跟原本设计挨着) #}
{% if mirror_sql_content %}
<div style="margin-top: 14px; padding: 14px; background: #f5f5f5;
            border-radius: 4px; border-left: 4px solid #5bc0de;">
    <strong>📝 镜像工单 SQL 内容 (自动生成, 走当前配置审批流):</strong>
    <pre style="background: white; padding: 10px 12px; border-radius: 4px;
                margin-top: 8px; margin-bottom: 0;
                font-family: 'Courier New', monospace; font-size: 13px;
                white-space: pre-wrap; word-wrap: break-word;
                max-height: 240px; overflow-y: auto;">{{ mirror_sql_content }}</pre>
</div>
{% endif %}

{% endblock content %}
```

### 3. 样式要点

- 灰底 + 蓝色左边框 (`#5bc0de`) 跟 8/26 inline 区域视觉关联
- `<pre>` 渲染: Courier New + pre-wrap + max-height 240 + overflow-y auto
- 标题 emoji `📝` + 文字 "(自动生成, 走当前配置审批流)" 解释用途

### view 端不动

D19 加的 `mirror_sql_content` 还在 context dict 里, 复用 (SQL 提取
逻辑不需要重做)。

## 134 dev 演练 (Django test client + force_login archery)

`/detail/123/` (新镜像工单 wf#123, status=`workflow_manreviewing` 等审批):

| 验证项 | 期望 | 实际 |
|------|------|------|
| HTTP Status | 200 | 200 ✓ |
| Content length | 增长 | 95659 ✓ |
| 🤖 镜像工单 alert (D18 标识) | 1 次 | 1 ✓ |
| D19 alert 块 SQL 标题 (应该不存在) | 0 | 0 ✓ (D19 撤回干净) |
| D20 镜像工单 SQL 块 (新位置) | 1 次 | 1 ✓ |
| 📝 emoji 块标题 | 1 次 | 1 ✓ |
| 完整 SQL pre 块 | 1 次 | 1 ✓ |
| test3 SQL 关键字 | 多个 | 9 ✓ |
| 源工单 wf#122 link | 1 次 | 1 ✓ |
| 8/26 inline 区域 | 1+ | 3 ✓ |
| 目标库 hly_accesscard_history | 1+ | 5 ✓ |
| SQL 块在 column-diff-result 之后 | ✓ | ✓ (挨着 8/26 inline 区域) |
| alert 块里没 SQL 块 | ✓ | ✓ (D19 已撤回) |

## 134 dev 部署

- 备份 `/backup/d20_20260903_1105/` (detail.html.bak 原始 D19 版本)
- SFTP 推 `detail.html` (md5 `16a34b54...` = local)
- gunicorn pids: 32184 (master) + 32187-32190 (4 worker, 11:08 拉新)
- 9003 端口 LISTEN ✓

## 实战新发现 (D20 实战总结)

1. **二次开发 UX 必先看 Archery 原本设计再改**: 不要在 alert 块里塞新功能,
   必看 Archery 原本的字段 diff / 审批流 / 其他信息 / 工单详情-展开全部
   区域, 二次开发新功能应该融入而不是抢戏
2. **二次开发 UX 必问用户拍板位置**: alert 块 (顶部显眼但突兀) vs inline
   区域 (挨着原本设计) vs modal (折叠) vs 新建独立区域. 实战前必 3 选项
   拍板, 不要默认塞 alert 块 (D19 实战踩坑)
3. **撤回 + 挪位置实战套路**: 不要在新功能上加新功能 (D19 → D20), 实战
   前看 Archery 原本设计, 直接在新位置加, 不要先加 alert 块再撤回
4. **用户反馈 "不应该用原本位置展示吗" 是关键信号**: 业务 RD 拿工单
   时, 知道 Archery 原本设计, 二次开发块应该跟原本设计挨着, 不要塞
   alert 块让用户看突兀

## 110 prod 状态 (待推)

- 110 prod `detail.html` 仍是 7/19 上游版 (md5 `82198afe...`), 没 D20 SQL 块
- 110 prod 推 4 功能一起:
  - 8/26 21:34 字段 diff inline 区域 (commit 0a04775)
  - 9/2 17:30 JS ReferenceError 修复 (commit 2a04a12)
  - 9/2 22:30 DDL 跨库同步镜像/源工单 alert 块 (commit 55ec7fa)
  - 9/3 11:05 镜像工单 SQL 块挪到 8/26 inline 区域 (本次)

## 同源 entry

- D19 9/3 10:15 alert 块 SQL 块 (commit `a4abf01`) - **D20 撤回**
- D18 9/2 22:30 镜像/源工单 alert 块 (commit `55ec7fa`) - 保留, 跟 D20 配合
- 8/26 21:34 字段变更检测 inline 区域 (commit 0a04775) - D20 SQL 块紧挨着
- 8/26 21:57 JS ReferenceError 修复 (commit 2a04a12) - escapejs 教训复用
- 9/1 18:00 D9 `sync_trigger.py` (commit 5420c81) - `SqlWorkflowContent` OneToOne

## W2 进度 (D20 新增)

- D6 ✓ (9/1 14:45): 3 张表 migration
- D7 ✓ (9/1 16:15): 库对管理 CRUD + admin + 2 template + base.html
- D8 ✓ (9/1 17:45): 5 AJAX 端点 + 4 service + pair_detail + 5 modal + JS
- D9 ✓ (9/1 18:15): R3 走当前配置 + signal + 8/13 教训应用
- D10 ✓ (9/2 10:30): 134 dev 端到端演练 5 Case
- D11 ✓ (9/2 11-15): 134 dev 6 hotfix
- D12 ✓ (9/2 17:30): 134 dev detail/119 JS ReferenceError 修复
- D13 ✓ (9/2 18:30): 多表 DDL 字段 diff bug 修复
- D14 ✓ (9/2 19:40): 推 110 prod 修复汪银和工单 (commit ed1c20c)
- D15 ✓ (9/2 20:30): 字符集 implicit/explicit 区分 (commit e939ffe)
- D16 ✓ (9/2 21:10): 推 D15 修复实战 110 prod c9236a0 (commit 289adc7)
- D17 ✓ (9/2 21:43): 验证 110 prod D15 修复实战生效
- D18 ✓ (9/2 22:30): DDL 跨库同步 镜像/源工单 alert 块 (commit 55ec7fa)
- D19 ✓ (9/3 10:15): alert 块 SQL 显示 (commit a4abf01)
- **D20 ✓ (9/3 11:05): 撤回 D19, 挪到 8/26 inline 区域旁边 (本次)**

## 下次推 prod checklist 必加 (D20 实战新发现)

1. **二次开发 UX 必先看 Archery 原本设计再改**: 不要在 alert 块里塞新功能,
   必看 Archery 原本的字段 diff / 审批流 / 其他信息 / 工单详情-展开全部
   区域, 二次开发新功能应该融入而不是抢戏
2. **二次开发 UX 必问用户拍板位置**: alert 块 (顶部显眼但突兀) vs inline
   区域 (挨着原本设计) vs modal (折叠) vs 新建独立区域. 实战前必 3 选项
   拍板, 不要默认塞 alert 块 (D19 实战踩坑)
3. **撤回 + 挪位置实战套路**: 不要在新功能上加新功能 (D19 → D20), 实战
   前看 Archery 原本设计, 直接在新位置加, 不要先加 alert 块再撤回
4. **用户反馈 "不应该用原本位置展示吗" 是关键信号**: 业务 RD 拿工单
   时, 知道 Archery 原本设计, 二次开发块应该跟原本设计挨着, 不要塞
   alert 块让用户看突兀
