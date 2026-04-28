"""Safety guardrails for Lobuddy tool execution."""

import ipaddress
import logging
import os
import re
import socket
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger("lobuddy.guardrails")


class SafetyGuardrails:
    """Enforces safety rules on Lobuddy tool execution."""

    # Common user directories that should be accessible
    EXTRA_ALLOWED_DIRS: list[Path] = []
    """Enforces safety rules on Lobuddy tool execution."""

    # Common user directories that should be accessible
    EXTRA_ALLOWED_DIRS: list[Path] = []

    def __init__(self, workspace_path: Path):
        self.workspace_path = workspace_path.resolve()
        home = Path.home()
        self.EXTRA_ALLOWED_DIRS = [
            home / "Desktop",
            home / "OneDrive" / "Desktop",
            home / "Downloads",
            home / "Documents",
            home / "Pictures",
            home / "Videos",
            home / "Music",
        ]
        project_root = Path(__file__).resolve().parent.parent.parent
        skills_dir = project_root / "lib" / "nanobot" / "nanobot" / "skills"
        if skills_dir.exists():
            self.EXTRA_ALLOWED_DIRS.append(skills_dir.resolve())
        lib_nanobot = project_root / "lib" / "nanobot"
        if lib_nanobot.exists():
            self.EXTRA_ALLOWED_DIRS.append(lib_nanobot.resolve())
        self.EXTRA_ALLOWED_DIRS = [d for d in self.EXTRA_ALLOWED_DIRS if d.exists()]

    def _is_under_any(self, path: Path, directories: list[Path]) -> bool:
        """Check if a path is under any of the given directories."""
        for directory in directories:
            try:
                path.relative_to(directory.resolve())
                return True
            except ValueError:
                continue
        return False

    def validate_path(self, path: str) -> Optional[str]:
        """Validate that a path is within workspace or allowed user directories."""
        """Validate that a path is within workspace or allowed user directories."""
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

            # Check if target is within workspace or extra allowed directories
            allowed_dirs = [self.workspace_path] + self.EXTRA_ALLOWED_DIRS
            if not self._is_under_any(target, allowed_dirs):
            # Check if target is within workspace or extra allowed directories
            allowed_dirs = [self.workspace_path] + self.EXTRA_ALLOWED_DIRS
            if not self._is_under_any(target, allowed_dirs):
                return f"Path {path} is outside workspace"

            # Symlink check: verify symlink target is within allowed directories
            # Symlink check: verify symlink target is within allowed directories
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
                if not self._is_under_any(resolved_link, allowed_dirs):
                if not self._is_under_any(resolved_link, allowed_dirs):
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
