# -*- coding: UTF-8 -*-
## CUSTOM-MODIFIED: get_chart_data 加 try/except 优雅降级
## @ 2026-08-17 @ mavis
## 修 Archery 上游 1.14.0 缺陷: 9+1 张图串行查询无 try/except, 1 张挂整页 500
## 134 dev 暴露场景: mysql_slow_query_review_history 表不在 (1146)
## 风险: 110 prod 任何上游 schema 变化都会触发, 加 try/except 后表丢了不 500
## 8/17 drill 4 Case 全过: 单图挂 / 多图挂 / 全挂 / 全好
## changelog: docs/changelogs/2026-08-17_dashboard-graceful-degrade.md
import logging
from django.contrib.auth.decorators import permission_required
from django.shortcuts import render
from django.http import JsonResponse
from django.core.exceptions import ValidationError

logger = logging.getLogger("default")

from sql.models import SqlWorkflow, QueryPrivilegesApply, Users, Instance

from common.utils.chart_dao import ChartDao
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from pyecharts.globals import CurrentConfig
from pyecharts import options as opts
from pyecharts.charts import Pie, Bar, Line

CurrentConfig.ONLINE_HOST = "/static/echarts/"


@permission_required("sql.menu_dashboard", raise_exception=True)
def pyecharts(request):
    # 获取统计数据
    dashboard_count_stats = {
        "sql_wf_cnt": SqlWorkflow.objects.count(),
        "query_wf_cnt": QueryPrivilegesApply.objects.count(),
        "user_cnt": Users.objects.filter(is_active=1).count(),
        "ins_cnt": Instance.objects.count(),
    }
    chart_dao = ChartDao()

    data = chart_dao.instance_count_by_type()
    attr = [row[0] for row in data["rows"]]
    value = [row[1] for row in data["rows"]]
    pie6 = create_pie_chart(attr, value)

    data = chart_dao.query_instance_env_info()
    bar4 = gen_stack_chart(data)

    instance_chart = {
        "pie6": pie6.render_embed(),
        "bar4": bar4.render_embed(),
    }
    # 获取图表数据
    # 字符串，近7天日期 "%Y-%m-%d"
    today = (date.today() - relativedelta(days=-1)).strftime("%Y-%m-%d")
    one_week_before = (date.today() - relativedelta(days=+6)).strftime("%Y-%m-%d")
    dashboard_chart = get_chart_data(one_week_before, today)

    return render(
        request,
        "dashboard.html",
        {
            "instance_chart": instance_chart,
            "chart": dashboard_chart,
            "count_stats": dashboard_count_stats,
        },
    )


@permission_required("sql.menu_dashboard", raise_exception=True)
def DashboardApi(request):
    start_date_str = request.GET.get("start_date")
    end_date_str = request.GET.get("end_date")

    try:
        start_date = validate_date(start_date_str)
        end_date = validate_date(end_date_str)
    except ValidationError as e:
        return JsonResponse({"error: 日期有误"}, status=400)

    dashboard_chart = get_chart_data(start_date, end_date)

    return JsonResponse({"chart": dashboard_chart})


def validate_date(date_str):
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        return date_obj.strftime("%Y-%m-%d")
    except ValueError:
        raise ValidationError(
            f"Invalid date format: {date_str}. Expected format: YYYY-MM-DD."
        )


