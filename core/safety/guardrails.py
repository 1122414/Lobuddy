"""Safety guardrails for Lobuddy tool execution."""

import ipaddress
import logging
import os
import re
import socket
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from core.safety.command_risk import CommandRiskAction, CommandRiskAssessment

logger = logging.getLogger("lobuddy.guardrails")

from core.logging.trace import get_logger
security_log = get_logger("security")


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
                security_log.warning("Path validation — null byte blocked: %s", path[:80])
                return f"Null byte in path blocked: {path}"

            # UNC path check
            if path.startswith("\\\\") or path.startswith("//"):
                security_log.warning("Path validation — UNC blocked: %s", path[:80])
                return f"UNC path blocked: {path}"

            # ADS check: reject colons not part of drive letter at start
            rest = re.sub(r"^[A-Za-z]:[\\/]", "", path)
            if ":" in rest:
                security_log.warning("Path validation — ADS/colon blocked: %s", path[:80])
                return f"NTFS ADS or invalid colon in path blocked: {path}"

            # Reject ambiguous Windows drive-relative paths (e.g., C:secret.txt)
            if re.match(r"^[A-Za-z]:[^\\/]", path):
                security_log.warning("Path validation — drive-relative blocked: %s", path[:80])
                return f"Ambiguous drive-relative path blocked: {path}"

            # Resolve relative paths against workspace, not CWD
            if not Path(path).is_absolute():
                target = (self.workspace_path / path).resolve()
            else:
                target = Path(path).resolve()

            # Check if target is within workspace or extra allowed directories
            allowed_dirs = [self.workspace_path] + self.EXTRA_ALLOWED_DIRS
            if not self._is_under_any(target, allowed_dirs):
                security_log.warning("Path validation — outside workspace: %s", path[:80])
                return f"Path {path} is outside workspace"

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
                    return f"Symlink target outside workspace: {path}"

            return None
        except Exception as e:
            return f"Invalid path: {e}"

    def validate_shell_command(self, command: str) -> Optional[str]:
        """Validate shell command safety using assess_shell_command.

        For backward compatibility, HITL_REQUIRED commands are reported as blocked
        (callers that support HITL should use assess_shell_command() directly).
        """
        assessment = self.assess_shell_command(command)
        if assessment.action == CommandRiskAction.ALLOW:
            return None
        security_log.warning(
            "Shell command blocked — %s: %s", assessment.command_name, assessment.reason
        )
        return f"Dangerous command blocked: {assessment.reason}"

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
            security_log.warning("URL validation — blocked scheme: %s", parsed.scheme)
            return f"Blocked URL scheme: {parsed.scheme}"

        if not parsed.hostname:
            security_log.warning("URL validation — missing hostname: %s", url[:80])
            return f"URL missing hostname: {url}"

        hostname = parsed.hostname.lower()

        if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            security_log.warning("URL validation — localhost blocked: %s", hostname)
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

    def _is_protected_delete_target(self, target: Path) -> bool:
        """Check if a path is a protected target that must never be deleted.

        Protected targets include root directories, drive roots, home root,
        workspace root itself, and extra allowed directory roots.
        """
        resolved = target.resolve()
        # Unix root
        if resolved == Path("/"):
            return True
        # Windows drive roots (e.g., C:\\, D:\\)
        if os.name == "nt":
            resolved_str = str(resolved)
            if len(resolved_str) == 3 and resolved_str[1:3] == ":\\":
                return True
        # Home directory root
        try:
            if resolved == Path.home():
                return True
        except Exception:
            pass
        # Workspace root itself
        try:
            if resolved == self.workspace_path:
                return True
        except Exception:
            pass
        # Extra allowed directory roots
        for extra_dir in self.EXTRA_ALLOWED_DIRS:
            try:
                if resolved == extra_dir.resolve():
                    return True
            except Exception:
                continue
        return False

    def _resolve_path_relative_to_workspace(self, path_str: str) -> Path | None:
        """Resolve a path string against workspace or as absolute.

        Returns None if the path cannot be resolved safely.
        """
        try:
            if not Path(path_str).is_absolute():
                return (self.workspace_path / path_str).resolve()
            return Path(path_str).resolve()
        except Exception:
            return None

    def assess_shell_command(
        self, command: str, working_dir: str = ""
    ) -> CommandRiskAssessment:
        """Assess shell command risk with path-level validation.

        Extends ToolPolicy.assess_command_risk() with:
        - Path validation for HITL_REQUIRED commands
        - Protected target blocking (roots, workspace root, home)
        - Working directory validation
        """
        from core.tools.tool_policy import ToolPolicy

        policy = ToolPolicy()
        assessment = policy.assess_command_risk(command)

        # DENY and ALLOW pass through unchanged
        if assessment.action != CommandRiskAction.HITL_REQUIRED:
            if assessment.action == CommandRiskAction.DENY:
                security_log.warning(
                    "Shell command DENY — %s: %s", assessment.command_name, assessment.reason
                )
            return assessment

        # HITL_REQUIRED: validate each affected path
        if not assessment.affected_paths:
            # No identifiable paths to validate — deny for safety
            security_log.warning(
                "HITL delete command has no identifiable paths: %s", command[:100]
            )
            return CommandRiskAssessment(
                action=CommandRiskAction.DENY,
                command=command,
                normalized_command=assessment.normalized_command,
                command_name=assessment.command_name,
                reason="Delete command with no identifiable target paths blocked",
                affected_paths=assessment.affected_paths,
                risk_tags=assessment.risk_tags + ("no_paths",),
            )

        validated_paths: list[str] = []
        for path_str in assessment.affected_paths:
            # Block wildcard paths
            if any(c in path_str for c in "*?[]"):
                security_log.warning(
                    "HITL delete command blocked — wildcard path: %s", path_str
                )
                return CommandRiskAssessment(
                    action=CommandRiskAction.DENY,
                    command=command,
                    normalized_command=assessment.normalized_command,
                    command_name=assessment.command_name,
                    reason=f"Wildcard path in delete command blocked: {path_str}",
                    affected_paths=assessment.affected_paths,
                    risk_tags=assessment.risk_tags + ("wildcard",),
                )

            # Validate path is within allowed directories
            path_error = self.validate_path(path_str)
            if path_error:
                security_log.warning(
                    "HITL delete command blocked — path validation failed: %s", path_error
                )
                return CommandRiskAssessment(
                    action=CommandRiskAction.DENY,
                    command=command,
                    normalized_command=assessment.normalized_command,
                    command_name=assessment.command_name,
                    reason=f"Path outside workspace: {path_str}",
                    affected_paths=assessment.affected_paths,
                    risk_tags=assessment.risk_tags + ("outside_workspace",),
                )

            # Resolve and check protected targets
            resolved = self._resolve_path_relative_to_workspace(path_str)
            if resolved is None:
                return CommandRiskAssessment(
                    action=CommandRiskAction.DENY,
                    command=command,
                    normalized_command=assessment.normalized_command,
                    command_name=assessment.command_name,
                    reason=f"Cannot resolve path: {path_str}",
                    affected_paths=assessment.affected_paths,
                    risk_tags=assessment.risk_tags + ("unresolvable",),
                )
            if self._is_protected_delete_target(resolved):
                security_log.warning(
                    "HITL delete command blocked — protected target: %s", resolved
                )
                return CommandRiskAssessment(
                    action=CommandRiskAction.DENY,
                    command=command,
                    normalized_command=assessment.normalized_command,
                    command_name=assessment.command_name,
                    reason=f"Protected target blocked: {resolved}",
                    affected_paths=assessment.affected_paths,
                    risk_tags=assessment.risk_tags + ("protected_target",),
                )

            validated_paths.append(path_str)

        # Validate working directory if provided
        if working_dir:
            wd_error = self.validate_working_dir(working_dir)
            if wd_error:
                security_log.warning(
                    "HITL delete command blocked — working_dir outside workspace: %s", wd_error
                )
                return CommandRiskAssessment(
                    action=CommandRiskAction.DENY,
                    command=command,
                    normalized_command=assessment.normalized_command,
                    command_name=assessment.command_name,
                    reason=f"Working directory outside workspace: {working_dir}",
                    affected_paths=assessment.affected_paths,
                    risk_tags=assessment.risk_tags + ("bad_working_dir",),
                )

        # All paths validated — HITL_REQUIRED confirmed
        return CommandRiskAssessment(
            action=CommandRiskAction.HITL_REQUIRED,
            command=command,
            normalized_command=assessment.normalized_command,
            command_name=assessment.command_name,
            reason=assessment.reason,
            affected_paths=tuple(validated_paths),
            risk_tags=assessment.risk_tags,
        )
