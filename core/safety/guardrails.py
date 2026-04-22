"""Safety guardrails for Lobuddy tool execution."""

import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger("lobuddy.guardrails")


class SafetyGuardrails:
    """Enforces safety rules on tool execution."""

    def __init__(self, workspace_path: Path):
        self.workspace_path = workspace_path.resolve()

    def validate_path(self, path: str) -> Optional[str]:
        """Validate that a path is within workspace."""
        try:
            # Null byte check
            if "\x00" in path:
                return f"Null byte in path blocked: {path}"

            # UNC path check
            if path.startswith("\\\\") or path.startswith("//"):
                return f"UNC path blocked: {path}"

            # ADS check: reject colons not part of drive letter at start
            rest = re.sub(r"^[A-Za-z]:[\\/]", "", path)
            if ":" in rest:
                return f"NTFS ADS or invalid colon in path blocked: {path}"

            # Reject ambiguous Windows drive-relative paths (e.g., C:secret.txt)
            if re.match(r"^[A-Za-z]:[^\\/]", path):
                return f"Ambiguous drive-relative path blocked: {path}"

            # Resolve relative paths against workspace, not CWD
            if not Path(path).is_absolute():
                target = (self.workspace_path / path).resolve()
            else:
                target = Path(path).resolve()

            # Check if target is within workspace
            try:
                target.relative_to(self.workspace_path)
            except ValueError:
                return f"Path {path} is outside workspace"

            # Symlink check: verify symlink target is within workspace
            if Path(path).is_absolute():
                original = Path(path)
            else:
                original = self.workspace_path / path
            if os.path.islink(original):
                link_target = os.readlink(original)
                if os.path.isabs(link_target):
                    resolved_link = Path(link_target).resolve()
                else:
                    resolved_link = (original.parent / link_target).resolve()
                try:
                    resolved_link.relative_to(self.workspace_path)
                except ValueError:
                    return f"Symlink target outside workspace: {path}"

            return None
        except Exception as e:
            return f"Invalid path: {e}"

    def validate_shell_command(self, command: str) -> Optional[str]:
        """Validate shell command safety using allowlist + dangerous pattern checks."""
        from core.tools.tool_policy import ToolPolicy

        policy = ToolPolicy()
        allowed, reason = policy.validate_command(command)
        if not allowed:
            return f"Dangerous command blocked: {reason}"
        return None

    def validate_working_dir(self, working_dir: str) -> Optional[str]:
        """Validate that shell working directory is within workspace."""
        return self.validate_path(working_dir)

    def validate_web_url(self, url: str) -> Optional[str]:
        """Validate web URL safety."""
        from urllib.parse import urlparse
        import ipaddress
        import socket

        try:
            parsed = urlparse(url)
        except Exception:
            return f"Invalid URL format: {url}"

        if parsed.scheme not in {"http", "https"}:
            return f"Blocked URL scheme: {parsed.scheme}"

        if not parsed.hostname:
            return f"URL missing hostname: {url}"

        hostname = parsed.hostname.lower()

        if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return f"Blocked localhost access: {hostname}"

        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
                return f"Blocked private IP address: {hostname}"
        except ValueError:
            pass

        try:
            if parsed.port and parsed.port not in (80, 443):
                return f"Blocked non-standard port: {parsed.port}"
        except ValueError:
            return f"Blocked invalid port in URL: {url}"

        try:
            resolved = socket.getaddrinfo(hostname, None)
            for _, _, _, _, sockaddr in resolved:
                resolved_ip = ipaddress.ip_address(sockaddr[0])
                if (
                    resolved_ip.is_private
                    or resolved_ip.is_loopback
                    or resolved_ip.is_reserved
                    or resolved_ip.is_link_local
                ):
                    return f"Blocked URL resolving to internal address: {hostname}"
        except socket.gaierror:
            return f"Blocked URL: DNS resolution failed for {hostname}"

        return None
