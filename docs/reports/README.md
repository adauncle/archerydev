# 功能开发计划 · 维护说明

主表：`2026-08-06_功能开发计划_v3.xlsx`

## 何时更新

每次新增功能 / 修复重要 bug / 推送新版本时，**在 commit 之后追加一行**到主表。

## 怎么更新

用 `scripts/record_feature.py` 一行命令搞定，不用手开 Excel。

### 1. 简单用法（必填主功能 + 子项目）

```bash
python scripts/record_feature.py --group ghost --name "v0.4.0 列压缩"
```

`--group` 支持 alias：`ghost` / `gh-ost` / `ddl` 都自动映射到 `gh-ost 无锁 DDL`。
完整 alias 用 `--list-groups` 看。

### 2. 完整用法（推荐）

```bash
python scripts/record_feature.py \
    --group ghost \
    --name "v0.4.0 列压缩" \
    --status 待办 \
    --risk 中 \
    --owner mavis \
    --days 2 \
    --scenario "大表加列不再重建" \
    --howto "admin 勾选列压缩 + auto gh-ost" \
    --auto-git
```

- `--auto-git`：自动从 git HEAD 拿 commit hash + 日期（不传就用今天）
- `--scenario` + `--howto`：自动拼成 `【场景】xxx【使用】xxx` 写到「功能说明」列
- `--pct 0.5`：半完成 50%（默认 0）

### 3. 列说明

| 列 | 必填 | 取值 |
|---|---|---|
| 主功能 | ✓ | `平台基础` / `钉钉 OA 集成` / `gh-ost 无锁 DDL` / `收尾` |
| 子项目 | ✓ | 自由文本 |
| 完成时间 | | `YYYY-MM-DD`（默认今天） |
| 完成进度 | | 0~1（默认 0） |
| 状态 | | `已发布` / `待办` / `TBD` / `可选`（默认 待办） |
| 关键 commit | | git short hash（默认用 git HEAD） |
| 风险等级 | | `高` / `中` / `低` / `无`（默认 低） |
| 负责人 | | `mavis` / `阿达叔叔` / `DBA` / `TBD（独立项目）` |
| 投入人天 | | 数字 或 `待估` |
| 备注 | | 自由文本 |
| 功能说明 | | 自由文本（用 `--scenario` + `--howto` 自动拼） |

### 4. 撤销误录

```bash
python scripts/record_feature.py --delete "v0.4.0 列压缩"
```

按子项目名精确匹配删除。

### 5. Excel 进程占用

如果 v3.xlsx 被 Excel 打开（Permission denied），脚本会自动写到一个带时间戳的副本（如 `..._v3_1430.xlsx`），**关掉 Excel 后手动覆盖 v3.xlsx** 即可。

### 6. 公式自动重算

「汇总统计」/「按风险等级」/「按负责人」3 个 sheet 用 `COUNTIF/COUNTIFS/SUMPRODUCT/TEXTJOIN` 公式。打开 Excel 后按 `F9` 强制重算，或在「公式」→「计算选项」选「自动」。

### 7. 完整流程（推荐）

```bash
# 1. commit 代码
git add . && git commit -m "feat(gh-ost): v0.4.0 列压缩"

# 2. 跑 record_feature 自动记录
python scripts/record_feature.py \
    --group ghost --name "v0.4.0 列压缩" \
    --scenario "..." --howto "..." --auto-git

# 3. （可选）commit .xlsx 改动
git add docs/reports/2026-08-06_功能开发计划_v3.xlsx
git commit -m "docs: 同步 v0.4.0 列压缩到功能开发计划"
```

## sheet 结构

- **功能开发计划**（主表，11 列）—— 4 大主功能分组的明细
- **汇总统计** —— 按主功能算子项目数 / 已完成 / 完成率 / 高风险数 / 投入人天（公式）
- **按风险等级** —— 用 `TEXTJOIN` 把高/中/低风险的子项目名拼出来（公式）
- **按负责人** —— 算每个角色已交付/待办/人天（公式）

## 4 个主功能分组的语义

| 分组 | 含义 |
|---|---|
| 平台基础 | Archery 本身的部署、运维、发布工具（v0.1.0 - v0.1.9 + 拓扑 + 脚本） |
| 钉钉 OA 集成 | v0.2.0+ 的钉钉 OA 审批集成（含 v0.2.1~v0.2.3 待办） |
| gh-ost 无锁 DDL | v0.3.0+ 的 gh-ost 集成（设计、alpha、beta、推 110、提上游） |
| 收尾 | 清理 / 升级 / 独立项目（不属于主功能） |

新增功能分到哪个组，按上面的语义判断。
