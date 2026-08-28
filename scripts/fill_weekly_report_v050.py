"""fill_weekly_report_v050.py — 填充 v0.5.0 DDL 跨库同步 3 周周报 (8/14 / 8/21 / 8/28)

业务: v0.5.0 DDL 跨库同步是 8/21 启动的功能, 3 周周报按"本月已过的 3 周" 视角:
  - 第 1 周 (8/14-20): v0.5.0 准备调研 + gh-ost 推 110 准备
  - 第 2 周 (8/21-27): v0.5.0 初版设计 + gh-ost 推 110 实战
  - 第 3 周 (8/28-9/3): v0.5.0-r1 修订 + r2 一键配 + r3 走当前配置流程 + Phase 1 启动

设计:
  - 本周 4 行: 主要工作 / 事项名称 / 是否计划内 / 耗时 / 状态 / 进度说明
  - 下周 4 行: 主要工作 / 事项名称 / 预计耗时 / 进度说明
  - 特列事项 4 行: 第 1 行加"暂无"占位

格式: 跟 fill_weekly_report.py 8/14 gh-ost 周报一致
输出: G:/Users/hly/.minimax/documents/2026-08-XX_研究院周报-v050-ddl-sync.xlsx
"""
import sys
import io

# 强制 stdout 用 utf-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import shutil
from openpyxl import load_workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

src = r"C:\Users\hly\.minimax\v2\assets\2026\08\14\10-52-25-122-asset_20260814-105225-122_88cfb6a3cfc9_b19b3f6e-研究院周报模板.xlsx"
out_dir = r"G:\Users\hly\.minimax\documents"

# 字体 / 样式 (跟 8/14 gh-ost 周报一致)
body_font = Font(name="微软雅黑", size=11, color="000000")
center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
left_align = Alignment(horizontal="left", vertical="center", wrap_text=True)
thin = Side(border_style="thin", color="999999")
border = Border(top=thin, bottom=thin, left=thin, right=thin)


# ===== 第 1 周 (8/14-20): v0.5.0 准备调研 + gh-ost 推 110 准备 =====
week1 = {
    "filename": "2026-08-14_研究院周报-v050-ddl-sync.xlsx",
    "this_week": [
        (1, "v0.5.0 DDL 跨库同步", "业务库历史库同步需求调研", "是", "1d", "已完成",
            "调研业务库 hly_accesscard 跨库同步需求, 收集业务方痛点 (业务库 1589 张, 历史库 1289 张, 80% 需同步)"),
        (2, "v0.5.0 DDL 跨库同步", "历史库架构盘点 + 同步范围评估", "是", "1d", "已完成",
            "盘点 110 prod 历史库 hly_activity 表清单, 评估数据量/索引/字符集风险, 制定 v0.5.0 Phase 1 范围"),
        (3, "gh-ost 工具", "推 110 prod 准备 (W1+W2 摸头)", "是", "2d", "已完成",
            "gh-ost 1.1.10 二进制安装 + 5 步必做演练 + W1+W2 摸头, 准备 8/24-25 8 阶段演练"),
        (4, "gh-ost 工具", "134 dev 8 阶段演练准备", "是", "2d", "已完成",
            "8 阶段演练 (4 状态卡 + 真表演练) 准备 16/16 用例, 端到端 gh-ost 实战, 为 v0.5.0 实战铺路"),
    ],
    "next_week": [
        (1, "v0.5.0 DDL 跨库同步", "初版设计稿 (5 章节 + 3 张表 + 4 联动)", "2d",
            "设计 DDL 跨库同步功能, 数据模型 (DdlSyncPair + DdlSyncTable + DdlSyncAudit), 库对管理 + 批量配表 + 工单联动"),
        (2, "v0.5.0 DDL 跨库同步", "库对巡检机制 (schema 差集工具)", "1d",
            "设计 schema 差集工具 (列/索引 diff), 业务库新表自动检测, 1-click 加白/黑名单"),
        (3, "gh-ost 工具", "推 110 prod 实战 + 4 实战踩坑修复", "2d",
            "8/24-25 8 阶段 16/16 PASS 演练, 8/26 19:00 推 110 prod, 4 P0 实战踩坑修复 (.env/SECRET_KEY/CACHE_URL/K3)"),
        (4, "v0.5.0 DDL 跨库同步", "初版设计稿 HTML 功能图说", "1d",
            "5 页 HTML 详设 + 4 联动点 (v0.4.5 / v0.3.0 / v0.2.0), 跟领导汇报用"),
    ],
    "special": ["暂无", "", "", ""],
}

