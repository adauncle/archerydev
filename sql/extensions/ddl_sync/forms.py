"""DDL 跨库同步 forms —— DdlSyncPair 创建/编辑表单

## CUSTOM-MODIFIED: v0.5.0-alpha DDL 跨库同步 forms @ 2026-09-01 @ mavis
设计参考: docs/designs/2026-09-01_ddl-sync-data-model.md §2
"""

from django import forms
from sql.models import Instance, ResourceGroup, Users

from .models import DdlSyncPair


class DdlSyncPairForm(forms.ModelForm):
    """库对配置表单 - 创建/编辑"""

    ## CUSTOM-MODIFIED: 源 instance / 目标 instance widget 限制 @ 2026-09-01 @ mavis
    source_instance = forms.ModelChoiceField(
        queryset=Instance.objects.all().order_by("instance_name"),
        label="业务库实例",
        help_text="业务库所在 MySQL instance (archery 配的 instance)",
    )
    target_instance = forms.ModelChoiceField(
        queryset=Instance.objects.all().order_by("instance_name"),
        label="历史库实例",
        help_text="历史库所在 MySQL instance (archery 配的 instance)",
    )

    ## CUSTOM-MODIFIED: D22 target_group 镜像工单审批组 @ 2026-09-03 @ mavis
    ## 关联: docs/changelogs/2026-09-03_ddl-sync-w2-d22-mirror-target-group.md
    target_group = forms.ModelChoiceField(
        queryset=ResourceGroup.objects.all().order_by("group_id"),
        label="镜像工单审批组",
        help_text="DBA 显式选 (Instance 是 M2M ResourceGroup, 不能自动猜); 走当前 group_id 的 WorkflowAuditSetting (SQL_REVIEW) 拿审流, 如 'prod core for 历史库' (DBA 单一审批)",
    )

    class Meta:
        model = DdlSyncPair
        fields = [
            "name", "source_instance", "source_db",
            "target_instance", "target_db",
            "target_group",
            "sync_mode", "enabled",
        ]
        labels = {
            "name": "配对名",
            "source_db": "业务库名",
            "target_db": "历史库名",
            "sync_mode": "同步模式",
            "enabled": "启用",
        }
        help_texts = {
            "name": "DBA 自己起, 如 'accesscard 库对'",
            "source_db": "业务库 schema 名 (如 'hly_accesscard')",
            "target_db": "历史库 schema 名 (如 'hly_activity')",
            "sync_mode": "R1 默认 blacklist (业务库全同步, 显式排除)",
            "enabled": "禁用不影响历史数据 (软删)",
        }
        widgets = {
            "sync_mode": forms.RadioSelect,
        }

    def clean(self):
        cleaned_data = super().clean()
        source_instance = cleaned_data.get("source_instance")
        source_db = cleaned_data.get("source_db")
        target_instance = cleaned_data.get("target_instance")
        target_db = cleaned_data.get("target_db")
        target_group = cleaned_data.get("target_group")

        # 业务库跟历史库不能是同一个 instance + 同一个 db
        if source_instance and target_instance and source_db and target_db:
            if source_instance.id == target_instance.id and source_db == target_db:
                raise forms.ValidationError(
                    "业务库跟历史库不能是同一个 instance + 同一个 db"
                )

        # D22: 镜像工单审批组必填 (没填会导致 sync_trigger fallback 走 source_workflow.group_id,
        # 走业务组审批, 违反"镜像工单走历史库审批流"设计)
        if not target_group:
            raise forms.ValidationError(
                "镜像工单审批组必填 (DBA 显式选, 走历史库组审批流, "
                "不能 fallback 走业务组, 否则 wf#121 那种 bug 会重现)"
            )

        return cleaned_data

    def save(self, commit=True):
        # D22: 同步 target_group_name (跟 group_id 配对, 给 SqlWorkflow.group_name 用)
        instance = super().save(commit=False)
        if instance.target_group:
            instance.target_group_name = instance.target_group.group_name
        if commit:
            instance.save()
            self.save_m2m()
        return instance
