# 二次开发规范

> 目标：让定制代码可维护、可升级、可追溯。

## 1. 三条铁律

1. **不直接改上游核心** —— 优先用插件/扩展/Django app 隔离
2. **每次变更都要有 changelog** —— 放 `docs/changelogs/`
3. **保持可升级** —— 写清楚改动影响范围

## 2. 工作流选择

| 工作流 | 适用场景 | 怎么同步上游 |
|--------|----------|--------------|
| **Fork + 改源码** | 改动大、覆盖核心 | `git remote add upstream` 后 `merge`/`rebase` |
| **Patch 模式** | 改动小、想保持纯上游 | 修改后 `git diff` 存到 `patches/`，重放 |
| **子模块/扩展 app** | 改动独立、不碰核心 | 升级时几乎零成本 |

**默认推荐：Fork + 扩展 app 组合**。

## 3. 改动分类与处理方式

### 3.1 业务定制（首选）
- 新建 Django app：`sql/extensions/<feature>/` 或 `custom_<feature>/`
- 在 `INSTALLED_APPS` 注册
- 不动 `sql/`、`common/` 等核心

### 3.2 必须改上游代码
- 在被改文件顶部加注释：
  ```python
  ## CUSTOM-MODIFIED: <简要原因> @ 2026-07-20 @ <你的名字>
  ## 关联 changelog: docs/changelogs/2026-07-20_xxx.md
  ```
- 在 `docs/changelogs/` 写明改动位置、原因、回滚方法
- 同步上游时手动 review 这部分

### 3.3 配置项
- 全部走环境变量（见 `.env.example`）
- 命名规范：`CUSTOM_<MODULE>_<KEY>`
- 默认值在 `archery/settings.py` 顶层 `os.environ.get(...)` 中声明

## 4. 命名与目录约定

```
sql/extensions/                  # 上游核心模块的扩展
  └── <feature_name>/
      ├── __init__.py
      ├── apps.py
      ├── models.py
      ├── views.py
      ├── serializers.py
      ├── urls.py
      ├── tasks.py
      ├── services/             # 业务逻辑
      └── tests/

custom_<feature>/                # 全新独立功能
  └── ...

docs/changelogs/
  └── YYYY-MM-DD_<short-name>.md # 每次提交一个
```

## 5. changelog 模板

```markdown
# <简短标题>

**日期**：YYYY-MM-DD
**作者**：<name>
**影响范围**：<modules>
**风险等级**：低/中/高

## 背景
为什么要做这个改动？

## 改动内容
- 关键点 1
- 关键点 2

## 涉及文件
- `path/to/file.py:123` —— 改动说明

## 回滚方案
怎么撤销这个改动？

## 测试
- [ ] 单元测试
- [ ] 手动验证步骤
```

## 6. 升级上游流程

```bash
# 1. 拉取上游
git fetch upstream
git checkout main

# 2. 合入（团队约定 merge 或 rebase）
git merge upstream/master   # 或 git rebase upstream/master

# 3. 解决冲突
# 重点关注：
#   - 标记了 CUSTOM-MODIFIED 的文件
#   - INSTALLED_APPS / URLConf / settings
#   - 数据库迁移文件

# 4. 跑测试
docker-compose run --rm archery pytest

# 5. 升级记录
# 在 docs/changelogs/ 写明上游版本升级 + 冲突解决
```

## 7. 提交规范

见根目录 `AGENTS.md` 的"提交规范"一节。

## 8. 禁止事项

- ❌ 直接在 settings.py 硬编码凭据
- ❌ 把 `*.sql` 真实数据提交到仓库
- ❌ 不写 changelog
- ❌ 把上游文件改完不标注
- ❌ 引入与上游冲突的依赖版本
