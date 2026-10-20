"""Credential migration with read-back verification before removing legacy copies."""

from __future__ import annotations

import hashlib
import io
import os
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from dotenv.parser import parse_stream

from core.storage.crypto import decrypt_sensitive, is_encrypted
from core.storage.db import Database
from core.storage.keychain import KeychainError, MacKeychain

if TYPE_CHECKING:
    from core.config import Settings

SECRET_FIELDS = ("llm_api_key", "llm_multimodal_api_key", "fish_api_key", "typesafe_api_key")


class SecretStore(Protocol):
    def get(self, account: str) -> str | None: ...
    def set(self, account: str, secret: str) -> None: ...


def migrate_credentials(db: Database, env_file: Path | None, store: SecretStore) -> int:
    original = env_file.read_text(encoding="utf-8") if env_file and env_file.exists() else ""
    bindings = list(parse_stream(io.StringIO(original)))
    environment = {binding.key.lower(): binding.value for binding in bindings if binding.key}
    with db.get_connection() as conn:
        rows = {
            row["key"]: row["value"]
            for row in conn.execute("SELECT key,value FROM app_settings")
            if row["key"] in SECRET_FIELDS
        }
    credentials: dict[str, str] = {}
    for field in SECRET_FIELDS:
        value = environment.get(field) or rows.get(field)
        if value:
            if value.startswith("enc:v1:"):
                if not is_encrypted(value):
                    raise KeychainError("旧凭据无法解密，未删除原数据")
                value = decrypt_sensitive(value)
            credentials[field] = value
    for field, value in credentials.items():
        store.set(field, value)
        if store.get(field) != value:
            raise KeychainError("钥匙串校验失败，未删除原凭据")
    # Do not remove a concurrently edited .env. Keychain values can be safely retried.
    if env_file and env_file.exists():
        current = env_file.read_text(encoding="utf-8")
        if hashlib.sha256(current.encode()).digest() != hashlib.sha256(original.encode()).digest():
            raise KeychainError("凭据文件在迁移时被修改，已保留文件，请重试")
        filtered = "".join(
            binding.original.string
            for binding in bindings
            if not binding.key or binding.key.lower() not in SECRET_FIELDS
        )
        if filtered != original:
            descriptor, temporary = tempfile.mkstemp(prefix=".credentials-", dir=env_file.parent)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    stream.write(filtered)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, env_file)
            finally:
                Path(temporary).unlink(missing_ok=True)
    with db.transaction() as conn:
        for field in credentials:
            conn.execute("DELETE FROM app_settings WHERE key=?", (field,))
    return len(credentials)


def read_credentials(store: SecretStore | None = None) -> dict[str, str]:
    keychain = store or MacKeychain()
    return {field: value for field in SECRET_FIELDS if (value := keychain.get(field))}


def load_settings() -> Settings:
    """Read configured credentials in memory; migration/removal is an explicit upgrade step."""
    from dotenv import dotenv_values

    from core.config import Settings

    environment = dotenv_values(Path.cwd() / ".env")
    values = {
        field: os.environ.get(field.upper()) or environment.get(field.upper()) or ""
        for field in SECRET_FIELDS
    }
    # Each credential has independent precedence; configuring LLM via env must not hide Fish.
    if not all(values.values()) and (sys.platform == "darwin" or not values["llm_api_key"]):
        for field, secret in read_credentials().items():
            if not values[field]:
                values[field] = secret
    return Settings(
        llm_api_key=values["llm_api_key"],
        llm_multimodal_api_key=values["llm_multimodal_api_key"],
        fish_api_key=values["fish_api_key"],
        typesafe_api_key=values["typesafe_api_key"],
    )
