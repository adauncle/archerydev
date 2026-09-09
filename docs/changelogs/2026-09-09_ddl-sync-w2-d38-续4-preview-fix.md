# D38 续 4: 一键配 modal 预览前 20 张 修复 (2026-09-09 13:50)

## 业务方反馈
- 9/9 13:44 业务方反馈: "预览前 20 张, 点击没有弹出展示, 没反应"

## 根因 (D38 续 4 实战新发现)
- `_one_click_modal.html` 模板 line 31 + 45 有按钮 id:
  - `one-click-whitelist-preview` (白名单预览前 20 张)
  - `one-click-blacklist-preview` (黑名单预览前 20 张)
- **pair_detail.js 没有给这两个按钮绑 click 事件监听器**
- 业务方点击按钮, 按钮存在但 JS 不响应 → "没反应"

### 老代码漏的
- `bindOneClickSetup()` 函数只绑了 7 个 button/checkbox 事件:
  - one-click-whitelist-select-all
  - one-click-whitelist-deselect-all
  - one-click-blacklist-select-all
  - one-click-blacklist-deselect-all
  - one-click-whitelist-checkbox
  - one-click-blacklist-checkbox
  - one-click-confirm
- **漏了 one-click-whitelist-preview + one-click-blacklist-preview**

## 修法 (D38 续 4)
1. **template**: `_one_click_modal.html` 在白名单/黑名单按钮组下加 preview-list 区域 (默认 hidden, 单色灰背景, max-height 200px 滚动)
2. **JS**: `bindOneClickSetup()` 加 2 个 click listener + 新函数 `showOneClickPreview(type)` 渲染前 20 张表名
3. **JS**: 表名 HTML escape 防 XSS (业务方表名可能含特殊字符)

### 改动 2 个文件
1. `sql/extensions/ddl_sync/templates/ddl_sync/partials/_one_click_modal.html`
   - 白名单按钮组后加 `<div id="one-click-whitelist-preview-list">` 默认 hidden
   - 黑名单按钮组后加 `<div id="one-click-blacklist-preview-list">` 默认 hidden
2. `sql/extensions/ddl_sync/static/ddl_sync/pair_detail.js`
   - `bindOneClickSetup()` 加 2 个 click listener
   - 新函数 `showOneClickPreview(type)` 渲染前 20 张表名

## 演练 PASS (force_login mkq, 13:50)
- pair/1/ 渲染 status 200, len 75236
- modal-one-click-setup present: True ✅
- one-click-whitelist-preview button: True ✅
- one-click-blacklist-preview button: True ✅
- one-click-whitelist-preview-list div: True ✅ (default display: none)
- one-click-blacklist-preview-list div: True ✅ (default display: none)

## 部署
- 2 文件 scp 推 110 prod (md5: tpl `e0feec7e...da95` + js `4b952084...6926`)
- 2 文件 scp 推 134 dev (md5 一致)
- **静态文件改动不需重启 gunicorn** (Django DEBUG=True 每次请求重读 template, JS 是 static file)
- 业务方**需要硬刷** (Ctrl+Shift+R) 拿新 JS

## D38 续 4 实战新发现 (跨项目可复用)
1. **template 有 button 但 JS 没绑事件是隐藏 bug** (D38 续 4) - button id 跟 event listener 必须在 JS 双向走查. 跨项目改 template 加 button 必查 JS 有没有绑事件
2. **静态文件浏览器会缓存** (D38 续 4) - template 改完 Django 每次重读, 但 JS 静态文件浏览器缓存, 业务方必须 Ctrl+Shift+R 硬刷. 跨项目改 JS 必通知业务方硬刷
3. **innerHTML 注入必 escape HTML** (D38 续 4) - 表名从后端 data 注入 ul.innerHTML 前必 escape `&<>"'` 防 XSS. 跨项目所有 innerHTML 注入业务方可控字符串都必 escape

## 业务方硬刷验证清单
- 业务方按 Ctrl+Shift+R 硬刷 `/ddl_sync/pair/1/`
- 点击 "🎯 一键配" 打开 modal
- 等 compute_diff 完成后 (业务库 + 历史库扫表)
- 点击 "白名单 (业务库 ∩ 历史库) 69 张" 下面的 "预览前 20 张" 按钮
- 应该看到 modal 里出现 20 行表名 (灰底列表)
- 同样点 "黑名单 (业务库 - 历史库) 39 张" 下面的 "预览前 20 张", 看到 20 行黑名单表