def get_chart_data(start_date, end_date):
    """
    获取 dashboard 9+1 = 10 张图数据。

    上游原版 9+1 张图查询串行执行,任何 1 张抛异常都会让整页 500。
    8/17 mavis 加 try/except 优雅降级,1 张图挂只影响那 1 张 (返空字符串),
    其他 9 张照常显示,整页 200。

    changelog: docs/changelogs/2026-08-17_dashboard-graceful-degrade.md
    """
    logging.info("Dashboard: start_date: %s, end_date: %s", start_date, end_date)
    chart_dao = ChartDao()
    chart = {}

    def _safe(name, builder):
        """1 张图查失败不影响其他图,失败时返空字符串 (模板渲染空 div)"""
        try:
            return builder()
        except Exception as e:
            logger.warning("dashboard %s failed: %s", name, e)
            return ""

    # SQL上线数量 (bar1)
    def _bar1():
        data = chart_dao.workflow_by_date(start_date, end_date)
        attr = chart_dao.get_date_list(
            datetime.strptime(start_date, "%Y-%m-%d"),
            datetime.strptime(end_date, "%Y-%m-%d"),
        )
        _dict = {row[0]: row[1] for row in data["rows"]}
        value = [_dict.get(day, 0) for day in attr]
        return create_bar_chart(attr, value).render_embed()

    # SQL上线统计 (pie1)
    def _pie1():
        data = chart_dao.workflow_by_group(start_date, end_date)
        attr = [row[0] for row in data["rows"]]
        value = [row[1] for row in data["rows"]]
        return create_pie_chart(attr, value).render_embed()

    # SQL语法类型 (pie2)
    def _pie2():
        data = chart_dao.syntax_type(start_date, end_date)
        attr = [row[0] for row in data["rows"]]
        value = [row[1] for row in data["rows"]]
        return create_pie_chart(attr, value).render_embed()

    # SQL上线用户 (bar2)
    def _bar2():
        data = chart_dao.workflow_by_user(start_date, end_date)
        attr = [row[0] for row in data["rows"]]
        value = [row[1] for row in data["rows"]]
        return create_bar_chart(attr, value).render_embed()

    # SQL查询统计 (line1)
    def _line1():
        attr = chart_dao.get_date_list(
            datetime.strptime(start_date, "%Y-%m-%d"),
            datetime.strptime(end_date, "%Y-%m-%d"),
        )
        effect_data = chart_dao.querylog_effect_row_by_date(start_date, end_date)
        effect_dict = {row[0]: int(row[1]) for row in effect_data["rows"]}
        effect_value = [effect_dict.get(day, 0) for day in attr]
        count_data = chart_dao.querylog_count_by_date(start_date, end_date)
        count_dict = {row[0]: int(row[1]) for row in count_data["rows"]}
        count_value = [count_dict.get(day, 0) for day in attr]
        line = Line(init_opts=opts.InitOpts(width="600", height="380px", bg_color="white"))
        line.set_global_opts(
            title_opts=opts.TitleOpts(title=""),
            legend_opts=opts.LegendOpts(selected_mode="single"),
        )
        line.add_xaxis(attr)
        line.add_yaxis(
            "检索行数",
            effect_value,
            is_smooth=True,
            markpoint_opts=opts.MarkPointOpts(data=[opts.MarkPointItem(type_="average")]),
        )
        line.add_yaxis(
            "检索次数",
            count_value,
            is_smooth=True,
            markline_opts=opts.MarkLineOpts(
                data=[opts.MarkLineItem(type_="max"), opts.MarkLineItem(type_="average")]
            ),
        )
        return line.render_embed()

    # SQL查询用户 (pie4)
    def _pie4():
        data = chart_dao.querylog_effect_row_by_user(start_date, end_date)
        attr = [row[0] for row in data["rows"]]
        value = [int(row[1]) for row in data["rows"]]
        return create_pie_chart(attr, value).render_embed()

    # DB检索行数 (pie5)
    def _pie5():
        data = chart_dao.querylog_effect_row_by_db(start_date, end_date)
        attr = [row[0] for row in data["rows"]]
        value = [int(row[1]) for row in data["rows"]]
        return create_pie_chart(attr, value).render_embed()

    # 慢查询db/user维度统计 (pie3) — 上游 134 dev 缺表 1146 起点
    def _pie3():
        data = chart_dao.slow_query_count_by_db_by_user()
        attr = [row[0] for row in data["rows"]]
        value = [int(row[1]) for row in data["rows"]]
        return create_pie_chart(attr, value).render_embed()

    # 慢查询db维度统计 (bar3) — 上游 134 dev 缺表 1146 起点
    def _bar3():
        data = chart_dao.slow_query_count_by_db()
        attr = [row[0] for row in data["rows"]]
        value = [row[1] for row in data["rows"]]
        return create_bar_chart(attr, value).render_embed()

    # SQL上线工单 (bar5)
    def _bar5():
        data = chart_dao.query_sql_prod_bill(start_date, end_date)
        attr = [row[0] for row in data["rows"]]
        value = [row[1] for row in data["rows"]]
        return create_bar_chart(attr, value).render_embed()

    chart["bar1"] = _safe("bar1", _bar1)
    chart["bar2"] = _safe("bar2", _bar2)
    chart["bar3"] = _safe("bar3", _bar3)
    chart["bar5"] = _safe("bar5", _bar5)
    chart["pie1"] = _safe("pie1", _pie1)
    chart["pie2"] = _safe("pie2", _pie2)
    chart["pie3"] = _safe("pie3", _pie3)
    chart["pie4"] = _safe("pie4", _pie4)
    chart["pie5"] = _safe("pie5", _pie5)
    chart["line1"] = _safe("line1", _line1)

    return chart


