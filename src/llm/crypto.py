"""API Key 加解密工具。

使用 ``LLM_PROVIDER_ENCRYPTION_KEY`` 环境变量作为主密钥，
对供应商 ``api_key_encrypted`` 字段进行 AES-256-GCM 加解密。

安全要求：
    - 密钥从环境变量读取，禁止硬编码（红线 #5）。
    - 日志中禁止输出明文 API Key（红线 #10）。
    - 加密算法使用 Fernet（对称加密，内置完整性校验）。
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import threading

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_ENV_KEY = "LLM_PROVIDER_ENCRYPTION_KEY"

_fernet_lock = threading.Lock()
_fernet_instance: Fernet | None = None
_fernet_passphrase: str | None = None


def _get_fernet() -> Fernet:
    """从环境变量读取主密钥并构造 Fernet 实例（模块级缓存）。

    环境变量 ``LLM_PROVIDER_ENCRYPTION_KEY`` 为任意长度的 passphrase，
    通过 SHA-256 派生为 32 字节 Fernet 密钥。

    首次调用时构造并缓存，后续调用直接返回缓存实例。
    若环境变量发生变化（如测试中切换 passphrase），自动重建。

    Returns:
        Fernet 实例。

    Raises:
        RuntimeError: 环境变量未设置。
    """
    global _fernet_instance, _fernet_passphrase

    passphrase = os.environ.get(_ENV_KEY)
    if not passphrase:
        raise RuntimeError(
            f"环境变量 {_ENV_KEY} 未设置，无法加解密 API Key。"
            f"请在 .env 中配置该变量。"
        )

    if _fernet_instance is not None and _fernet_passphrase == passphrase:
        return _fernet_instance

    with _fernet_lock:
        # Double-check after acquiring lock
        if _fernet_instance is not None and _fernet_passphrase == passphrase:
            return _fernet_instance

        key = base64.urlsafe_b64encode(
            hashlib.sha256(passphrase.encode()).digest()
        )
        _fernet_instance = Fernet(key)
        _fernet_passphrase = passphrase
        return _fernet_instance


def reset_fernet_cache() -> None:
    """清除缓存的 Fernet 实例（主要用于测试）。

    当环境变量 ``LLM_PROVIDER_ENCRYPTION_KEY`` 被修改后，
    调用此函数强制下次 ``_get_fernet()`` 重建实例。
    """
    global _fernet_instance, _fernet_passphrase
    with _fernet_lock:
        _fernet_instance = None
        _fernet_passphrase = None


def encrypt(plaintext: str) -> str:
    """加密明文 API Key。

    Args:
        plaintext: 明文 API Key。

    Returns:
        Fernet 加密后的字符串（base64 编码，含时间戳和 HMAC）。
    """
    f = _get_fernet()
    encrypted: str = f.encrypt(plaintext.encode()).decode()
    return encrypted


def decrypt(ciphertext: str) -> str:
    """解密 API Key。

    Args:
        ciphertext: ``encrypt()`` 返回的加密字符串。

    Returns:
        明文 API Key。

    Raises:
        ValueError: 解密失败（密钥不匹配或数据损坏）。
    """
    f = _get_fernet()
    try:
        plaintext: str = f.decrypt(ciphertext.encode()).decode()
        return plaintext
    except InvalidToken as exc:
        raise ValueError("API Key 解密失败，请检查 LLM_PROVIDER_ENCRYPTION_KEY") from exc
