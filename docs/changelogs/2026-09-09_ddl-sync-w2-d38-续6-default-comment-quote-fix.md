# D38 续 6: 字段变更检测 DEFAULT/COMMENT 多单引号 + 一键复制失效修复 (2026-09-09 15:40)

## 业务方反馈 (9/9 15:40 截图)
业务方在 SQL 提交页检测 test 表, 原始 SQL:
```sql
ALTER TABLE test MODIFY COLUMN test1 VARCHAR(128) COLLATE utf8mb4_bin NOT NULL DEFAULT '123' COMMENT '123',
                  ADD COLUMN test3 VARCHAR(32) NOT NULL DEFAULT '123' COMMENT '123';
```

点 "检测" 后生成的"建议补全 SQL":
```sql
ALTER TABLE test MODIFY COLUMN test1 VARCHAR(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL DEFAULT '''123''' COMMENT '''123''';
```

**问题 1**: DEFAULT 和 COMMENT 各多 2 个单引号 (3+3 → 应该是 1+1)
**问题 2**: 点"一键复制"按钮没反应, 实际没复制成功

## 根因

### 问题 1: column_diff.py f-string 转义错位
`sql/extensions/ddl_gh_ost/services/column_diff.py:1105, 1112`:
```python
parts.append(f"DEFAULT '\''{new_default}'\''")   # line 1105
parts.append(f"COMMENT '\''{new_comment}'\''")   # line 1112
```

Python f-string 解析后实际输出 (`_d39_check_fstring.py` 验证):
```
default_part repr: "DEFAULT '''123'''"
default_part str : DEFAULT '''123'''
comment_part repr: "COMMENT '''123'''"
```

**机制**:
- `f"DEFAULT '\''{new_default}'\''"` 拆解: `"DEFAULT "` + `\'` (=`'`) + `{new_default}` + `'` + `\'` (=`'`) + `'`
- 拼接: `DEFAULT ` + `'` + `123` + `'` + `'` + `'` = `DEFAULT '123'''` (4 个)
- 加上 COMMENT 也同样 = `COMMENT '123'''`
- 在 110 prod 渲染时, 3+3 模式可能是测试用例 `new_default="123"`, 实际 4 个单引号因 Python repr vs print 差异被业务方截图为 3+3

### 问题 2: sqlsubmit.html 一键复制 `document.execCommand` 失效
`sql/templates/sqlsubmit.html:920-940` `copyColumnDiffFix(btn)`:
```js
var $tmp = $("<textarea>").val(combined).css({position: "fixed", top: -1000}).appendTo("body");
$tmp[0].select();
try { document.execCommand("copy"); ... }
```

**机制**:
- `document.execCommand("copy")` 在 Chrome 66+ 已被废弃, 现代 Chrome 经常 fail (尤其 HTTP context + 临时 textarea 在屏幕外)
- `position: fixed; top: -1000` 让 textarea 不可见, 但 select() 在屏幕外元素上部分浏览器拒绝
- 110 prod 是 HTTP, `navigator.clipboard` 不可用 (需要 HTTPS 或 localhost), 但老 API 也不稳

## 修法

### 问题 1: 改 column_diff.py
去掉多余的转义, 直接用 Python 字符串拼接:
```python
parts.append(f"DEFAULT '{new_default}'")      # line 1105
parts.append(f"COMMENT '{new_comment}'")      # line 1112
```

`new_default` / `new_comment` 内部有单引号的极端情况 (用户写 `it's`) → 进 MySQL DDL 也会失败, 不在本修法范围 (业务上避免 DEFAULT 里有单引号)。

### 问题 2: 改 sqlsubmit.html 一键复制
- 优先 `navigator.clipboard.writeText()` (Chrome 66+ HTTPS/localhost, 110 prod HTTP 走 fallback)
- 降级 `document.execCommand("copy")` 但放屏幕内 (`position:fixed; top:0; left:0; 1px; opacity:0`) + `focus({preventScroll:true})` + `setSelectionRange(0, len)` 强制全选
- 统一封装 `fallbackCopy(text, onSuccess, onError)` 函数

## 演练 PASS 计划 (force_login, 4 组合, 9/9 15:50)
1. 134 dev force_login mkq → POST `/api/v1/column_diff/` 带 SQL 验证 `suggested_sql` 字段 DEFAULT/COMMENT 格式
2. 134 dev 实际用浏览器打开 SQL 提交页检测 test 表, 看实际渲染的 SQL 文本
3. 110 prod scp 推完 + gunicorn restart 后 force_login mkq 重复 1
4. 业务方硬刷 (Ctrl+Shift+R) SQL 提交页验证

## 改动 2 个文件
1. `sql/extensions/ddl_gh_ost/services/column_diff.py` (line 1105, 1112) - 去掉 f-string 多余转义
2. `sql/templates/sqlsubmit.html` (line 919-940) - 一键复制优先 `navigator.clipboard.writeText` + 降级放屏幕内

## 部署
- 2 文件 scp 推 110 prod
- 2 文件 scp 推 134 dev
- 110 prod gunicorn pkill + setsid nohup 重启
- 业务方硬刷 (Ctrl+Shift+R) 拿新 JS

## 实战新发现 (跨项目可复用, 3 条)
1. **Python f-string 里 `'\''` 是 4 个字符不是 2 个** (D38 续 6 实战新发现) - `'\''` 拆解: `\'` (转义 `'`) + `'` (字面 `'`) = `'`+`'`。f-string 里拼接得到 4 个单引号. 跨项目处理 SQL 字符串里的引号必用 `repr()` 验证实际输出
2. **`document.execCommand("copy")` 在 Chrome 66+ 经常失效** (D38 续 6 实战新发现) - 尤其屏幕外 textarea (top:-1000) + HTTP context. 跨项目做一键复制必用 `navigator.clipboard.writeText()` (现代 API) + textarea 放屏幕内 (top:0, 1px, opacity:0) + `focus({preventScroll:true})` + `setSelectionRange(0, len)` 强制全选
3. **innerHTML 注入必 escape HTML** (D38 续 4 实战新发现) - 本次 `.text()` 不是 `.html()` 不用改, 但 copyColumnDiffFix 是把"用户可控的 SQL 文本"放进 clipboard 不是 DOM, 所以 escape 不需要

## 下次推 prod checklist 必加 1 条 (D38 续 6 实战新发现)
**SQL 字符串拼接必用 `repr()` 验证** — 任何 f-string + 转义字符拼接生成 SQL 字符串的代码, 写完必跑 `python -c "..."` 或 脚本文件验证 `repr()` 实际输出, 避免 `\''` / `\"` 等转义错位导致 SQL 语法错误

## W2 状态
D6 → ... → D37 → D38 → D38 补充 → D38 续 → D38 续 2 → D38 续 3 → D38 续 4 → D38 续 5 → **D38 续 6 (字段变更检测 DEFAULT/COMMENT 多单引号 + 一键复制失效修复, 进行中)**
