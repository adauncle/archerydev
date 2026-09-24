docs: README 添加 6 大新功能章节 (2026-09 上线)

- 阿达叔叔 9/24 10:38 要求更新 git README 文件, 列出 6 大功能说明
- 6 大新功能 (基于真实业务工单闭环, 9/11-9/22 实战接龙 33+ commit):
  1. 字段 diff 弹窗 (9/11 实战, wf#4791)
  2. 大表无锁变更 (gh-ost + v0 智能模式, wf#4841 154GB 大表演练)
  3. 历史库同步 (DDL-Sync + Bug-A, wf#4841/4848/4849)
  4. 提交工单限制单库 (9/16 新上线, wf#4834)
  5. 插入主键冲突检测 (9/16 新上线, wf#4834)
  6. v1 混合 DDL 禁止 + CREATE INDEX 兼容 (9/17 新上线, wf#4849)
- 详情设计/commit 链路/演练 case 链到 docs/reports/ 6 大功能大纲文档
- README 保持简洁 (16 行新加), 实战细节仍在 changelog + reports

CHANGELOG: docs/changelogs/2026-09-24_readme-6大新功能.md