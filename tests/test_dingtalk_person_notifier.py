"""DingdingPersonNotifier 路由逻辑单测 (v0.1.7 dingtalk 1对1 通知).

覆盖:
1) GroupDingtalkAuditor 精确匹配 (group + resource_group) -> 用 dingtalk_user_ids
2) GroupDingtalkAuditor fallback 跨资源组通用 (resource_group=None) -> 用 dingtalk_user_ids
3) GroupDingtalkAuditor dingtalk_cc_user_ids 一并加入
4) dingtalk_dept_id -> get_dept_user_ids 拉部门下 user (mock 掉 HTTP)
5) 没 GroupDingtalkAuditor 配置 -> fallback Users.ding_user_id
6) current_audit 多级 ("3,4") -> 按主当前节点匹配 (current_audit)
"""
import json
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group

from sql.extensions.dingtalk_oa.models import GroupDingtalkAuditor
from sql.notify import DingdingPersonNotifier, LegacyMessage


@pytest.mark.django_db
class TestDingdingPersonNotifierRouting:
    """DingdingPersonNotifier._resolve_dingtalk_user_ids 路由逻辑."""

    def _make_audit(self, current_audit="3", group_id=25, **kw):
        """构造一个 mock WorkflowAudit, 只设 _resolve_dingtalk_user_ids 用的字段."""
        from types import SimpleNamespace
        return SimpleNamespace(
            current_audit=current_audit,
            group_id=group_id,
            **kw,
        )

    def test_group_auditor_exact_match_uses_dingtalk_user_ids(self):
        """场景1: (group=3, resource_group=25) 精确匹配 -> 用其 dingtalk_user_ids."""
        Group.objects.create(id=3, name="DBA")
        GroupDingtalkAuditor.objects.create(
            group_id=3,
            resource_group_id=25,
            dingtalk_user_ids=json.dumps(["dba_alice", "dba_bob"]),
            is_active=True,
        )
        notifier = DingdingPersonNotifier.__new__(DingdingPersonNotifier)
        notifier.audit = self._make_audit(current_audit="3", group_id=25)
        m = LegacyMessage(msg_title="t", msg_content="c", msg_to=[])

        result = sorted(notifier._resolve_dingtalk_user_ids(m))
        assert result == ["dba_alice", "dba_bob"]

    def test_group_auditor_fallback_to_cross_resource_group(self):
        """场景2: (group=3, resource_group=25) 找不到, fallback 到 (group=3, resource_group=None)."""
        Group.objects.create(id=3, name="DBA")
        GroupDingtalkAuditor.objects.create(
            group_id=3,
            resource_group_id=None,
            dingtalk_user_ids=json.dumps(["dba_cross"]),
            is_active=True,
        )
        notifier = DingdingPersonNotifier.__new__(DingdingPersonNotifier)
        notifier.audit = self._make_audit(current_audit="3", group_id=99)
        m = LegacyMessage(msg_title="t", msg_content="c", msg_to=[])

        result = sorted(notifier._resolve_dingtalk_user_ids(m))
        assert result == ["dba_cross"]

    def test_cc_user_ids_merged(self):
        """场景3: dingtalk_cc_user_ids 一并加入结果."""
        Group.objects.create(id=3, name="DBA")
        GroupDingtalkAuditor.objects.create(
            group_id=3,
            resource_group_id=25,
            dingtalk_user_ids=json.dumps(["main"]),
            dingtalk_cc_user_ids=json.dumps(["cc1", "cc2"]),
            is_active=True,
        )
        notifier = DingdingPersonNotifier.__new__(DingdingPersonNotifier)
        notifier.audit = self._make_audit(current_audit="3", group_id=25)
        m = LegacyMessage(msg_title="t", msg_content="c", msg_to=[])

        result = sorted(notifier._resolve_dingtalk_user_ids(m))
        assert result == ["cc1", "cc2", "main"]

    def test_dept_id_resolves_to_user_list(self):
        """场景4: dingtalk_dept_id -> 拉部门下 userid, mock get_oa_access_token + get_dept_user_ids."""
        Group.objects.create(id=3, name="DBA")
        GroupDingtalkAuditor.objects.create(
            group_id=3,
            resource_group_id=25,
            dingtalk_dept_id="dept_42",
            is_active=True,
        )
        notifier = DingdingPersonNotifier.__new__(DingdingPersonNotifier)
        notifier.audit = self._make_audit(current_audit="3", group_id=25)
        m = LegacyMessage(msg_title="t", msg_content="c", msg_to=[])

        with patch(
            "sql.notify.get_oa_access_token", return_value="fake_token"
        ), patch(
            "sql.notify.get_dept_user_ids", return_value=["dept_user_1", "dept_user_2"]
        ):
            result = sorted(notifier._resolve_dingtalk_user_ids(m))
        assert result == ["dept_user_1", "dept_user_2"]

    def test_fallback_to_users_ding_user_id_when_no_auditor(self):
        """场景5: 没 GroupDingtalkAuditor 配置 -> fallback Users.ding_user_id."""
        from types import SimpleNamespace
        # 创建一个 mock User，有 ding_user_id 字段
        u1 = SimpleNamespace(ding_user_id="user_a")
        u2 = SimpleNamespace(ding_user_id="")  # 空的不算
        u3 = SimpleNamespace(ding_user_id="user_c")
        m = LegacyMessage(msg_title="t", msg_content="c", msg_to=[u1, u2], msg_cc=[u3])

        notifier = DingdingPersonNotifier.__new__(DingdingPersonNotifier)
        notifier.audit = self._make_audit(current_audit="3", group_id=25)

        result = sorted(notifier._resolve_dingtalk_user_ids(m))
        assert result == ["user_a", "user_c"]

    def test_current_audit_with_multiple_levels(self):
        """场景6: current_audit='3,4' 多级 -> 只按主节点(3)匹配 (current_audit 第一个)."""
        from types import SimpleNamespace
        Group.objects.create(id=3, name="DBA")
        Group.objects.create(id=4, name="PM")
        # 主节点 3 配了映射
        GroupDingtalkAuditor.objects.create(
            group_id=3,
            resource_group_id=25,
            dingtalk_user_ids=json.dumps(["dba_x"]),
            is_active=True,
        )
        notifier = DingdingPersonNotifier.__new__(DingdingPersonNotifier)
        notifier.audit = self._make_audit(current_audit="3,4", group_id=25)
        m = LegacyMessage(msg_title="t", msg_content="c", msg_to=[])

        result = sorted(notifier._resolve_dingtalk_user_ids(m))
        assert result == ["dba_x"]

    def test_inactive_auditor_skipped(self):
        """场景7: is_active=False 的映射忽略."""
        Group.objects.create(id=3, name="DBA")
        GroupDingtalkAuditor.objects.create(
            group_id=3,
            resource_group_id=25,
            dingtalk_user_ids=json.dumps(["disabled"]),
            is_active=False,
        )
        notifier = DingdingPersonNotifier.__new__(DingdingPersonNotifier)
        notifier.audit = self._make_audit(current_audit="3", group_id=25)
        # 消息里有个有 ding_user_id 的 user 当 fallback
        from types import SimpleNamespace
        m = LegacyMessage(
            msg_title="t", msg_content="c",
            msg_to=[SimpleNamespace(ding_user_id="fallback_user")],
        )

        result = sorted(notifier._resolve_dingtalk_user_ids(m))
        # is_active=False 的被跳过，走 fallback
        assert result == ["fallback_user"]
