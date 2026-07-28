"""src.llm.crypto 的单元测试。

测试覆盖：
- encrypt / decrypt 往返
- decrypt 无效密文抛 ValueError
- _get_fernet 未设置环境变量抛 RuntimeError
- 不同 passphrase 加密结果不同
"""

from __future__ import annotations

import pytest

from src.llm.crypto import decrypt, encrypt


class TestEncryptDecrypt:
    """encrypt / decrypt 往返测试。"""

    def test_roundtrip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """加密后解密恢复原文。"""
        monkeypatch.setenv("LLM_PROVIDER_ENCRYPTION_KEY", "test-passphrase")
        plaintext = "sk-abc123xyz"
        encrypted = encrypt(plaintext)
        assert encrypted != plaintext
        assert decrypt(encrypted) == plaintext

    def test_different_plaintexts_different_ciphertexts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """不同明文加密结果不同。"""
        monkeypatch.setenv("LLM_PROVIDER_ENCRYPTION_KEY", "test-passphrase")
        enc1 = encrypt("key1")
        enc2 = encrypt("key2")
        assert enc1 != enc2

    def test_same_plaintext_different_ciphertexts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """相同明文每次加密结果不同（Fernet 含随机 IV/时间戳）。"""
        monkeypatch.setenv("LLM_PROVIDER_ENCRYPTION_KEY", "test-passphrase")
        enc1 = encrypt("same-key")
        enc2 = encrypt("same-key")
        assert enc1 != enc2
        # 但都能解密为同一明文
        assert decrypt(enc1) == "same-key"
        assert decrypt(enc2) == "same-key"

    def test_different_passphrase_decrypt_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """用不同 passphrase 解密失败。"""
        monkeypatch.setenv("LLM_PROVIDER_ENCRYPTION_KEY", "passphrase1")
        encrypted = encrypt("secret")

        monkeypatch.setenv("LLM_PROVIDER_ENCRYPTION_KEY", "passphrase2")
        with pytest.raises(ValueError, match="解密失败"):
            decrypt(encrypted)

    def test_decrypt_invalid_data(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """解密无效数据抛 ValueError。"""
        monkeypatch.setenv("LLM_PROVIDER_ENCRYPTION_KEY", "test-passphrase")
        with pytest.raises(ValueError, match="解密失败"):
            decrypt("not-a-valid-fernet-token")

    def test_encrypt_empty_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """空字符串也能加密解密。"""
        monkeypatch.setenv("LLM_PROVIDER_ENCRYPTION_KEY", "test-passphrase")
        encrypted = encrypt("")
        assert decrypt(encrypted) == ""


class TestGetFernet:
    """_get_fernet 环境变量检查测试。"""

    def test_missing_env_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """环境变量未设置抛 RuntimeError。"""
        monkeypatch.delenv("LLM_PROVIDER_ENCRYPTION_KEY", raising=False)
        with pytest.raises(RuntimeError, match="LLM_PROVIDER_ENCRYPTION_KEY"):
            encrypt("test")

    def test_empty_env_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """环境变量为空字符串抛 RuntimeError。"""
        monkeypatch.setenv("LLM_PROVIDER_ENCRYPTION_KEY", "")
        with pytest.raises(RuntimeError, match="LLM_PROVIDER_ENCRYPTION_KEY"):
            encrypt("test")
