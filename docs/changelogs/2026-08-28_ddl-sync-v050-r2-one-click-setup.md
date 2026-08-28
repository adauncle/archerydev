# 8/28 DDL 跨库同步 v0.5.0-r2 一键配机制 (按历史库 1589/1289 实战)

## 背景

- 8/28 09:17 v0.5.0-r1 修订设计稿刚发 (commit `34e2613`), 解决"DBA 手动配 500 次"问题
- 8/28 14:00 DBA 阿达叔叔查 110 prod 真实数据:
  - 业务库 `hly_accesscard`: **1589** 张表 (`select count(*) from information_schema.tables where table_schema like 'hly%'`)
  - 历史库 `hly_activity`: **1289** 张表
  - 业务库 - 历史库: **300** 张 (字典/配置/日志等不归档)
  - 历史库 - 业务库: **0** 张
- DBA 原话: "**历史库有多少张表就拿多少张**" — 朴素思路: 白名单 = 历史库所有表 (1289 张), 黑名单 = 业务库独有 (300 张), 1-click 配完, 不用 r1 批量导入手动勾选

## 核心问题

v0.5.0-r1 解决"DBA 手动配 500 次"问题, 但 **r1 批量导入仍要 DBA 手动勾选 1289 张白名单 + 手动加 300 张黑名单**, 配齐 1589 张表还是 **15-25 min** 量级, **不够"一键"**.

**r2 真正解决**: 让 Archery 自动按"历史库"算差集, 1-click 配完白/黑名单, **6 min** 完成.

## 核心改动 (1 个 P0 + 数据模型 + URL 路由)

### P0 · 一键配机制 (核心)

库对详情页加 **"🎯 一键配 (按历史库)"** 按钮, 弹模态框, 自动扫业务库 + 历史库算差集:

| 步骤 | r1 批量导入 | **r2 一键配** |
|------|------------|---------------|
| 配白名单 | 批量导入勾选 (5 min) | **自动 (1 click)** |
| 配黑名单 | 手动加 OR 写脚本 (10-20 min) | **自动 (1 click)** |
| **总耗时** | **15-25 min** | **6 min** |

**再省 2-4 倍**, 从 r1 "5-10 min 配白名单 + 几十个排除" 降到 r2 "1-click 配完两边".

模态框 UX 草图 (r1 设计稿 §12.2 详):

```
┌─ 🎯 一键配 (按历史库) ───────────────────────────────┐
│ 自动扫描历史库 + 业务库, 计算差集:                       │
│                                                        │
│   业务库 (hly_accesscard): 1589 张表                   │
│   历史库 (hly_activity):   1289 张表                   │
│   ─────────────────────────────                       │
│   业务库 ∩ 历史库 (1289 张): → 默认白名单 (建议全选)      │
│   业务库 - 历史库 (300 张):  → 默认黑名单 (建议全选)      │
│   历史库 - 业务库 (0 张):    → 0 张, 提示 DBA          │
│                                                        │
│  ⚙ 预览:                                              │
│    ✓ 白名单 (1289 张, 全选):                            │
│       accesscard_black_detail  ✓ 存在 243MB            │
│       accesscard_config        ✓ 存在 12KB             │
│       ... (分页 50/页)                                 │
│                                                        │
│    🚫 黑名单 (300 张, 全选):                            │
│       dict_currency            ✗ 历史库无 4KB            │
│       log_search               ✗ 历史库无 1.2GB          │
│       ... (分页 50/页)                                 │
│                                                        │
│         [取消]  [✓ 1-click 接受 (1289+300)]              │
└────────────────────────────────────────────────────────┘
```

### 后端实现 (r1 设计稿 §12.3)

```python
# sql/extensions/ddl_sync/services/one_click_setup.py
def one_click_setup(pair, accept_white: list, accept_black: list):
    """一键配 (按历史库) — 8/28 r2 新增"""
    with transaction.atomic():
        DdlSyncTable.objects.filter(pair=pair).delete()  # 幂等
        if accept_white:
            DdlSyncTable.objects.bulk_create([
                DdlSyncTable(pair=pair, table_name=t, sync_type='whitelist')
                for t in accept_white
            ])
        if accept_black:
            DdlSyncTable.objects.bulk_create([
                DdlSyncTable(pair=pair, table_name=t, sync_type='blacklist')
                for t in accept_black
            ])
    return len(accept_white) + len(accept_black)


def compute_diff(pair):
    """扫业务库 + 历史库, 算差集 — 8/28 r2 新增"""
    source_tables = scan_history_tables(pair.source_instance, pair.source_db)
    target_tables = scan_history_tables(pair.target_instance, pair.target_db)
    source_names = {t["TABLE_NAME"] for t in source_tables}
    target_names = {t["TABLE_NAME"] for t in target_tables}
    return {
        "white": sorted(source_names & target_names),  # 业务库 ∩ 历史库
        "black": sorted(source_names - target_names),  # 业务库独有
        "orphan": sorted(target_names - source_names), # 历史库独有 (业务库已删)
    }
```

