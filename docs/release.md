# 发布/升级流程

## 1. 版本号约定

`<upstream>.<custom>`

例：

- `1.14.0.0` —— 基于上游 1.14.0，无内部 patch
- `1.14.0.1` —— 内部第 1 个 patch
- `1.15.0.0` —— 同步到上游 1.15.0

Tag 命名：`v<upstream>.<custom>`，如 `v1.14.0.1`。

## 2. 内部 patch 发布

```bash
# 1. 确保 main 分支干净，所有 PR 已合并
git checkout main
git pull

# 2. 准备 changelog
# 编辑 docs/changelogs/<date>_<feature>.md

# 3. 升级版本号（在 archery/__init__.py 或 setup.cfg）
# __version__ = "1.14.0.1"

# 4. 打 tag
git tag -a v1.14.0.1 -m "feat: <feature summary>"
git push origin main --tags
```

## 3. 同步上游

```bash
# 1. 创建升级分支
git checkout main
git pull
git checkout -b chore/upgrade-1.15.0

# 2. 拉取上游
git fetch upstream
git merge upstream/master

# 3. 解决冲突
# 重点检查：
#   - requirements.txt
#   - sql/models.py 的 migrations/
#   - archery/settings.py
#   - 所有标记了 CUSTOM-MODIFIED 的文件

# 4. 跑测试
docker-compose run --rm archery pytest

# 5. 写升级 changelog
# docs/changelogs/<date>_upgrade-upstream-1.15.0.md

# 6. 合入 main，打 tag
git checkout main
git merge chore/upgrade-1.15.0
git tag v1.15.0.0
git push origin main --tags
```

## 4. 灰度发布

- 内部：先在 staging 环境跑 1 周
- 生产：先小流量切 10%，观察 1 天再全量
- 回滚：保留上一个 tag 镜像，`docker-compose` 切回上一个 tag 即可

## 5. 数据迁移

涉及模型变更时：

1. 写迁移文件（Django 标准做法）
2. 写回滚 SQL（`docs/migrations/` 留底）
3. 大表 ALTER 提前评估锁表时间
4. 生产执行前在 staging 全量演练

## 6. 通知

- 发布前：在团队群发预告
- 发布完成：贴 release notes 链接
- 故障：第一时间回滚，再分析
