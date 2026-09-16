"""W3 跨库检测单元测试 (134 dev 演练 Case A-E, 9/16)

@ 2026-09-16 @ mavis
"""
import sys, os, django
sys.path.insert(0, "/opt/archery/prod")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
django.setup()

from sql.utils.cross_db_check import check_cross_db


CASES = [
    # (case_name, sql, db_name, expected_ok, expected_error_substring)
    ("A 跨库 reject", "ALTER TABLE `hly_usercenter`.accesscard_vehicle_change ADD COLUMN xxx", "hly_accesscard", False, "hly_usercenter"),
    ("B 同库 pass", "ALTER TABLE accesscard_vehicle_change ADD COLUMN xxx", "hly_accesscard", True, ""),
    ("C 反引号同库 pass", "ALTER TABLE `hly_accesscard`.accesscard_vehicle_change ADD COLUMN xxx", "hly_accesscard", True, ""),
    ("D 不带反引号跨库 reject", "ALTER TABLE hly_usercenter.accesscard_vehicle_change ADD COLUMN xxx", "hly_accesscard", False, "hly_usercenter"),
    ("E use 切换库不算跨库", "use hly_usercenter;\nALTER TABLE accesscard_vehicle_change ADD COLUMN xxx", "hly_accesscard", True, ""),
    # 实战 9/16 wf#4821 业务方真实形态
    ("F wf#4821 第3条 SQL", "ALTER TABLE hly_usercenter.accesscard_user_vehicle_change ADD COLUMN ocr_travel_vehicletype varchar(150) DEFAULT NULL COMMENT 'OCR行驶证车辆类型'", "hly_accesscard", False, "hly_usercenter"),
    # INSERT/UPDATE/DELETE/CREATE/DROP 跨库
    ("G INSERT 跨库 reject", "INSERT INTO `hly_usercenter`.`output_fee_config` VALUES (302, 1, 159, '账单')", "hly_accesscard", False, "hly_usercenter"),
    ("H UPDATE 跨库 reject", "UPDATE hly_usercenter.accesscard_vehicle_change SET col=1", "hly_accesscard", False, "hly_usercenter"),
    ("I DELETE 跨库 reject", "DELETE FROM hly_usercenter.accesscard_vehicle_change WHERE id=1", "hly_accesscard", False, "hly_usercenter"),
    ("J CREATE 跨库 reject", "CREATE TABLE hly_usercenter.xxx_test (id INT)", "hly_accesscard", False, "hly_usercenter"),
    ("K DROP 跨库 reject", "DROP TABLE hly_usercenter.xxx_test", "hly_accesscard", False, "hly_usercenter"),
    # INSERT 同库 pass
    ("L INSERT 同库 pass", "INSERT INTO `hly_accesscard`.`output_fee_config` VALUES (302, 1, 159, '账单')", "hly_accesscard", True, ""),
    # 空 SQL / 只有 SELECT
    ("M 空 SQL pass", "", "hly_accesscard", True, ""),
    ("N 只有 SELECT pass", "SELECT * FROM accesscard_vehicle_change WHERE id=1", "hly_accesscard", True, ""),
    # 多个 ALTER 一个跨库一个同库 (有跨库就 reject)
    ("O 多个 ALTER 一个跨库 reject", "ALTER TABLE accesscard_vehicle_change ADD COLUMN a INT;\nALTER TABLE hly_usercenter.xxx ADD COLUMN b INT", "hly_accesscard", False, "hly_usercenter"),
]


def main():
    print("=== W3 cross_db_check 单元测试 (134 dev) ===\n")
    passed = 0
    failed = 0
    for name, sql, db_name, expected_ok, expected_substr in CASES:
        result = check_cross_db(sql, None, db_name)
        actual_ok = result["ok"]
        actual_error = result.get("error", "")
        ok_match = (actual_ok == expected_ok)
        # error substring check
        if expected_substr and actual_error:
            substr_match = expected_substr in actual_error
        elif expected_substr:
            substr_match = False  # 期望有错误但实际没错误
        else:
            substr_match = True  # 不期望错误
        if ok_match and substr_match:
            print(f"  ✓ {name}: ok={actual_ok}, expected={expected_ok}")
            passed += 1
        else:
            print(f"  ✗ {name}: ok={actual_ok} (expected={expected_ok}), error={actual_error[:80]!r}")
            failed += 1
    print(f"\n=== 总结: {passed} passed, {failed} failed ===")
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)