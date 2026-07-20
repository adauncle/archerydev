"""driver 抽象层测试。"""

import pytest

from sql.extensions.audit_drivers.archery import ArcheryDriver
from sql.extensions.audit_drivers.base import (
    AuditDriver,
    Decision,
    DriverStartResult,
)
from sql.extensions.audit_drivers.configurable_auditor import ConfigurableAuditor
from sql.extensions.audit_drivers.registry import (
    DRIVER_REGISTRY,
    get_driver,
    register_driver,
)


# ============================== ArcheryDriver ==============================


def test_archery_driver_name():
    driver = ArcheryDriver()
    assert driver.name == "archery"


def test_archery_driver_is_abstract_subclass():
    """ArcheryDriver 必须实现 AuditDriver 的全部抽象方法。"""
    driver = ArcheryDriver()
    assert isinstance(driver, AuditDriver)


def test_archery_driver_start_returns_empty_external_id():
    driver = ArcheryDriver()
    result = driver.start(workflow=None, audit=None, flow=None)
    assert isinstance(result, DriverStartResult)
    assert result.external_id == ""


def test_archery_driver_apply_decision_noop():
    driver = ArcheryDriver()
    assert driver.apply_decision(audit=None, decision=Decision.PASS, actor=None, remark="x") is None
    assert driver.apply_decision(audit=None, decision=Decision.REJECT, actor=None, remark="x") is None


def test_archery_driver_terminate_noop():
    driver = ArcheryDriver()
    assert driver.terminate(audit=None, actor=None, remark="abort") is None


def test_archery_driver_get_status_local():
    driver = ArcheryDriver()
    assert driver.get_status(audit=None) == {"status": "local"}


def test_archery_driver_callback_not_implemented():
    driver = ArcheryDriver()
    with pytest.raises(NotImplementedError):
        driver.handle_callback(request=None)


# ============================== Registry ==============================


def test_registry_contains_archery():
    assert "archery" in DRIVER_REGISTRY
    assert DRIVER_REGISTRY["archery"].endswith(":ArcheryDriver")


def test_registry_get_driver_archery():
    driver = get_driver("archery")
    assert isinstance(driver, ArcheryDriver)
    assert driver.name == "archery"


def test_registry_get_driver_unknown_raises_value_error():
    with pytest.raises(ValueError) as exc:
        get_driver("not_in_registry")
    assert "Unknown audit_driver" in str(exc.value)


def test_registry_register_driver_in_memory(monkeypatch):
    """register_driver 只是写入 DRIVER_REGISTRY；get_driver 才会 import。"""
    register_driver("mock_test", "sql.extensions.audit_drivers.archery:ArcheryDriver")
    assert "mock_test" in DRIVER_REGISTRY
    driver = get_driver("mock_test")
    assert driver.name == "archery"


def test_registry_get_driver_import_error_raises_import_error(monkeypatch):
    """指向不存在模块时 get_driver 应该抛 ImportError，不是 ValueError。"""
    register_driver("bad_test", "sql.does.not.exist:Nope")
    with pytest.raises(ImportError):
        get_driver("bad_test")


# ============================== ConfigurableAuditor ==============================


def test_configurable_auditor_feature_disabled_by_default(settings):
    """未设 CUSTOM_DINGTALK_OA_ENABLED 时，特性必须默认关闭。"""
    assert hasattr(settings, "CUSTOM_DINGTALK_OA_ENABLED") is False or settings.CUSTOM_DINGTALK_OA_ENABLED is False
    # 不实例化 AuditV2 父类（需要 workflow）；只验证 default
    ca = ConfigurableAuditor.__new__(ConfigurableAuditor)
    assert ca._feature_enabled() is False


def test_configurable_auditor_feature_enabled_when_set(settings):
    settings.CUSTOM_DINGTALK_OA_ENABLED = True
    ca = ConfigurableAuditor.__new__(ConfigurableAuditor)
    assert ca._feature_enabled() is True


def test_abstract_audit_driver_cannot_be_instantiated():
    with pytest.raises(TypeError):
        AuditDriver()  # type: ignore[abstract]