# 创建柱状图
def create_bar_chart(attr, value, width="600", height="380px"):
    bar = Bar(init_opts=opts.InitOpts(width=width, height=height, bg_color="white"))
    bar.add_xaxis(attr)

    if len(attr) > 60:
        bar.add_yaxis(
            "",
            value,
            label_opts=opts.LabelOpts(is_show=False),
            markline_opts=opts.MarkLineOpts(
                data=[
                    opts.MarkLineItem(type_="max"),
                    opts.MarkLineItem(type_="average"),
                ]
            ),
        )
    else:
        bar.add_yaxis("", value, label_opts=opts.LabelOpts())

    if len(attr) > 0 and attr[0] and len(attr[0]) > 20:
        bar.set_global_opts(
            xaxis_opts=opts.AxisOpts(axislabel_opts=opts.LabelOpts(rotate=-10)),
            legend_opts=opts.LegendOpts(pos_left="right"),
        )
    return bar


# 创建饼图
def create_pie_chart(attr, value, width="600", height="380px"):
    pie = Pie(init_opts=opts.InitOpts(width=width, height=height, bg_color="white"))
    pie.set_global_opts(
        title_opts=opts.TitleOpts(title=""),
        legend_opts=opts.LegendOpts(
            orient="vertical", pos_top="15%", pos_left="2%", is_show=False
        ),
    )
    pie.set_series_opts(label_opts=opts.LabelOpts(formatter="{b}: {c}"))
    pie.add("", [list(z) for z in zip(attr, value)]) if attr and value else None
    return pie


# 生成堆叠图
def gen_stack_chart(data):
    rows = data.get("rows", [])
    envs = list(set(row[0] for row in rows if len(row) >= 1))  # X轴
    db_types = list(set(row[1] for row in rows if len(row) >= 2))  # 堆叠1
    env_dict = {env: {db_type: 0 for db_type in db_types} for env in envs}  # 堆叠2

    # 填充
    for row in rows:
        if len(row) == 3:
            env, db_type, count = row
            if env in env_dict and db_type in env_dict[env]:
                env_dict[env][db_type] = count

    # 将环境-数据库类型的计数转化为数据列表
    db_data = {db_type: [] for db_type in db_types}
    for env in envs:
        for db_type in db_types:
            db_data[db_type].append(env_dict[env][db_type])

    # 绘制堆叠柱状图
    stack_bar = Bar(
        init_opts=opts.InitOpts(width="800px", height="380px", bg_color="white")
    ).add_xaxis(
        envs
    )  # 设置X轴数据（环境）

    for db_type in db_types:
        y_values = db_data[db_type]

        stack_bar.add_yaxis(
            series_name=db_type,
            y_axis=y_values,
            stack="stack1",
            label_opts=opts.LabelOpts(is_show=False),
        )

    # 隐藏Y轴的刻度标签
    stack_bar.set_global_opts(
        xaxis_opts=opts.AxisOpts(axislabel_opts=opts.LabelOpts(rotate=-10)),
        legend_opts=opts.LegendOpts(pos_left="right"),
    )
    return stack_bar
