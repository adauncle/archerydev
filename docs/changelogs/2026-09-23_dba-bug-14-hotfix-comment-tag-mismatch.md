# 9/23 DBA-bug-14 hotfix: 注释里的字面 Django 标签导致 500

**日期**: 2026-09-23 14:22 阿达叔叔反馈
**症状**: 110 prod `wf#4885` 详情页 500 Internal Server Error, `TemplateSyntaxError: Invalid block tag on line 2050: 'endblock'`
**根因**: DBA-bug-14 (commit `509e489`) 改 detail.html 时, 注释里**直接写了** `\`{% if big_table_alert %}\`` 这种字面 Django 标签字面量, **被 Django 模板 parser 当成真模板标签 parse**
- Django parser 不识别反引号 `` ` ``, 它只看 `{%` `}` 字符
- 结果: 多 1 个 if 标签, 少 1 个 endif → `{% endblock %}` 触发 "expected 'elif', 'else' or 'endif'" 报错
- 实际报错位置是 line 2050 `</script>`, 但根因在 line 1884 (hotfix 注释里又写了一遍同样的字面标签)

**修法** (1 文件 2 处, `detail.html:1877-1885`):
- 把注释里 `{% if big_table_alert %}` 这种字面 Django 标签字面量**全部改写**为不带 `{%` `}` 符号的描述
- 例: `\`{% if big_table_alert %}\`` → `big_table_alert 判断块`
- 例: `\`{% if big_table_alert %}\` 这种字面 Django 标签` → `这种字面 Django 标签`

**演练**:
- 静态: `if=49, endif=49` 平衡 ✅
- 134 dev 真实 GET wf#4885 详情页 → 返回 `<!DOCTYPE html>` (非 500 页面) ✅
- 134 dev error.log 最近 20 行无新错误 ✅
- 110 prod HUP reload + HTTP 200 ✅
- 110 prod if/endif 平衡 ✅

**实战新发现 (跨项目可复用)**:
- **Django 模板里 `//` JS 注释不是 Django 注释, Django parser 不会跳过**
- 写注释时**绝对不能**带 `{%` 或 `}` 字符 (反引号 `` ` `` 不能 escape 它们)
- 演练 Django parse 必须**用项目自己的模板配置** (mock 的 Django 缺 `format_tags` 等自定义 tag library 也会报错的, 不一定是根因)
- 演练 if/endif 平衡**只数真标签**, 注释里的字面量要**先去掉**再数 (不然数不准)
- 实战教训: 写代码注释时, 提到 Django 标签用 "X 块" / "X 判断" 等描述, 不要直接写 `{% X %}`

---

## 部署 (DBA 一条龙)

1. **134 dev (9/23 14:25)**:
   - scp detail.html → `/opt/archery/prod/sql/templates/detail.html`
   - `systemctl restart archery-prod-gunicorn.service` + sleep 4
   - 真实 GET `wf#4885` 详情页 → `<!DOCTYPE html>` ✅
   - error.log 最近 20 行无新错误 ✅
2. **110 prod (9/23 14:28)**:
   - scp detail.html → `/dbdata/archery_v114_c9236a0/sql/templates/detail.html`
   - gunicorn HUP reload (master pid=109396) + sleep 4
   - HTTP 200 ✅
   - if/endif 平衡 49/49 ✅

---

## 实战测 (阿达叔叔)

wf#4885 详情页硬刷新 (Ctrl+F5):
- ✅ HTTP 200, 详情页正常渲染
- ✅ 只有 1 个大表 alert 块 (DBA-bug-14 修复目标)
- ✅ 没有下方重复的纯文案块
- ✅ 字段 diff 按钮 + DBA 兜底启用 gh-ost 按钮 + 立即执行双层 confirm 全在

---

## 关联

- 9/23 DBA-bug-14 (commit `509e489`): 删除 JS 拼装 bigTableAlertHtml 重复块 (本 hotfix 修这次引入的注释)
- 8/11 ~ 9/23 detail.html 大表 alert 块 (line 557-614) 设计源头
- 9/22 DBA-bug-13 第一波 can_enable_ghost 守卫 (DBA-bug-14 修复依赖)

---

## commit

待提交: `fix(detail): DBA-bug-14 hotfix 注释字面 Django 标签导致 500 (DBA-bug-14 hotfix)`

CHANGELOG: docs/changelogs/2026-09-23_dba-bug-14-hotfix-comment-tag-mismatch.md
关联: commit 509e489 (DBA-bug-14 主修复)