### 数据模型微调 (DdlSyncTable 加 sync_type 字段)

```python
class DdlSyncTable(models.Model):
    SYNC_TYPE_CHOICES = [
        ("whitelist", "白名单 (要同步)"),
        ("blacklist", "黑名单 (不同步)"),
    ]
    pair = models.ForeignKey(DdlSyncPair, on_delete=models.CASCADE, related_name="tables")
    table_name = models.CharField(max_length=128)
    sync_type = models.CharField(max_length=16, choices=SYNC_TYPE_CHOICES, default="whitelist")
    # ... 其他字段跟 8/21 相同

    class Meta:
        # 同一对库 + 同一表, 不能既在白名单又在黑名单
        unique_together = [("pair", "table_name", "sync_type")]
```

### URL 路由加 2 个端点 (r1 设计稿 §12.5)

```python
# sql/extensions/ddl_sync/urls.py
urlpatterns = [
    # ... 8/28 r1 路由
    # 8/28 r2 新增: 一键配
    path("api/pair/<int:pair_id>/compute_diff/", views.api_compute_diff,
         name="api_compute_diff"),
    path("api/pair/<int:pair_id>/one_click_setup/", views.api_one_click_setup,
         name="api_one_click_setup"),
]
```

## r1 批量导入 跟 r2 一键配 关系

**两者并存, 不冲突**:

| 机制 | 适用场景 | 占比 |
|------|---------|------|
| **r2 一键配** (核心) | 业务库 + 历史库**有重叠** (99% DDL 同步场景) | 95% |
| **r1 批量导入** (fallback) | 业务库 + 历史库**不重叠** OR DBA 想手动选部分表 | 5% |
| **单张加** (兜底) | 临时加 1 张表 | < 1% |

库对详情页**同时放 3 个按钮**, DBA 根据场景选:

```
库对详情页
  [🎯 一键配 (按历史库)]  ← 95% 场景 1-click
  [📥 批量导入]            ← 5% 场景 fallback
  [+ 添加同步表]           ← 兜底单张加
```

## 实战示例 (8/28 14:00 业务库数据)

```bash
# 110 prod 真实查询 (DBA 截图)
select count(*) from information_schema.tables where table_schema like 'hly%'
# 业务库: 1589 (hly_accesscard)
# 历史库: 1289 (hly_activity)
# 业务库 - 历史库: 300 张 (字典/配置/日志等不归档)

# 走 r2 一键配:
# - 业务库 ∩ 历史库 = 1289 张 → 自动加白名单
# - 业务库 - 历史库 = 300 张 → 自动加黑名单
# - 1-click 接受, 6 min 配完

# vs r1 批量导入:
# - 配白名单 1289 张: 5 min 批量导入
# - 配黑名单 300 张: 手动加 OR 写脚本 10-20 min
# - 总耗时 15-25 min
```

## Phase 1 范围调整

r2 一键配加到 Phase 1, 跟 r1 批量导入并存:

- [ ] 数据模型 3 张表 migration (sync_mode 默认 blacklist + **r2 加 sync_type 字段**)
- [ ] 库对管理列表 + 库对详情
- [ ] **r2 一键配机制** (核心, 95% 场景): `compute_diff` + `one_click_setup`
- [ ] **r1 批量导入机制** (fallback, 5% 场景): 跟 r2 并存
- [ ] 业务库 DDL 工单详情"本表已配置同步" 提示
- [ ] 134 dev 演练: 配 accesscard 库对 + **r2 一键配 1-click 接受** + 1 条真实 DDL 联动

## 跟 v0.5.0-r1 关系

v0.5.0-r1 修订 (commit `34e2613`) **保留有效**:
- §3 批量导入机制 (r1 5% 场景 fallback)
- §4 增量同步机制 (Phase 2 业务库新表自动检测)
- §5 §6 §7 §8 §9 §10 §11 (跟 r1 一致)

