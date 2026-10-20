"""macOS generic-password storage through Security.framework, without shell arguments."""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Iterator
from contextlib import contextmanager


class KeychainError(RuntimeError):
    pass


class MacKeychain:
    def __init__(self, service: str = "com.lobuddy.desktop") -> None:
        if sys.platform != "darwin":
            raise KeychainError("当前平台尚未配置安全凭据存储")
        self.service = service
        self.cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        self.security = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
        pointer = ctypes.c_void_p
        signatures = {
            "CFStringCreateWithCString": ([pointer, ctypes.c_char_p, ctypes.c_uint32], pointer),
            "CFDataCreate": ([pointer, ctypes.c_char_p, ctypes.c_long], pointer),
            "CFDataGetLength": ([pointer], ctypes.c_long),
            "CFDataGetBytePtr": ([pointer], pointer),
            "CFDictionaryCreateMutable": ([pointer, ctypes.c_long, pointer, pointer], pointer),
            "CFDictionarySetValue": ([pointer, pointer, pointer], None),
            "CFRelease": ([pointer], None),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.cf, name)
            function.argtypes = arguments
            function.restype = result
        for name, arguments in {
            "SecItemCopyMatching": [pointer, ctypes.POINTER(pointer)],
            "SecItemAdd": [pointer, ctypes.POINTER(pointer)],
            "SecItemUpdate": [pointer, pointer],
            "SecItemDelete": [pointer],
        }.items():
            function = getattr(self.security, name)
            function.argtypes = arguments
            function.restype = ctypes.c_int32

    def _constant(self, name: str) -> ctypes.c_void_p:
        library = self.cf if name.startswith("kCF") else self.security
        return ctypes.c_void_p.in_dll(library, name)

    @contextmanager
    def _attributes(self, values: dict[str, str | bytes | ctypes.c_void_p]) -> Iterator[int]:
        owned: list[int] = []
        dictionary = self.cf.CFDictionaryCreateMutable(None, 0, None, None)
        if not dictionary:
            raise KeychainError("无法创建系统凭据请求")
        try:
            for key, value in values.items():
                if isinstance(value, str):
                    item = self.cf.CFStringCreateWithCString(
                        None, value.encode("utf-8"), 0x08000100
                    )
                    owned.append(item)
                elif isinstance(value, bytes):
                    item = self.cf.CFDataCreate(None, value, len(value))
                    owned.append(item)
                else:
                    item = value
                if not item:
                    raise KeychainError("无法创建系统凭据属性")
                self.cf.CFDictionarySetValue(dictionary, self._constant(key), item)
            yield dictionary
        finally:
            self.cf.CFRelease(dictionary)
            for item in owned:
                if item:
                    self.cf.CFRelease(item)

    def _query(self, account: str) -> dict[str, str | bytes | ctypes.c_void_p]:
        if not account or len(account) > 200:
            raise ValueError("无效的凭据名称")
        return {
            "kSecClass": self._constant("kSecClassGenericPassword"),
            "kSecAttrService": self.service,
            "kSecAttrAccount": account,
        }

    def get(self, account: str) -> str | None:
        values = self._query(account)
        values["kSecReturnData"] = self._constant("kCFBooleanTrue")
        values["kSecMatchLimit"] = self._constant("kSecMatchLimitOne")
        result = ctypes.c_void_p()
        with self._attributes(values) as query:
            status = self.security.SecItemCopyMatching(query, ctypes.byref(result))
        if status == -25300:
            return None
        if status != 0:
            raise KeychainError(f"无法读取系统钥匙串（状态 {status}），未使用明文回退")
        try:
            return ctypes.string_at(
                self.cf.CFDataGetBytePtr(result), self.cf.CFDataGetLength(result)
            ).decode("utf-8")
        finally:
            self.cf.CFRelease(result)

    def set(self, account: str, secret: str) -> None:
        if not secret or len(secret) > 16000 or "\x00" in secret:
            raise ValueError("凭据为空或格式无效")
        with (
            self._attributes(self._query(account)) as query,
            self._attributes({"kSecValueData": secret.encode("utf-8")}) as update,
        ):
            status = self.security.SecItemUpdate(query, update)
        if status == -25300:
            values = self._query(account)
            values["kSecValueData"] = secret.encode("utf-8")
            with self._attributes(values) as create:
                status = self.security.SecItemAdd(create, None)
        if status != 0:
            raise KeychainError(f"无法写入系统钥匙串（状态 {status}），原凭据保持不变")
        if self.get(account) != secret:
            raise KeychainError("系统钥匙串写入后校验失败，原凭据保持不变")

    def delete(self, account: str) -> None:
        with self._attributes(self._query(account)) as query:
            status = self.security.SecItemDelete(query)
        if status not in (0, -25300):
            raise KeychainError(f"无法删除系统钥匙串项（状态 {status}）")
