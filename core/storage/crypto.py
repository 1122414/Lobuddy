import base64
import hashlib
import os
import platform


def _derive_key():
    try:
        user = os.getlogin()
    except Exception:
        user = os.environ.get("USER", os.environ.get("USERNAME", "default"))
    node = platform.node() or "default"
    seed = f"{user}@{node}:lobuddy_v1".encode("utf-8")
    return hashlib.sha256(seed).digest()


_ENC_PREFIX = "enc:v1:"


def _try_decrypt(payload):
    try:
        key = _derive_key()
        data = base64.b64decode(payload.encode("ascii"))
        decrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
        return decrypted.decode("utf-8")
    except Exception:
        return None


def encrypt_sensitive(plaintext):
    if not plaintext:
        return ""
    if plaintext.startswith(_ENC_PREFIX):
        payload = plaintext[len(_ENC_PREFIX):]
        if _try_decrypt(payload) is not None:
            return plaintext
    key = _derive_key()
    data = plaintext.encode("utf-8")
    encrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    payload = base64.b64encode(encrypted).decode("ascii")
    return _ENC_PREFIX + payload


def decrypt_sensitive(ciphertext):
    if not ciphertext:
        return ""
    if ciphertext.startswith(_ENC_PREFIX):
        payload = ciphertext[len(_ENC_PREFIX):]
        result = _try_decrypt(payload)
        if result is not None:
            return result
    return ciphertext


def is_encrypted(value):
    if not value:
        return False
    if value.startswith(_ENC_PREFIX):
        return _try_decrypt(value[len(_ENC_PREFIX):]) is not None
    return False
