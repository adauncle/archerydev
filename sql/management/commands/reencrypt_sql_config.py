# -*- coding: UTF-8 -*-
"""
一次性 management command：把 sql_config 表里所有 v1.10.0 导入的明文 value
用当前 SECRET_KEY 重新加密。

触发场景：
  1. Navicat 全量导入 v1.10.0 库到 v1.14.0 库
  2. v1.10.0 的 Config.value 是 plain CharField
  3. v1.14.0 的 Config.value 是 EncryptedCharField
  4. ORM from_db_value 尝试解密明文失败 → auth.py int() 报 500

用法：
  python manage.py reencrypt_sql_config
  python manage.py reencrypt_sql_config --dry-run    # 只看不解

设计：raw SQL 拿原值（绕开 ORM），再用 mirage cipher 加密，UPDATE 写回
"""
import base64
import logging

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils.encoding import force_bytes

from mirage.crypto import Crypto

logger = logging.getLogger("default")


def _derive_mirage_key():
    """
    跟 mirage.crypto.Crypto.__init__ 保持一致：

      key = base64.urlsafe_b64encode(SECRET_KEY.encode())[:32]

    不要用 SECRET_KEY[:32]，会跟 mirage 内部用错导致加解密 key 不一致。
    """
    raw = getattr(settings, "MIRAGE_SECRET_KEY", None) or settings.SECRET_KEY
    return base64.urlsafe_b64encode(force_bytes(raw))[:32]


class Command(BaseCommand):
    help = "把 sql_config 表里所有 value 用当前 SECRET_KEY 重新加密（用于 Navicat 从 v1.10.0 导入数据后修复）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="只读取+解密模拟，不 UPDATE",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)

        # 拿 cipher（用 mirage 自己的 key 派生方式）
        key = _derive_mirage_key()
        cipher = Crypto(key=key)
        self.stdout.write(
            f"使用 mirage key（前 16 hex）: {key.hex()[:16]}...  (len={len(key)} bytes)"
        )

        # raw SQL 拿明文（绕开 ORM 的 from_db_value 自动解密）
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, item, value FROM sql_config ORDER BY id")
            rows = cursor.fetchall()

        self.stdout.write(f"读取 {len(rows)} 条 sql_config 记录")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY-RUN 模式：只打印前 5 条 + 验证 round-trip，不 UPDATE"))
            for row_id, item, plain in rows[:5]:
                try:
                    dec = cipher.decrypt(plain)
                    round_ok = "✓" if dec != plain else "(idempotent)"
                except Exception as e:
                    round_ok = f"✗({e})"
                self.stdout.write(
                    f"  id={row_id} item={item!r:35s} value={plain!r:50s}  decrypt={round_ok}"
                )
            return

        # UPDATE 加密
        updated = 0
        skipped = 0
        failed = 0
        for row_id, item, plain in rows:
            if not plain:
                skipped += 1
                continue
            try:
                encrypted = cipher.encrypt(plain)
                # 验证 round-trip：解出来应该等于 plain
                dec = cipher.decrypt(encrypted)
                if dec != plain:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  id={row_id} item={item!r:35s} round-trip 不一致：enc≠dec，跳过"
                        )
                    )
                    failed += 1
                    continue
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  id={row_id} item={item!r} 加密失败: {e}"))
                failed += 1
                continue
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE sql_config SET value = %s WHERE id = %s",
                    [encrypted, row_id],
                )
            updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"完成：加密 {updated} 条，跳过空值 {skipped} 条，round-trip 失败 {failed} 条，总 {len(rows)} 条"
            )
        )
        self.stdout.write("重启 gunicorn 让 ORM 重新加载：")
        self.stdout.write("  systemctl restart archery-prod-gunicorn.service")
