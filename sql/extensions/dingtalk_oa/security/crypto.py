"""钉钉 OA 回调加密/解密 + 签名校验。

设计参考：docs/designs/2026-07-20_dingtalk-oa-workflow.md v0.7 §10.5.1

钉钉 OA 回调采用「加密 + 签名」双重保护：
    * 签名 = SHA1( sorted([token, timestamp, nonce, encrypted_body]) )
    * 加密 = AES-256-CBC, IV = aes_key 前 16 字节
    * 密文布局 = random(16B) + msg_len(4B 大端) + msg_json + receiveid
    * 填充 = PKCS7（block_size = 32）

依赖：``pycryptodome==3.19.1``（项目 requirements.txt 已固定）。
"""

import base64
import hashlib
import hmac
import json
import os
import struct
from typing import Union

from Crypto.Cipher import AES


class DingtalkCrypto:
    """钉钉 OA 回调加密/解密 + 签名校验。

    Args:
        token: 钉钉后台「事件订阅」生成的 Token 字符串。
        aes_key: 43 字符 base64（不含 ``=``），钉钉后台生成。
            解码后是 32 字节，作为 AES-256 key + IV（前 16 字节）。
        receiveid: 钉钉后台配置的企业 corp_id / receive_id，用于
            校验密文尾部、加密回包尾部。空字符串表示跳过此校验。
    """

    BLOCK_SIZE = 32

    def __init__(self, token: str, aes_key: str, receiveid: str = ""):
        if not token:
            raise ValueError("token is required")
        if not aes_key or len(aes_key) != 43:
            raise ValueError("aes_key must be 43 chars (base64 without padding)")
        self.token = token
        self.receiveid = receiveid or ""
        # base64 解码：43 字符 base64 + 补 "=" -> 32 字节
        try:
            self.aes_key = base64.b64decode(aes_key + "=")
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"aes_key base64 decode failed: {e}") from e
        if len(self.aes_key) != 32:
            raise ValueError(
                f"aes_key decoded length must be 32 bytes, got {len(self.aes_key)}"
            )

    # ============================== 签名 ==============================

    def verify_signature(
        self, timestamp: str, nonce: str, encrypted_b64: str, signature: str
    ) -> bool:
        """校验 URL 参数 ``signature``。

        钉钉 v2 签名规则：
            1) 把 token、timestamp、nonce、encrypted_body 排序
            2) 拼接后 SHA1（hex）
            3) 与 URL 参数 ``signature`` 比较
        """
        if not signature:
            return False
        params = sorted([self.token, str(timestamp), str(nonce), str(encrypted_b64)])
        expected = hashlib.sha1("".join(params).encode("utf-8")).hexdigest()
        # 用 hmac.compare_digest 防止时序攻击
        return hmac.compare_digest(expected, str(signature))

    # ============================== 解密 ==============================

    def decrypt(self, encrypted_b64: str) -> dict:
        """AES-256-CBC 解密 + 解析 JSON。

        Raises:
            ValueError: 密文长度异常、``receiveid`` 不匹配、msg_len 越界。
            json.JSONDecodeError: 解密后非 JSON。
        """
        if not encrypted_b64:
            raise ValueError("encrypted body is empty")
        try:
            ciphertext = base64.b64decode(encrypted_b64)
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"base64 decode failed: {e}") from e
        if len(ciphertext) < 32:
            raise ValueError(
                f"ciphertext too short: {len(ciphertext)} bytes (min 32)"
            )

        # IV = aes_key 前 16 字节
        iv = self.aes_key[:16]
        cipher = AES.new(self.aes_key, AES.MODE_CBC, iv)
        plain = cipher.decrypt(ciphertext)

        # 跳过前 16 字节 random
        plain = plain[16:]

        # 防御：msg_len 必须为非负且不超过剩余字节数
        if len(plain) < 4:
            raise ValueError("plaintext header too short")
        msg_len = struct.unpack(">I", plain[:4])[0]
        if msg_len <= 0 or msg_len > len(plain) - 4:
            raise ValueError(f"msg_len out of range: {msg_len}")

        msg = plain[4 : 4 + msg_len]
        # 尾部 receiveid 校验
        if self.receiveid:
            tail = plain[4 + msg_len : 4 + msg_len + len(self.receiveid)]
            expected = (
                self.receiveid.encode("utf-8")
                if isinstance(self.receiveid, str)
                else self.receiveid
            )
            if tail != expected:
                raise ValueError("receiveid mismatch")
        return json.loads(msg.decode("utf-8"))

    # ============================== 加密（回包用） ==============================

    def encrypt(self, msg: Union[dict, str]) -> str:
        """AES-256-CBC 加密回包用。

        Args:
            msg: dict（自动 ``json.dumps``）或 str（UTF-8 编码）。

        Returns:
            base64 字符串。
        """
        if isinstance(msg, dict):
            msg_bytes = json.dumps(msg, ensure_ascii=False).encode("utf-8")
        elif isinstance(msg, str):
            msg_bytes = msg.encode("utf-8")
        else:
            raise TypeError(f"msg must be dict or str, got {type(msg).__name__}")

        msg_len = struct.pack(">I", len(msg_bytes))
        random_bytes = os.urandom(16)
        plain = (
            random_bytes
            + msg_len
            + msg_bytes
            + self.receiveid.encode("utf-8")
        )
        # PKCS7 padding
        pad = self.BLOCK_SIZE - len(plain) % self.BLOCK_SIZE
        plain += bytes([pad] * pad)

        iv = self.aes_key[:16]
        cipher = AES.new(self.aes_key, AES.MODE_CBC, iv)
        return base64.b64encode(cipher.encrypt(plain)).decode("utf-8")