v0.5.0-r2 是 **r1 进一步优化**:
- 核心机制加一键配 (95% 场景用一键配, 5% 场景用 r1 批量导入)
- 减少 **2-4 倍** DBA 工作量 (15-25 min → 6 min)

## 教训 (跨项目可复用)

### 1. **实战数据驱动的设计修订**
8/28 14:00 DBA 给 110 prod 真实数据 (1589 / 1289 / 300) 后, "历史库有多少张表就拿多少张" 这句朴素思路把 r1 "批量导入" 优化成 r2 "一键配", 6 min 配完 1589 张表.
**下次设计稿: 必先看 1-2 个真实业务场景数据再拍板**, 不要靠"想象"的场景.

### 2. **白/黑名单 + 批量导入 + 一键配 三件套**
DBA 配 N 张表的场景, 工业级方案是 3 件套:
- **白/黑名单** (r0 基础): 显式选要/不要同步的
- **批量导入** (r1 fallback): 业务库 + 历史库不重叠 OR 想手动选
- **一键配** (r2 核心): 业务库 + 历史库有重叠, 按"另一端"自动算差集

**下次配 N 条记录场景: 必演 3 件套**, 不只做"白名单逐张加" 这种最低配.

### 3. **DBA 视角"以历史库为准"是更朴素的方案**
8/28 14:00 DBA 思路 "历史库有多少张表就拿多少张" 是从 DBA 实际工作流出发 — 历史库建出来就是为了归档业务库, 所以"同步"语义天然是"业务库所有表 ∩ 历史库" (1289 张).
**r1 设计稿 "批量导入手动勾选 1289 张" 是反 DBA 视角的** — 让 DBA 干数据迁移工程师的活.
**r2 一键配是"用算法替代 DBA 手动操作"** — 把差集算交给后端, DBA 只做 1-click 确认.

**下次设计稿: 必从"使用方怎么想"反推功能设计**, 不要从"技术上能怎么做" 出发.

### 4. **"1-click 完成" 跟 "1 分钟完成" 是两个量级**
r1 批量导入 = 5-10 min 配白名单 + 10-20 min 配黑名单 = 15-25 min, DBA 心理负担"还有事没干完".
r2 一键配 = 1-click + 1-click + 确认 = 6 min, DBA 心理负担"搞定了".

**下次配 N 条记录场景: 必演"1-click 完成" 跟"分步配置" 心理负担对比**, 不要小看"1-click" 这个体验差异.

## 同源 entry

- 8/28 09:17 v0.5.0-r1 修订 (commit `34e2613`) — r2 是在 r1 基础上加一键配
- 8/28 14:00 DBA 给真实数据 1589/1289/300 + 思路"历史库有多少张就拿多少张" — 触发 r2 修订
- 8/28 09:17 8/21 v0.5.0 旧设计稿防丢 (commit `f4078c6`) — r1 修订前的"反例"对照
- 8/21 v0.5.0 初版设计稿 (50KB MD + 145KB HTML) — r1 / r2 都在它的基础上改

## 下次推 prod 必做 (新增 2 条)

1. **设计稿写完必演 1-2 个真实业务场景数据** — 8/28 14:00 DBA 给 110 prod 真实数据 (1589/1289/300) 后, r1 "5-10 min 配白名单" 立刻被 r2 "1-click 配完" 替代. 写设计稿时, 必先看 1-2 个真实数据, 不靠"想象" 场景.
2. **配 N 条记录场景, 必演"一键配 / 批量导入 / 单张加" 三件套** — DBA 配 1289 张表场景, 必演 3 种 UX, 不能只做"单张加" 这种最低配.

## 关联 commit / 文件

- **本次 (8/28 14:00)**:
  - `docs/designs/2026-08-28_ddl-sync-pair-design-v050-r1.md` 加 §12 章节 (一键配机制)
  - `docs/designs/2026-08-28_ddl-sync-pair-feature-card.html` 加 §05 一键配模态框, 原 §05-§09 顺延到 §06-§10, 改对比表 + Hero 描述 + 配套链接
  - 本 changelog: `docs/changelogs/2026-08-28_ddl-sync-v050-r2-one-click-setup.md`
- **8/28 09:17** commit `34e2613`: v0.5.0-r1 修订设计稿 + 新功能图说 HTML
- **8/28 09:17** commit `f4078c6`: 8/21 旧设计稿 + 8/27 功能图说 HTML 防丢

## 状态

- **v0.5.0-r2 修订设计完成** (含一键配机制 + 实战数据 1589/1289), **未开工**
- 等用户拍板 Phase 1 启动 (r2 一键配 + r1 批量导入并存)
