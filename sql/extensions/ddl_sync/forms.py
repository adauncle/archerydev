"""DDL 跨库同步 forms —— DdlSyncPair 创建/编辑表单

## CUSTOM-MODIFIED: v0.5.0-alpha DDL 跨库同步 forms @ 2026-09-01 @ mavis
设计参考: docs/designs/2026-09-01_ddl-sync-data-model.md §2
"""

from django import forms
from sql.models import Instance, Users

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

    class Meta:
        model = DdlSyncPair
        fields = [
            "name", "source_instance", "source_db",
            "target_instance", "target_db",
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

        # 业务库跟历史库不能是同一个 instance + 同一个 db
        if source_instance and target_instance and source_db and target_db:
            if source_instance.id == target_instance.id and source_db == target_db:
                raise forms.ValidationError(
                    "业务库跟历史库不能是同一个 instance + 同一个 db"
                )

        return cleaned_data