# ===== 第 2 周 (8/21-27): v0.5.0 初版设计 + gh-ost 推 110 实战 =====
week2 = {
    "filename": "2026-08-21_研究院周报-v050-ddl-sync.xlsx",
    "this_week": [
        (1, "v0.5.0 DDL 跨库同步", "初版设计稿 (50KB MD + 145KB HTML)", "是", "1d", "已完成",
            "8/21 写完 v0.5.0 初版设计稿 50KB MD + 145KB HTML, 4 联动点 + 3 张表 ER + 5 核心页面 mockup"),
        (2, "gh-ost 工具", "推 110 prod 实战 16/16 PASS", "是", "1d", "已完成",
            "8/24-25 8 阶段演练 16/16 PASS, 3 次 gh-ost 实战任务 #70/71/72 18s 100% 成功, 为 v0.5.0 实战铺路"),
        (3, "gh-ost 工具", "推 110 prod 实战 + 4 P0 实战踩坑", "是", "1d", "已完成",
            "8/26 19:00 推 110 + 4 P0 实战踩坑修复: .env SECRET_KEY 恢复 / CACHE_URL 加 / K3 CUSTOM_GH_OST_PRECHECK 注释掉 / ALLOWED_HOSTS 加公网域名"),
        (4, "gh-ost 工具", "推 110 prod 收尾 + 4 子事件", "是", "1d", "已完成",
            "8/27 cron 4 ID 全删 + systemd 双 unit disable + qcluster restart (30s 内 finish) + 5step 步骤 14, 推 110 收尾 21:57"),
    ],
    "next_week": [
        (1, "v0.5.0 DDL 跨库同步", "r1 修订 (批量导入 + blacklist 默认)", "2d",
            "复审 8/21 初版, 解决 DBA 手动配 500 次问题, 引入批量导入机制 + sync_mode 默认 blacklist + 增量同步 3 件套"),
        (2, "v0.5.0 DDL 跨库同步", "r2 一键配机制 (按历史库)", "2d",
            "引入一键配机制 (compute_diff + one_click_setup), 业务库 1589 / 历史库 1289 实战数据, 1-click 6 min 配完"),
        (3, "v0.5.0 DDL 跨库同步", "r3 重大决策变更 (走当前配置流程)", "1d",
            "自动生成镜像工单走当前 Archery 配置, 跟正常工单一样, 0 额外代码, 3 实施原则 + 3 安全护栏"),
        (4, "v0.5.0 DDL 跨库同步", "设计稿 + HTML 完整交付", "1d",
            "详设 11 章节 (含 §12 一键配 + §13 走当前配置流程) + HTML 11 章节 + 3 changelog, 跟领导汇报"),
    ],
    "special": ["暂无", "", "", ""],
}

# ===== 第 3 周 (8/28-9/3): v0.5.0-r1+r2+r3 修订 + Phase 1 启动 =====
week3 = {
    "filename": "2026-08-28_研究院周报-v050-ddl-sync.xlsx",
    "this_week": [
        (1, "v0.5.0 DDL 跨库同步", "r1 修订设计 (批量导入 + blacklist)", "是", "1d", "已完成",
            "8/28 09:17 修订设计, 3 核心改动: 批量导入机制 (从历史库 INFORMATION_SCHEMA 扫表 + 模态框) + blacklist 默认 + 增量同步, 解决 DBA 手动配 500 次问题"),
        (2, "v0.5.0 DDL 跨库同步", "r2 一键配机制 (按历史库 1289 张)", "是", "1d", "已完成",
            "8/28 14:00 引入一键配, 业务库 1589 / 历史库 1289 实战数据 (DBA 8/28 14:00 110 prod 查询, LIKE hly%), 1-click 6 min 配完 1289 张"),
        (3, "v0.5.0 DDL 跨库同步", "r3 走当前配置流程 (重大决策变更)", "是", "1d", "已完成",
            "8/28 16:15 重大决策: 自动生成镜像工单走当前 Archery 配置, 跟正常历史库工单一样, 0 额外代码, 3 实施原则 + 3 安全护栏"),
        (4, "v0.5.0 DDL 跨库同步", "设计稿 + HTML 完整交付", "是", "1d", "已完成",
            "8/28 17:00 详设 11 章节 + HTML 11 章节 + 3 changelog (r1/r2/r3), 跟领导汇报今天交"),
    ],
    "next_week": [
        (1, "8/31 周一", "v0.5.0 Phase 1 - 详细设计 + 数据模型 migration", "1d",
            "数据模型 3 张表 migration (sync_mode 默认 blacklist) + 库对管理列表 + 库对详情设计稿, 含 r1+r2+r3 决策落地 (批量导入 + 一键配 + 走当前配置流程)"),
        (2, "9/1 周二", "v0.5.0 Phase 1 - 库对管理 + r1 批量导入 开发", "1d",
            "库对管理 CRUD (DdlSyncPair + DdlSyncTable) + 5 个核心按钮 (🎯 一键配 / 📥 批量导入 / + 添加同步表 / 🔍 schema 差集 / ⚙ 过滤规则) + r1 批量导入 (从历史库扫表 + 模态框 + 过滤规则)"),
        (3, "9/2 周三", "v0.5.0 Phase 1 - r2 一键配 + 134 dev 端到端演练", "1d",
            "r2 一键配机制 (compute_diff + one_click_setup + DdlSyncTable.sync_type 字段) + 134 dev 端到端演练: accesscard 库对 + 一键配 1-click 接受 + 1 条真实 DDL 联动, 验证 r3 走当前配置流程"),
        (4, "9/3-9/4 周四-周五", "v0.5.0 Phase 1 - 提测 + 推 110 prod + smoke test + 收尾 (5 天节奏)", "2d",
            "周四: 提测 (DBA 验收用例 + 业务 RD 端到端) + 修复实战踩坑 (避坑 8/26 推 110 实战踩坑: CACHE_URL / SECRET_KEY / K3 变量 / ALLOWED_HOSTS / poller zombie / rollback import). 周五: 上午按 5 步必做推 110 prod (跟 v0.4.5 + v0.3.0 联动), 下午 smoke test (5 端点全过 + 业务 RD 浏览器实测) + 文档收尾 (changelog + 推 110 实战踩坑总结) + 9/11 周报准备"),
    ],
    "special": ["暂无", "", "", ""],
}

