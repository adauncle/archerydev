# v0.5.0 自定义文档库 · 详细设计稿

> **核心约束 (8/24 18:11 拍板)**:
> 1. **只 DBA 上传** (设计规范 / 运维手册), 全员可看
> 2. **完全不绑定** (跟库/表/SQL 工单无关联, 纯平台文档库, 类似百度网盘内部版)
> 3. **支持 5 种文件类型**: Markdown / HTML / PDF / Word (.docx) / Excel (.xlsx)
>
> **跟 8/24 `/dbaprinciples/` 500 bug 修复的关系**: `/dbaprinciples/` 当前显示 `docs/upstream/docs.md` (单文件 read-only), 升级为本设计稿描述的"文档库"后, 该页面作为**文档库的入口 / 文档列表页**, 但单文件 read-only 行为保留 (兼容)。
>
> **作者**: mavis  ·  **日期**: 2026-08-24  ·  **目标版本**: v0.5.0  ·  **预计工作量**: 2-3 周 (Phase 1)

---

## 目录

- [01 业务背景 & 用户痛点](#01-业务背景--用户痛点)
- [02 核心定位 & 设计原则](#02-核心定位--设计原则)
- [03 用户场景 & 业务流](#03-用户场景--业务流)
- [04 功能范围 & Phase 划分](#04-功能范围--phase-划分)
- [05 数据模型](#05-数据模型)
- [06 权限模型](#06-权限模型)
- [07 后端架构](#07-后端架构)
- [08 前端架构](#08-前端架构)
- [09 文件存储 & 安全](#09-文件存储--安全)
- [10 推 110 / Roadmap / 风险](#10-推-110--roadmap--风险)

---

## 01 业务背景 & 用户痛点

### 1.1 现状

Archery v1.14.0 平台现有 "相关文档" 功能非常原始:
- `/dbaprinciples/` 页面硬编码读 `docs/docs.md` 单个文件 (8/24 17:12 修复 FileNotFoundError, 见 changelog `2026-08-24_dbaprinciples-file-not-found.md`)
- 即使文件存在, 业务用户**只能看不能维护**
- 文档内容跟平台代码绑死, **DBA 加新规范需要改代码部署**

### 1.2 业务用户痛点 (8/24 演示稿 / 日常反馈)

| 角色 | 痛点 | 频率 |
|------|------|------|
| 业务 RD | "我想看 `hly_accesscard` 表的设计规范, 但不知道问谁" | 每天 |
| 业务 RD | "DBA 给我发的设计规范链接在内部 Wiki, 我登录另一个系统才能看" | 每周 |
| DBA | "我维护了 10+ 份设计规范, 每改一份都要走代码 review 部署" | 每月 |
| DBA | "业务 RD 问的重复问题, 我每次都重新发同一个文件" | 每天 |
| 新人 | "新人入职, 我手把手介绍 20 个核心表, 没效率" | 每月 |

### 1.3 业务收益估算

| 指标 | 现状 | 上线后 (估算) |
|------|------|---------------|
| DBA 维护文档耗时 | 1 小时/规范/季度 (走代码) | 10 分钟/规范/季度 (走平台) |
| 业务 RD 查规范耗时 | 1-2 小时 (问人 + 找文件) | 5 分钟 (平台搜索) |
| 重复咨询次数 | 20+/周 | 5/周 |
| 新人入职培训 | 1 对 1, 半天 | 自助式, 1 小时 |

### 1.4 跟 8/24 已做工作的关系

| 已做 | 关系 |
|------|------|
| 8/24 修 `/dbaprinciples/` 500 错 | 解决了"读"的问题, 但 "写" 还是空缺 |
| 8/24 gh-ost 任务管理列表页 (v0.3.0-beta) | 同样的"权限细分 + DBA 专属"模式, 直接复用 |
| 8/24 DDL 智能回滚 (v0.4.5) | 同样的"扩展 Django app" 模式, 复用 `extensions/` 目录 |
| 8/06 RaccoonX 接入设计稿 | 同样是 v0.5.0 Roadmap, 本设计稿并行 |
| 8/06 DDL 跨库同步设计稿 | 同样是 v0.5.0 Roadmap, 本设计稿并行 |

---

## 02 核心定位 & 设计原则

### 2.1 产品定位 (一句话)

> **"Archery 平台内置的轻量级文档库, DBA 单边维护设计规范 / 运维手册, 全员随时查。"**

不是:
- ❌ Notion / Confluence 替代品 (那是 Wiki 系统, 范围太大)
- ❌ 百度网盘 (那是个人文件存储, 范围更窄)
- ❌ SQL 工单的"附件" (本设计稿**完全不绑定 SQL 工单**)

是:
- ✅ Archery 平台菜单的**新功能模块**
- ✅ 跟 8/24 `/dbaprinciples/` 500 bug 修复的**升级版**
- ✅ DBA 工作流的一部分 (跟 gh-ost 任务管理、DDL 智能回滚并列)

### 2.2 设计原则 (5 条)

1. **简单优先 (Simple First)**: Phase 1 只做核心 (上传/下载/预览/搜索), 不做版本/审批/全文检索等高级功能
2. **DBA 中心 (DBA-Centric)**: 文档所有权 100% 在 DBA 团队, 业务用户只读, 减少协作成本
3. **不绑定 (Decoupled)**: 跟库/表/SQL 工单无任何外键关联, 避免"加一个文档需要改库/表/工单" 的爆炸半径
4. **Archery 风格一致 (Consistent UX)**: 跟 8/24 gh-ost 任务管理列表页同样的 Element UI 风格 + 权限细分模式
5. **离线可访问 (Offline-Friendly)**: 文档可下载到本地, 业务 RD 出差/在家能查 (不依赖平台在线)

### 2.3 核心约束的产品解读

| 约束 | 产品解读 | 反例 (为什么不做) |
|------|---------|------------------|
| 1. 只 DBA 上传 | 文档所有权 100% DBA 团队, 业务 RD 不上传不删除不编辑, 避免"多个人改同一个文件" 冲突 | ❌ "全员都能上传" → 文档质量失控, 业务 RD 传错版本 |
| 2. 完全不绑定 | 文档跟库/表/SQL 工单无外键, 业务 RD 查文档不需要先打开某个工单 | ❌ "跟工单绑定" → DBA 上传 1 个文档需要选 5 个工单关联, 实际没人这么干 |
| 3. 5 种类型 | 覆盖 DBA 日常维护场景 (MD 写规范, PDF 存扫描件, Word 存外审报告, Excel 存巡检报表, HTML 存富文本) | ❌ "只支持 MD" → DBA 想存 PDF 扫描件得用网盘, 体验割裂 |

---

## 03 用户场景 & 业务流

### 3.1 角色定义

| 角色 | 定义 | 权限 |
|------|------|------|
| **DBA** (上传者) | 实际维护规范的人, 通常 1-3 人, 是 is_superuser 或在 DBA 组 | 增 / 删 / 改 / 查 / 下载 |
| **业务 RD** (浏览者) | 平台所有其他用户, 业务开发、测试、产品等 | 查 / 下载 (不能增删改) |

### 3.2 场景 1: DBA 上传新规范 (核心流)

```
┌──────────┐                                  ┌──────────┐
│  DBA     │                                  │ 平台     │
│  马克群  │                                  │          │
└────┬─────┘                                  └────┬─────┘
     │                                              │
     │  1. 登录 Archery, 点击菜单 "文档库"           │
     │─────────────────────────────────────────────>│
     │                                              │
     │  2. 点击 "上传新文档" 按钮                    │
     │─────────────────────────────────────────────>│
     │                                              │
     │  3. 选择本地文件 (MD/PDF/Word/Excel/HTML)     │
     │  4. 填写标题 (必填, 50 字内)                 │
     │  5. 填写分类 (下拉: 设计规范/运维手册/SOP/其他) │
     │  6. 填写描述 (选填, 500 字内)                │
     │  7. 点击 "提交"                              │
     │─────────────────────────────────────────────>│
     │                                              │
     │                                     ┌────────┴────────┐
     │                                     │ 8. 验证:        │
     │                                     │  - 大小 ≤ 50MB  │
     │                                     │  - 扩展名合法   │
     │                                     │  - MIME 合法    │
     │                                     │  - 病毒扫描 (clamd, 未来) │
     │                                     └────────┬────────┘
     │                                              │
     │                                     ┌────────┴────────┐
     │                                     │ 9. 存储:        │
     │                                     │  - 写文件到 /opt/archery/shared/uploads/documents/<uuid>.<ext> │
     │                                     │  - 写 Document 表记录 │
     │                                     │  - 写 audit_log │
     │                                     └────────┬────────┘
     │                                              │
     │  10. 跳转到文档详情页, 显示 "上传成功" 提示    │
     │<─────────────────────────────────────────────│
     │                                              │
```

### 3.3 场景 2: 业务 RD 查询规范

```
┌──────────┐                                  ┌──────────┐
│ 业务 RD   │                                  │ 平台     │
│ 陈陈      │                                  │          │
└────┬─────┘                                  └────┬─────┘
     │                                              │
     │  1. 登录 Archery, 点击菜单 "文档库"           │
     │─────────────────────────────────────────────>│
     │                                              │
     │  2. 看到文档列表 (分页, 20 条/页)             │
     │  3. 用搜索框过滤 (标题 + 描述 + 分类)          │
     │  4. 用分类下拉过滤 (设计规范/运维手册/SOP/其他) │
     │─────────────────────────────────────────────>│
     │                                              │
     │  5. 点击某个文档, 进入详情页                   │
     │─────────────────────────────────────────────>│
     │                                              │
     │                                     ┌────────┴────────┐
     │                                     │ 6. 根据文件类型渲染: │
     │                                     │  - MD → marked.js 转 HTML │
     │                                     │  - HTML → iframe sandbox │
     │                                     │  - PDF → pdf.js 渲染     │
     │                                     │  - Word → mammoth.js 转 HTML │
     │                                     │  - Excel → sheetjs 渲染表格 │
     │                                     └────────┬────────┘
     │                                              │
     │  7. 业务 RD 看到渲染后的文档                   │
     │<─────────────────────────────────────────────│
     │                                              │
     │  8. 点击 "下载" 按钮, 浏览器下载原始文件       │
     │─────────────────────────────────────────────>│
     │                                              │
     │                                     ┌────────┴────────┐
     │                                     │ 9. 检查 download perm │
     │                                     │ 10. 写 audit_log  │
     │                                     │ 11. 返文件流     │
     │                                     └────────┬────────┘
     │                                              │
```

### 3.4 场景 3: DBA 替换/删除文档

```
DBA 看到旧文档, 上传新版本 → 旧文档 软删除 (Document.is_deleted=True) → 新文档生效
或者: DBA 直接点 "删除" → 物理删除文件 + 软删除记录 (保留 audit_log 30 天)
```

---

## 04 功能范围 & Phase 划分

### 4.1 Phase 1 (MVP, 2 周, 排 v0.5.0 第一个 release)

| 功能 | 端点 | 权限要求 | 工作量 |
|------|------|---------|--------|
| 文档列表页 (分页 + 搜索 + 分类过滤) | `GET /custom_docs/` | `sql.menu_document` | 1 天 |
| 文档上传 (DBA) | `POST /custom_docs/upload/` | `sql.upload_document` | 2 天 |
| 文档详情页 (5 种类型预览) | `GET /custom_docs/<id>/` | `sql.menu_document` | 3 天 |
| 文档下载 (DBA + RD) | `GET /custom_docs/<id>/download/` | `sql.menu_document` | 1 天 |
| 文档编辑 (DBA) | `GET/POST /custom_docs/<id>/edit/` | `sql.change_document` | 1 天 |
| 文档删除 (DBA 软删除) | `POST /custom_docs/<id>/delete/` | `sql.delete_document` | 1 天 |
| Admin 后台管理 (DBA) | `/admin/custom_docs/document/` | `is_staff` | 0.5 天 |
| 写 audit_log (DBA 操作审计) | middleware | 自动 | 0.5 天 |
| 跟 8/24 `/dbaprinciples/` 兼容 | `/dbaprinciples/` 跳到 `/custom_docs/` | 无 | 0.5 天 |
| 端到端测试 (5 种文件类型各 3 Case) | pytest | 无 | 1 天 |

**Phase 1 总工作量: 12 天 (1.5 周单人, 2 周留 buffer)**

### 4.2 Phase 2 (增强, 1 周, 排 v0.5.1)

| 功能 | 工作量 |
|------|--------|
| 文档版本管理 (DBA 上传新版本, 历史版本可查) | 2 天 |
| 文档批量上传 (DBA 一次性拖 10 个文件) | 1 天 |
| 文档收藏 (业务 RD 收藏常用文档, 个人中心显示) | 1 天 |
| 文档评论 (DBA 在文档详情页加 "FAQ" 区块) | 2 天 |

### 4.3 不做 (out of scope)

- ❌ Office 完整编辑 (只能预览不能编辑, 避免 LibreOffice 集成复杂度)
- ❌ 在线 Markdown WYSIWYG 编辑器 (DBA 本地写好再上传, 避免前端编辑器坑)
- ❌ 全文搜索 (用标题/描述/分类模糊匹配够用, ES 集成过重)
- ❌ 跟 SQL 工单绑定 (用户拍板不绑定, 保持简单)
- ❌ 审批流 (DBA 自己审自己, 不需要业务审批)
- ❌ 文档加密/水印 (DBA 内部使用, 不需要 DRM)
- ❌ 文档分享外链 (Archery 用户才能访问, 不暴露到外网)
- ❌ 移动端 APP (Archery 平台无移动端, 浏览器响应式够用)

---

## 05 数据模型

### 5.1 Document 表

```python
# sql/extensions/custom_docs/models.py
from django.db import models
from django.contrib.auth.models import Group
from sql.models import Users as User  # Archery 实际用 Users 不是 auth.User

class DocumentCategory(models.TextChoices):
    DESIGN_SPEC = "design_spec", "设计规范"
    OPS_MANUAL = "ops_manual", "运维手册"
    SOP = "sop", "SOP"
    OTHER = "other", "其他"

class DocumentFileType(models.TextChoices):
    MARKDOWN = "md", "Markdown"
    HTML = "html", "HTML"
    PDF = "pdf", "PDF"
    WORD = "docx", "Word"
    EXCEL = "xlsx", "Excel"

class Document(models.Model):
    """自定义文档库 · 单文件元数据"""

    # 业务字段
    title = models.CharField(max_length=50, help_text="文档标题, 50 字内")
    description = models.TextField(blank=True, max_length=500, help_text="文档描述, 500 字内")
    category = models.CharField(max_length=20, choices=DocumentCategory.choices, default=DocumentCategory.OTHER)
    file = models.FileField(upload_to="documents/%Y/%m/", help_text="文件存储路径")
    file_type = models.CharField(max_length=10, choices=DocumentFileType.choices)
    file_size = models.BigIntegerField(help_text="文件大小, 字节")
    file_hash = models.CharField(max_length=64, help_text="SHA256, 用于去重 + 完整性校验")

    # 元数据
    uploaded_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="uploaded_documents")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="updated_documents", null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    # 软删除
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="deleted_documents")
    deleted_at = models.DateTimeField(null=True, blank=True)

    # 统计
    view_count = models.BigIntegerField(default=0, help_text="浏览次数")
    download_count = models.BigIntegerField(default=0, help_text="下载次数")

    class Meta:
        db_table = "custom_doc_document"
        ordering = ["-uploaded_at"]
        indexes = [
            models.Index(fields=["category", "is_deleted", "-uploaded_at"]),
            models.Index(fields=["title"]),
            models.Index(fields=["file_hash"]),  # 去重
        ]
        permissions = [
            ("upload_document", "Can upload document (DBA only)"),
            ("change_document", "Can change document (DBA only)"),
            ("delete_document", "Can delete document (DBA only)"),
            ("view_document_audit", "Can view document audit log (DBA only)"),
        ]
        verbose_name = "文档"
        verbose_name_plural = "文档库"

    def __str__(self):
        return f"[{self.get_category_display()}] {self.title}"

    @property
    def extension(self):
        return self.file.name.rsplit(".", 1)[-1].lower() if "." in self.file.name else ""
```

### 5.2 DocumentAuditLog 表 (审计日志)

```python
class DocumentAuditLog(models.Model):
    """文档操作审计日志 - 30 天保留, 用于合规 + 事故排查"""

    document = models.ForeignKey(Document, on_delete=models.SET_NULL, null=True, blank=True)
    document_title_snapshot = models.CharField(max_length=50, help_text="操作时的 title, 文档删了也能查")
    action = models.CharField(max_length=20, choices=[
        ("upload", "上传"),
        ("view", "浏览"),
        ("download", "下载"),
        ("edit", "编辑"),
        ("delete", "删除"),
    ])
    operator = models.ForeignKey(User, on_delete=models.PROTECT, related_name="document_audit_logs")
    operator_display = models.CharField(max_length=50, help_text="操作时 display, 即使用户改了名也能查")
    operator_ip = models.GenericIPAddressField(null=True, blank=True)
    operator_ua = models.CharField(max_length=200, blank=True)
    extra = models.JSONField(default=dict, blank=True, help_text="操作详情, 如 old_size/new_size")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "custom_doc_audit_log"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["document", "-created_at"]),
            models.Index(fields=["operator", "-created_at"]),
        ]
```

### 5.3 索引设计 (性能关键)

| 查询 | 索引 |
|------|------|
| 列表页: 按 category 过滤 + 按时间倒序 | `(category, is_deleted, -uploaded_at)` 复合索引 |
| 搜索: 标题模糊匹配 | `title` 索引 (LIKE 'xxx%' 能用) |
| 去重: 同 hash 查找 | `file_hash` 索引 |
| 审计: 按用户查 | `(operator, -created_at)` 索引 |
| 软删除: 排除已删除 | `is_deleted` 索引 (boolean 单独索引效果一般, 跟其他字段组合) |

### 5.4 数据库迁移

```bash
docker-compose exec archery python manage.py makemigrations custom_docs
docker-compose exec archery python manage.py migrate

# 134 dev 演练 (验证 schema 正确)
cd /opt/archery/prod
source venv/bin/activate
python manage.py makemigrations custom_docs
python manage.py migrate --database default

# 110 prod 推的时候
python manage.py migrate --database default
```

---

## 06 权限模型

### 06.1 权限细分 (跟 8/24 gh-ost 任务管理同样模式)

```python
# sql/extensions/custom_docs/permissions.py
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from sql.models import Users as User

def get_doc_perms():
    """返回 5 个 perm 对象, 用于 init_perms 脚本 + admin 注册"""
    ct = ContentType.objects.get_for_model(Document)
    return [
        Permission(codename="view_document", name="Can view document", content_type=ct),
        Permission(codename="upload_document", name="Can upload document", content_type=ct),
        Permission(codename="change_document", name="Can change document", content_type=ct),
        Permission(codename="delete_document", name="Can delete document", content_type=ct),
        Permission(codename="view_document_audit", name="Can view document audit log", content_type=ct),
    ]
```

### 06.2 权限分配 (134 dev / 110 prod)

| 角色 | 拥有的 perm | 行为 |
|------|------------|------|
| 业务 RD (默认) | `view_document` | 列表 / 详情 / 下载 |
| DBA (在 DBA 组) | `view_document` + `upload_document` + `change_document` + `delete_document` + `view_document_audit` | 全部 |
| 业务 RD leader (在 RD 组长组) | `view_document` | 只读 |
| Admin (is_superuser) | 全部 | 全部 + admin 后台 |

### 06.3 端点 perm 守卫 (跟 8/24 gh-ost 操作端点同样模式)

```python
# sql/extensions/custom_docs/views.py
from django.http import JsonResponse
from functools import wraps

def _require_doc_perm(action):
    """DBA 上传/编辑/删除端点 perm 守卫, 不能 raise PermissionDenied (会返整页 HTML)"""
    perm_map = {
        "upload": "custom_docs.upload_document",
        "change": "custom_docs.change_document",
        "delete": "custom_docs.delete_document",
        "audit": "custom_docs.view_document_audit",
    }
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.has_perm(perm_map[action]):
                return JsonResponse(
                    {"ok": False, "error": f"无 {action} 权限, 请联系 DBA"},
                    status=403
                )
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator

@_require_doc_perm("upload")
def upload_document(request):
    ...

@_require_doc_perm("change")
def edit_document(request, doc_id):
    ...

@_require_doc_perm("delete")
def delete_document(request, doc_id):
    ...
```

**关键**: 跟 8/24 gh-ost 一样, **不能 raise PermissionDenied** (Django middleware 会返 403 HTML 页面, AJAX 拿到整页源码, alert 弹源码), 必须返 `JsonResponse({"ok": False, "error": "..."}, status=403)`。

### 06.4 8/24 教训复用

- `JsonResponse + status=403` 模式 (8/24 gh-ost 任务管理 perm 守卫)
- `request.user.display or request.user.username` 显示中文名 (8/24 cancel 视图)
- `request.user.groups ∩ audit_group_ids` 拿用户实际所在审批节点 (8/24 ghost task operator)

---

## 07 后端架构

### 07.1 Django app 结构

```
sql/extensions/custom_docs/
├── __init__.py
├── apps.py                          # AppConfig
├── models.py                        # Document + DocumentAuditLog
├── admin.py                         # Django admin 注册
├── permissions.py                   # 5 个 perm 定义
├── views.py                         # 6 个端点
├── urls.py                          # URLconf
├── services/
│   ├── __init__.py
│   ├── file_upload.py              # 文件上传验证 + 存储
│   ├── file_preview.py             # 5 种类型预览渲染
│   ├── file_search.py              # 标题/描述/分类搜索
│   └── audit.py                    # 审计日志写入
├── migrations/
│   └── 0001_initial.py             # 2 张表
├── templates/
│   └── custom_docs/
│       ├── list.html                # 列表页
│       ├── detail.html             # 详情页 (5 种类型)
│       ├── upload.html             # 上传页
│       └── edit.html               # 编辑页
├── static/
│   └── custom_docs/
│       ├── js/
│       │   ├── list.js
│       │   ├── detail.js           # 5 种类型预览 JS
│       │   ├── upload.js
│       │   └── edit.js
│       └── css/
│           └── preview.css
└── tests/
    ├── __init__.py
    ├── test_models.py
    ├── test_views.py
    ├── test_file_upload.py
    ├── test_file_preview.py
    └── test_e2e.py                # 端到端 5 类型各 3 Case
```

### 07.2 URLconf

```python
# sql/extensions/custom_docs/urls.py
from django.urls import path
from . import views

app_name = "custom_docs"

urlpatterns = [
    path("", views.document_list, name="list"),
    path("upload/", views.upload_document, name="upload"),
    path("<int:doc_id>/", views.document_detail, name="detail"),
    path("<int:doc_id>/download/", views.download_document, name="download"),
    path("<int:doc_id>/edit/", views.edit_document, name="edit"),
    path("<int:doc_id>/delete/", views.delete_document, name="delete"),
    path("audit/", views.audit_log, name="audit"),
]
```

挂载到 Archery 主 urls:

```python
# archery/urls.py
urlpatterns = [
    ...
    path("custom_docs/", include(("sql.extensions.custom_docs.urls", "custom_docs"), namespace="custom_docs")),
    ...
]
```

### 07.3 端点设计

| 端点 | 方法 | 权限 | 行为 |
|------|------|------|------|
| `GET /custom_docs/` | GET | `view_document` | 列表页, 支持 `?q=关键词&category=design_spec&page=1` |
| `POST /custom_docs/upload/` | POST | `upload_document` | 上传 (multipart/form-data) |
| `GET /custom_docs/<id>/` | GET | `view_document` | 详情页, 5 种类型渲染 |
| `GET /custom_docs/<id>/download/` | GET | `view_document` | 下载原始文件 |
| `GET /custom_docs/<id>/edit/` | GET | `change_document` | 编辑页 (改 title/description/category, 不改文件) |
| `POST /custom_docs/<id>/edit/` | POST | `change_document` | 提交编辑 |
| `POST /custom_docs/<id>/delete/` | POST | `delete_document` | 软删除 |
| `GET /custom_docs/audit/` | GET | `view_document_audit` | 审计日志页 (DBA) |

### 07.4 业务流: 上传

```python
# sql/extensions/custom_docs/services/file_upload.py
import os
import uuid
import hashlib
from django.conf import settings
from django.core.exceptions import ValidationError
from ..models import Document, DocumentFileType, DocumentCategory

ALLOWED_EXTENSIONS = {"md", "markdown", "html", "htm", "pdf", "docx", "xlsx"}
ALLOWED_MIMES = {
    "md": ["text/markdown", "text/plain"],
    "markdown": ["text/markdown", "text/plain"],
    "html": ["text/html"],
    "htm": ["text/html"],
    "pdf": ["application/pdf"],
    "docx": ["application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
    "xlsx": ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
}
MAX_SIZE = 50 * 1024 * 1024  # 50MB

def validate_upload(file, title):
    """返回 (is_valid, error_msg, file_type)"""
    if not file:
        return False, "未选择文件", None

    if file.size > MAX_SIZE:
        return False, f"文件超过 50MB (当前 {file.size/1024/1024:.1f}MB)", None

    ext = file.name.rsplit(".", 1)[-1].lower() if "." in file.name else ""
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"不支持的文件类型: .{ext} (允许: MD/HTML/PDF/Word/Excel)", None

    if file.content_type not in ALLOWED_MIMES.get(ext, []):
        return False, f"文件 MIME ({file.content_type}) 跟扩展名 .{ext} 不匹配, 拒绝上传", None

    if not title or len(title) > 50:
        return False, "标题必填且 ≤ 50 字", None

    return True, None, _ext_to_filetype(ext)

def _ext_to_filetype(ext):
    return {
        "md": DocumentFileType.MARKDOWN,
        "markdown": DocumentFileType.MARKDOWN,
        "html": DocumentFileType.HTML,
        "htm": DocumentFileType.HTML,
        "pdf": DocumentFileType.PDF,
        "docx": DocumentFileType.WORD,
        "xlsx": DocumentFileType.EXCEL,
    }[ext]

def save_upload(file, title, description, category, user):
    """保存上传文件, 返回 Document 对象"""
    # 1. 计算 hash
    file_hash = hashlib.sha256()
    for chunk in file.chunks():
        file_hash.update(chunk)
    file_hash_hex = file_hash.hexdigest()

    # 2. 检查去重 (同 hash + 同 title 才算重复, 避免误判)
    existing = Document.objects.filter(
        file_hash=file_hash_hex, is_deleted=False
    ).first()
    if existing:
        raise ValidationError(f"文件已存在 (同 hash, 标题: {existing.title}), 请检查是否重复上传")

    # 3. 重命名 (uuid + 原扩展名, 避免路径冲突 + 路径注入)
    ext = file.name.rsplit(".", 1)[-1].lower()
    new_name = f"{uuid.uuid4().hex}.{ext}"

    # 4. 保存
    doc = Document(
        title=title,
        description=description,
        category=category,
        file=file,  # FileField 会自动用 upload_to + new_name
        file_type=_ext_to_filetype(ext),
        file_size=file.size,
        file_hash=file_hash_hex,
        uploaded_by=user,
    )
    # 重命名 file.name 让 FileField 用我们的名字
    doc.file.name = f"documents/{new_name}"
    doc.save()
    return doc
```

### 07.5 业务流: 5 种类型预览

```python
# sql/extensions/custom_docs/services/file_preview.py
import os
import re
from django.conf import settings
from ..models import Document, DocumentFileType

def render_preview(doc):
    """根据 file_type 渲染预览, 返回 HTML 字符串"""
    file_path = doc.file.path
    if not os.path.exists(file_path):
        return '<div class="alert alert-warning">文件已丢失, 请联系 DBA</div>'

    if doc.file_type == DocumentFileType.MARKDOWN:
        return _render_markdown(file_path)
    elif doc.file_type == DocumentFileType.HTML:
        return _render_html(file_path)
    elif doc.file_type == DocumentFileType.PDF:
        return _render_pdf(file_path)
    elif doc.file_type == DocumentFileType.WORD:
        return _render_word(file_path)
    elif doc.file_type == DocumentFileType.EXCEL:
        return _render_excel(file_path)

def _render_markdown(path):
    with open(path, "r", encoding="utf-8") as f:
        md = f.read()
    # 用前端 marked.js 渲染, 后端只返 raw markdown
    return f'<pre id="md-source" style="display:none">{md}</pre><div id="md-rendered"></div>'

def _render_html(path):
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    # iframe sandbox, 防止 XSS
    # base64 编码避免路径问题
    import base64
    b64 = base64.b64encode(html.encode("utf-8")).decode("ascii")
    return f'<iframe sandbox srcdoc="..." style="width:100%;height:80vh;border:0"></iframe>'

def _render_pdf(path):
    # pdf.js 渲染, 后端只返文件 URL
    rel_url = doc.file.url  # /media/documents/xxx.pdf
    return f'<canvas id="pdf-canvas"></canvas><script src="...pdf.js"></script>'

def _render_word(path):
    # mammoth.js 客户端转 HTML
    rel_url = doc.file.url
    return f'<div id="word-content" data-url="{rel_url}"></div>'

def _render_excel(path):
    # sheetjs 客户端渲染
    rel_url = doc.file.url
    return f'<div id="excel-content" data-url="{rel_url}"></div>'
```

**5 种类型前端渲染 (Phase 1 方案)**:
- MD: 前端 `marked.js` + `DOMPurify` (XSS 净化)
- HTML: `<iframe sandbox srcdoc="...">` (完全隔离)
- PDF: 前端 `pdf.js` (Mozilla, 成熟)
- Word: 前端 `mammoth.js` (.docx → HTML)
- Excel: 前端 `sheetjs` (.xlsx → HTML 表格)

### 07.6 业务流: 下载

```python
# sql/extensions/custom_docs/views.py
from django.http import FileResponse, Http404, JsonResponse
import mimetypes
import os

@require_http_methods(["GET"])
def download_document(request, doc_id):
    doc = get_object_or_404(Document, id=doc_id, is_deleted=False)
    if not request.user.has_perm("custom_docs.view_document"):
        return JsonResponse({"ok": False, "error": "无查看权限"}, status=403)

    if not os.path.exists(doc.file.path):
        raise Http404("文件已丢失")

    # 写审计
    DocumentAuditLog.objects.create(
        document=doc,
        document_title_snapshot=doc.title,
        action="download",
        operator=request.user,
        operator_display=request.user.display or request.user.username,
        operator_ip=request.META.get("REMOTE_ADDR"),
        operator_ua=request.META.get("HTTP_USER_AGENT", "")[:200],
    )

    # 更新统计
    Document.objects.filter(id=doc.id).update(download_count=F("download_count") + 1)

    # 返文件流 (用原文件名, 不用 uuid)
    return FileResponse(
        open(doc.file.path, "rb"),
        as_attachment=True,
        filename=doc.title + "." + doc.extension,  # 业务用户下载看到的名字
        content_type=mimetypes.guess_type(doc.file.path)[0] or "application/octet-stream",
    )
```

---

## 08 前端架构

### 08.1 页面结构 (Vue 2 + Element UI, 跟 Archery 现有风格一致)

```
/custom_docs/                            # 列表页
├── 顶部: 标题 "文档库" + 搜索框 + 分类下拉 + "上传" 按钮 (DBA 可见)
├── 主体: 文档表格 (Element UI el-table)
│   ├── 标题 (列, 链接到详情)
│   ├── 分类 (列, 标签)
│   ├── 大小 (列, 人类可读)
│   ├── 上传者 (列, 中文名)
│   ├── 上传时间 (列, 相对时间)
│   ├── 浏览/下载次数 (列)
│   └── 操作 (列: 详情/下载/编辑/删除, 根据 perm 显隐)
└── 底部: 分页 (el-pagination)

/custom_docs/<id>/                       # 详情页
├── 顶部: 标题 + 分类标签 + 上传者 + 时间 + "下载/编辑/删除" 按钮
├── 主体: 5 种类型渲染
│   ├── MD: marked.js 渲染区域
│   ├── HTML: iframe sandbox
│   ├── PDF: pdf.js canvas
│   ├── Word: mammoth.js 渲染区域
│   └── Excel: sheetjs 渲染区域
└── 底部: 描述 (折叠)

/custom_docs/upload/                     # 上传页 (DBA 专属)
└── 单一表单 (el-form)
    ├── 标题 (el-input, 50 字)
    ├── 分类 (el-select, 4 个选项)
    ├── 描述 (el-input type=textarea, 500 字)
    ├── 文件 (el-upload drag, 5 种类型)
    └── 提交 (el-button, type=primary)

/custom_docs/<id>/edit/                  # 编辑页 (DBA 专属)
└── 单一表单 (只改 title/description/category, 不改文件 - 想改文件重新上传)

/custom_docs/audit/                      # 审计日志页 (DBA 专属)
└── 表格: 时间 / 操作 / 操作者 / 文档 / IP / 详情
```

### 08.2 关键前端组件

| 组件 | 库 | 用途 |
|------|----|----|
| 列表表格 | Element UI `el-table` | 跟 8/24 gh-ost 任务管理列表页同样 |
| 上传组件 | Element UI `el-upload` (drag 模式) | 拖拽上传 + 进度条 |
| MD 渲染 | `marked.js` 4.3 + `DOMPurify` 3.0 | MD → 净化 HTML |
| HTML 隔离 | 原生 `<iframe sandbox>` | 完全隔离 XSS |
| PDF 渲染 | `pdf.js` 4.0 (Mozilla) | canvas 渲染 PDF 页面 |
| Word 渲染 | `mammoth.js` 1.6 | .docx → HTML |
| Excel 渲染 | `sheetjs` (xlsx) 0.20 | .xlsx → HTML 表格 |

### 08.3 依赖管理 (前端)

```bash
# 134 dev / 110 prod / 文档库前端
cd /opt/archery/prod
npm install marked@4.3.0 dompurify@3.0.6 pdfjs-dist@4.0.379 mammoth@1.6.0 xlsx@0.20.0
# 产物: node_modules/ + static/dist/
# 部署时 collectstatic 收进 /opt/archery/shared/static/dist/
```

或用 CDN (开发模式):
```html
<script src="https://cdn.jsdelivr.net/npm/marked@4.3.0/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/dompurify@3.0.6/dist/purify.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/pdfjs-dist@4.0.379/build/pdf.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/mammoth@1.6.0/mammoth.browser.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/xlsx@0.20.0/dist/xlsx.full.min.js"></script>
```

### 08.4 跟 8/24 演示稿的关系

8/24 演示稿 11 章节里有"业务侧最痛"问题:
- "我想看 `hly_accesscard` 表的设计规范, 但不知道问谁"
- "DBA 给我发的设计规范链接在内部 Wiki, 我登录另一个系统才能看"

**v0.5.0 文档库直接解决这两个问题**——演示稿里可以加一节"未来 Roadmap", 给业务用户预期。

---

## 09 文件存储 & 安全

### 09.1 文件存储路径

```
/opt/archery/shared/uploads/documents/
├── 2026/
│   ├── 08/
│   │   ├── 8e3b5c1d9a2f4e6b8c0d1e2f3a4b5c6d.pdf
│   │   ├── 9f4d6c2e0b1a3d5c7b8e9f0a1b2c3d4e.md
│   │   └── ...
│   └── 09/
│       └── ...
```

**关键设计**:
- 路径用 `uuid4().hex + 原扩展名`, **避免文件名冲突** + **避免路径注入** (扩展名白名单)
- 不用原文件名 (用户可能用中文/特殊字符, Linux 路径兼容性差, 也泄露信息)
- 下载时用 `title + 原扩展名` 作 download filename, 业务用户体验好

### 09.2 文件大小限制

| 类型 | 上限 | 理由 |
|------|------|------|
| 单文件 | 50 MB | 防止大文件拖慢 gunicorn worker, 业务场景 50MB PDF/Excel 够用 |
| 单用户当日上传 | 200 MB | 防止恶意 DBA (虽然我们是 single-DBA, 留个保险) |
| 总量 | 10 GB | 134 dev 现有 200GB 硬盘, 留 buffer; 110 prod 单独评估 |

### 09.3 MIME 校验 (白名单)

```python
ALLOWED_MIMES = {
    "md": ["text/markdown", "text/plain", "text/x-markdown"],
    "html": ["text/html", "application/xhtml+xml"],
    "pdf": ["application/pdf"],
    "docx": ["application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
    "xlsx": ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
}
```

**严格检查**: 扩展名 + MIME 必须都匹配, 否则拒绝 (8/24 教训: 防止上传 `.php.jpg` 之类伪装的文件)。

### 09.4 XSS 防护

- **MD**: 前端 `DOMPurify` 净化 (避免 `<script>` 注入)
- **HTML**: `<iframe sandbox srcdoc="...">` (完全隔离, HTML 内 JS 不能访问父页面)
- **PDF**: pdf.js 渲染 (Mozilla 维护, 安全)
- **Word**: mammoth.js 转 HTML + DOMPurify 净化
- **Excel**: sheetjs 转 HTML 表格, 不会执行 JS

### 09.5 路径注入防护

- 文件名用 `uuid4().hex` 生成, 不取用户输入
- 扩展名走白名单 (5 种)
- 路径拼接用 `os.path.join`, 不字符串拼接
- FileField 的 `upload_to="documents/%Y/%m/"` 限制根目录

### 09.6 病毒扫描 (Phase 2)

```python
# Phase 2: 集成 clamd
import clamd

def scan_for_virus(file_path):
    cd = clamd.ClamdNetworkSocket(host="127.0.0.1", port=3310)
    result = cd.scan(file_path)
    if result and result[file_path][0] == "FOUND":
        raise ValidationError("文件含病毒, 拒绝上传")
    return True
```

134 dev / 110 prod 部署 `clamd`:
```bash
yum install clamav-server clamav-data clamav-update clamav-filesystem clamav clamav-scanner-systemd clamav-devel clamav-lib clamav-server-systemd
systemctl enable clamd@scan
freshclam
```

**Phase 1 先不集成**, 推迟到 Phase 2 (内网环境 + 5 种已知类型 + 50MB 限制, 风险可控)。

### 09.7 权限安全 (跟 8/24 教训)

```python
# 文件路径权限 - 7 层防护
chown -R archery:archery /opt/archery/shared/uploads/
chmod 750 /opt/archery/shared/uploads/
# 业务用户走 Django view 拿文件, 不直接访问文件系统
# 防止:
# 1. 业务用户绕过 perm 直接 wget 文件
# 2. 业务用户读未授权文档
# 3. 误删文件 (只有 root + archery 能写)
```

---

## 10 推 110 / Roadmap / 风险

### 10.1 推 110 时序 (W3 9/1-7)

```
Day 1-2: 134 dev 部署 + 演练 (5 种文件类型各 3 Case)
Day 3-4: 8/24 6 commit + dbaprinciples 修复 + reload SOP 一起打包
Day 5: 推 110 prod (5 步必做脚本 + 本设计稿的 init_perms + 业务用户验证)
Day 6-7: 110 prod 演练 + 业务用户培训 + 收尾
```

### 10.2 推 110 必做清单 (新增)

```bash
# scripts/deploy/5step_prerequisites_110prod.sh 新增步骤
# 步骤 14: 创建文档库目录
mkdir -p /opt/archery/shared/uploads/documents/{2026,2027}/{01..12}
chown -R archery:archery /opt/archery/shared/uploads/
chmod 750 /opt/archery/shared/uploads/

# 步骤 15: 跑 migration (custom_docs 2 张表)
cd /opt/archery/prod
source venv/bin/activate
python manage.py migrate custom_docs

# 步骤 16: 注册 5 个 perm (init_perms.py)
python manage.py shell < scripts/init_doc_perms.py

# 步骤 17: 分配 perm (DBA 组拿全 5 个, 业务 RD 默认 view_document)
python manage.py shell < scripts/grant_doc_perms.py

# 步骤 18: 验证 (Django test client 模拟 5 种类型上传 + 下载)
pytest sql/extensions/custom_docs/tests/ -v
```

### 10.3 init_perms.py 脚本

```python
# scripts/init_doc_perms.py
from django.contrib.auth.models import Permission, Group
from django.contrib.contenttypes.models import ContentType
from sql.extensions.custom_docs.models import Document

def run():
    ct = ContentType.objects.get_for_model(Document)

    # 5 个 perm
    perms_def = [
        ("view_document", "Can view document"),
        ("upload_document", "Can upload document (DBA only)"),
        ("change_document", "Can change document (DBA only)"),
        ("delete_document", "Can delete document (DBA only)"),
        ("view_document_audit", "Can view document audit log (DBA only)"),
    ]
    for codename, name in perms_def:
        Permission.objects.get_or_create(
            codename=codename, content_type=ct, defaults={"name": name}
        )
    print(f"OK: 5 个 perm 已注册/已存在")

    # DBA 组拿全 5 个
    try:
        dba_group = Group.objects.get(name="DBA")
        dba_perms = Permission.objects.filter(content_type=ct)
        dba_group.permissions.add(*dba_perms)
        print(f"OK: DBA 组 ({dba_group.name}) 已分配 {dba_perms.count()} 个 perm")
    except Group.DoesNotExist:
        print("WARN: DBA 组不存在, 跳过 perm 分配")

    # 业务 RD 默认有 view_document (跟 8/24 gh-ost 任务管理 perm 一样, Django admin 注册时自动给 view_document)
    print("OK: 业务 RD 默认有 view_document (Django admin 自动注册)")

run()
```

### 10.4 Roadmap

| 版本 | 功能 | 工作量 | 状态 |
|------|------|--------|------|
| v0.5.0-alpha | Phase 1 全部 (6 个端点 + 5 种预览 + 权限细分) | 2 周 | 设计稿 (本文) |
| v0.5.0-beta | 134 dev 演练 + 5 类型各 3 Case 端到端 | 1 周 | 待开干 |
| v0.5.0 | 推 110 + 业务用户培训 | 1 周 | 待排期 |
| v0.5.1 | Phase 2 (版本管理 + 批量上传 + 收藏 + 评论) | 1 周 | 设计稿已写 |
| v0.6.0 | (预留) 全文搜索 (ES 集成) | 2 周 | 待评估 |
| v0.6.1 | (预留) 跟 SQL 工单绑定 (业务 RD 投票驱动) | 2 周 | 待评估 |

### 10.5 风险评估

| 风险 | 等级 | 缓解 |
|------|------|------|
| 134 dev gunicorn 加载性能 (PDF 渲染吃 CPU) | 中 | 50MB 限制 + PDF.js 客户端渲染, 不消耗 gunicorn |
| 业务用户上传超大文件拖慢 gunicorn | 中 | 50MB 限制 + multipart 解析在 nginx (反向代理) 层做, 不消耗 gunicorn |
| 134 dev 200GB 硬盘满 | 低 | 10GB 总量限制 + 软删除 30 天后物理删除 |
| 业务用户下载文档外传 (合规问题) | 低 | 写 audit_log 记录所有下载, 30 天可查 |
| HTML 文件含 XSS 攻击 | 高 | iframe sandbox + DOMPurify 双层防护 |
| Office 文件含宏 (Excel .xlsm) | 中 | 不支持 .xlsm (只支持 .xlsx), 防止宏执行 |
| MD 文件含 `<script>` 注入 | 高 | DOMPurify 净化 |
| 134 dev / 110 prod 用户混淆 (DBA 在 110 上传, 134 看不到) | 低 | 文档库数据存在 platform 库, 跟 110/134 无关, 实际不存在这问题 |
| DBA 误删文档 (不可恢复) | 低 | 软删除 + 30 天保留期 + audit_log 记录 |
| 8/24 教训: docstring SyntaxError 重演 | 高 | 改 Python 代码后必须本地 `py_compile` 验证, 推 110 前必须 Django test client 5 类型全验 |

### 10.6 跟 8/24 已做工作的关联

| 8/24 已做 | 关系 |
|----------|------|
| 8/24 修 `/dbaprinciples/` 500 错 | 解决了"读规范" 问题, 本设计稿升级为"读+写+管" |
| 8/24 gh-ost 任务管理列表页 (v0.3.0-beta) | 权限细分模式直接复用 |
| 8/24 DDL 智能回滚 (v0.4.5) | 扩展 Django app 模式直接复用 |
| 8/24 6 commit bug fix + reload SOP | 同样踩过 docstring SyntaxError 坑, 推 110 时必走 SOP |
| 8/24 演示稿 11 章节 | 业务用户痛点引出来, 本设计稿直接解决 |

### 10.7 后续可考虑 (out of scope 但值得记)

- **SQL 工单附件** (跟 SQL 工单绑定, 用户拍板不做)
- **Confluence 集成** (如果公司买了 Confluence, 文档库就是个 wrapper)
- **AI 自动总结** (用 LLM 自动给文档生成 100 字摘要, 列表页显示)
- **协作编辑** (DBA 多人协同编辑同一文档, 需要 CRDT, 复杂度高)
- **审批流** (DBA 上传需要 leader 审批, 用户拍板不做)

---

## 附录 A: 跟 Archery 现有菜单集成

`archery/settings.py` 跟现有菜单 (例如 `sql.menu_document`) 合并:

```python
# sql/templatetags/custom_menu.py
from django import template
register = template.Library()

@register.simple_tag
def doc_library_menu(user):
    """根据 user perm 决定是否显示文档库菜单"""
    if user.has_perm("custom_docs.view_document"):
        return True
    return False
```

模板里:
```html
{% load custom_menu %}
{% if user|doc_library_menu %}
<li><a href="{% url 'custom_docs:list' %}">文档库</a></li>
{% endif %}
```

## 附录 B: 数据库 schema 完整 DDL (参考)

```sql
CREATE TABLE `custom_doc_document` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `title` varchar(50) NOT NULL,
  `description` longtext NOT NULL,
  `category` varchar(20) NOT NULL,
  `file` varchar(100) NOT NULL,
  `file_type` varchar(10) NOT NULL,
  `file_size` bigint NOT NULL,
  `file_hash` varchar(64) NOT NULL,
  `uploaded_by_id` int NOT NULL,
  `uploaded_at` datetime(6) NOT NULL,
  `updated_by_id` int DEFAULT NULL,
  `updated_at` datetime(6) NOT NULL,
  `is_deleted` tinyint(1) NOT NULL DEFAULT '0',
  `deleted_by_id` int DEFAULT NULL,
  `deleted_at` datetime(6) DEFAULT NULL,
  `view_count` bigint NOT NULL DEFAULT '0',
  `download_count` bigint NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  KEY `custom_doc_document_category_is_deleted_uploaded_at` (`category`,`is_deleted`,`uploaded_at` DESC),
  KEY `custom_doc_document_title` (`title`),
  KEY `custom_doc_document_file_hash` (`file_hash`),
  CONSTRAINT `fk_uploaded_by` FOREIGN KEY (`uploaded_by_id`) REFERENCES `sql_users` (`id`),
  CONSTRAINT `fk_updated_by` FOREIGN KEY (`updated_by_id`) REFERENCES `sql_users` (`id`),
  CONSTRAINT `fk_deleted_by` FOREIGN KEY (`deleted_by_id`) REFERENCES `sql_users` (`id`)
);

CREATE TABLE `custom_doc_audit_log` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `document_id` bigint DEFAULT NULL,
  `document_title_snapshot` varchar(50) NOT NULL,
  `action` varchar(20) NOT NULL,
  `operator_id` int NOT NULL,
  `operator_display` varchar(50) NOT NULL,
  `operator_ip` varchar(39) DEFAULT NULL,
  `operator_ua` varchar(200) NOT NULL DEFAULT '',
  `extra` longtext NOT NULL DEFAULT '{}',
  `created_at` datetime(6) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `custom_doc_audit_log_document_created_at` (`document_id`,`created_at` DESC),
  KEY `custom_doc_audit_log_operator_created_at` (`operator_id`,`created_at` DESC),
  CONSTRAINT `fk_audit_document` FOREIGN KEY (`document_id`) REFERENCES `custom_doc_document` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_audit_operator` FOREIGN KEY (`operator_id`) REFERENCES `sql_users` (`id`)
);
```

## 附录 C: 端到端测试 5 类型各 3 Case

```python
# sql/extensions/custom_docs/tests/test_e2e.py
import os
import pytest
from django.test import Client
from django.core.files.uploadedfile import SimpleUploadedFile
from sql.models import Users as User
from sql.extensions.custom_docs.models import Document

@pytest.fixture
def dba_user():
    return User.objects.get(username="admin")  # or mkq

@pytest.fixture
def rd_user():
    return User.objects.filter(is_superuser=False).first()

@pytest.mark.django_db
class TestE2E:
    def test_md_upload_download(self, dba_user):
        """MD: 上传 + 下载 + 渲染"""
        c = Client(HTTP_HOST="172.20.2.134")
        c.force_login(dba_user)
        content = b"# Test\n\nHello **world**"
        file = SimpleUploadedFile("test.md", content, content_type="text/markdown")
        r = c.post("/custom_docs/upload/", {"title": "MD测试", "category": "design_spec", "file": file})
        assert r.status_code == 200
        doc = Document.objects.get(title="MD测试")
        assert doc.file_type == "md"

        # 下载
        r = c.get(f"/custom_docs/{doc.id}/download/")
        assert r.status_code == 200
        assert r.content == content

    def test_html_upload_sandbox(self, dba_user):
        """HTML: 上传 + iframe sandbox 隔离"""
        ...

    def test_pdf_upload_render(self, dba_user):
        """PDF: 上传 + pdf.js 渲染"""
        ...

    def test_word_upload_mammoth(self, dba_user):
        """Word: 上传 + mammoth.js 转 HTML"""
        ...

    def test_excel_upload_sheetjs(self, dba_user):
        """Excel: 上传 + sheetjs 渲染"""
        ...

    def test_rd_cannot_upload(self, rd_user):
        """业务 RD 上传被拒 (perm 守卫)"""
        c = Client(HTTP_HOST="172.20.2.134")
        c.force_login(rd_user)
        file = SimpleUploadedFile("test.md", b"x", content_type="text/markdown")
        r = c.post("/custom_docs/upload/", {"title": "X", "category": "other", "file": file})
        assert r.status_code == 403
        assert "无 upload 权限" in r.json()["error"]

    def test_dba_can_delete_rd_cannot(self, dba_user, rd_user):
        """删除 perm 守卫"""
        ...

    def test_file_size_limit(self, dba_user):
        """51MB 文件被拒"""
        ...
```

## 附录 D: 跟 8/24 6 commit 修复的关联

8/24 一天修了 6 个 bug, 6 commit, 跟本设计稿关联:

| 8/24 commit | 跟文档库关系 |
|-------------|------------|
| `a41c4d0` ConfigurableAuditor 走 WorkflowAuditSetting | 文档库不走审批, 不用这个 |
| `9d66064` gh-ost precheck 过度限制修正 | 文档库上传有白名单, 思路一致 |
| `eaf9853` cancel 已审核工单抛 "审批权限组不存在" | 文档库无 cancel, 不影响 |
| `e669567` column_diff use 前缀兼容 | 文档库不上传 SQL, 不影响 |
| `0b62856` column_diff modal 模板位置 | 文档库详情页用新模板, 复用这个 lesson |
| `76d48cc` + `324a53a` ghost task error_message 中文名 | 文档库 audit_log 用 `request.user.display or request.user.username`, 复用 |

---

**作者**: mavis  ·  **日期**: 2026-08-24 18:13  ·  **版本**: v1.0  ·  **状态**: 设计稿 (待拍板)