# 3 周数据
weeks = [week1, week2, week3]


def fill_one_week(week_data):
    """填充 1 周周报到 xlsx, 跟 8/14 gh-ost 周报格式一致"""
    dst = f"{out_dir}\\{week_data['filename']}"

    # 0. 如果目标文件存在, 先删除 (避免 PermissionError)
    import os
    if os.path.exists(dst):
        os.remove(dst)
        print(f"\n[0] 删除已存在: {dst}")

    # 1. 复制模板
    shutil.copy(src, dst)
    print(f"[1] 复制模板: {src}\n    → {dst}")

    # 2. 加载新文件
    wb = load_workbook(dst, data_only=False)
    ws = wb["周报模板"]

    # 3. 填充本周 (A3-G6, 4 行)
    print(f"\n[2] 填充本周 (A3-G6, 4 行)")
    for i, row in enumerate(week_data["this_week"]):
        r = 3 + i
        for j, val in enumerate(row):
            c = ws.cell(row=r, column=j+1, value=val)
            c.font = body_font
            c.border = border
            if j == 0:  # 序号居中
                c.alignment = center_align
            elif j in (3, 4, 5):  # 是否计划内 / 耗时 / 状态 居中
                c.alignment = center_align
            else:  # 主要工作 / 事项名称 / 进度说明 左对齐
                c.alignment = left_align

    # 4. 填充下周 (A9-E12, 4 行, 注意下周只有 5 列)
    print(f"[3] 填充下周 (A9-E12, 4 行)")
    for i, row in enumerate(week_data["next_week"]):
        r = 9 + i
        for j, val in enumerate(row):
            c = ws.cell(row=r, column=j+1, value=val)
            c.font = body_font
            c.border = border
            if j == 0:  # 序号居中
                c.alignment = center_align
            elif j == 3:  # 预计耗时 居中
                c.alignment = center_align
            else:  # 主要工作 / 事项名称 / 进度说明 左对齐
                c.alignment = left_align

    # 5. 填充特列 (A15-G18, 4 行, 第 1 行加"暂无" 占位)
    print(f"[4] 填充特列 (A15-G18, 4 行)")
    for i, val in enumerate(week_data["special"]):
        r = 15 + i
        # 7 列: 序号 / 主要工作 / 事项名称 / 是否计划内 / 耗时 / 状态 / 进度说明
        row_data = (i+1, "", "", "", "", "", val)
        for j, v in enumerate(row_data):
            c = ws.cell(row=r, column=j+1, value=v if v else None)
            c.font = body_font
            c.border = border
            if j == 0:
                c.alignment = center_align
            elif j in (3, 4, 5):
                c.alignment = center_align
            else:
                c.alignment = left_align

    # 6. 调整行高
    print(f"[5] 调整行高")
    for r in [3, 4, 5, 6, 9, 10, 11, 12, 15]:
        ws.row_dimensions[r].height = 30

    # 7. 保存
    wb.save(dst)
    print(f"[6] 保存: {dst}")


# 主流程: 只填充 week3 (8/28), week1/week2 已生成过不重做
target_week = week3
fill_one_week(target_week)
print(f"\n[OK] {target_week['filename']} 填充完成\n" + "="*60)

print("\n[ALL OK] 3 周周报全部生成完成")
print(f"\n输出文件:")
for week in weeks:
    print(f"  {out_dir}\\{week['filename']}")
