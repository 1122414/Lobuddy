"""Tool policy definitions for Lobuddy."""

import re
import shlex
from typing import Optional


class ToolPolicy:
    """Defines which tools are enabled and under what conditions."""

    ALLOWED_COMMANDS = {
        # POSIX / Linux / macOS
        "ls", "cat", "grep", "find", "head", "tail", "wc",
        "pwd", "echo", "mkdir", "touch", "cp", "mv", "rm",
        "git", "python", "python3", "pip", "node", "npm",
        "dir", "help", "info", "clear", "cls",
        # Network utilities (needed by skills e.g. weather)
        "curl", "wget",
        # Windows system commands
        "start", "explorer", "cmd", "powershell", "pwsh",
        "taskkill", "tasklist", "where",
        # Cross-platform utilities
        "open", "xdg-open", "which",
        # Common Windows builtins
        "ping", "tracert", "ipconfig", "systeminfo",
        # File management
        "ren", "del", "copy", "xcopy", "robocopy",
        # System control (safe ones)
        "shutdown", "reboot", "poweroff",
    }

    CHAINING_OPERATORS = {"&&", "||", ";", "|", "&", "`", "$()", ">>", ">", "<", "(", ")"}

    BLOCKED_COMMANDS = {
        "invoke-expression", "iex",
        "format", "shutdown", "reboot", "mkfs",
        "rd", "rmdir",
        "pushd", "popd",
    }

    # Pre-tokenization pattern: detect shell chaining/redirect operators
    # outside of quotes. Matches operators preceded/followed by whitespace
    # or string boundaries.
    _CHAINING_PATTERN = re.compile(
        r'(?:^|\s)'
        r'(;|&&|\|\||\||&|\$\(|>>|>|<|\(|\))'
        r'(?:\s|$)'
    )

    def _has_shell_syntax(self, tokens: list[str]) -> bool:
        for tok in tokens:
            stripped = self._strip_quotes(tok)
            if stripped.startswith(("-", "/")):
                return True
            if "/" in tok or "\\" in tok:
                return True
            if "$" in tok or "`" in tok:
                return True
        return False

    def __init__(self, shell_enabled: bool = False):
        self.shell_enabled = shell_enabled

    def is_tool_allowed(self, tool_name: str) -> bool:
        if tool_name in {"exec", "shell"}:
            return self.shell_enabled
        return True

    def _tokenize_command(self, command: str) -> list[str]:
        """Tokenize a command using shlex for structured parsing."""
        try:
            return shlex.split(command, posix=False)
        except ValueError:
            return command.split()

    def _has_chaining(self, tokens: list[str]) -> bool:
        """Check for command chaining operators in token stream.

        Detects both standalone operators and operators fused with adjacent
        words by shlex (e.g. 'safe;').
        """
        for tok in tokens:
            if tok in self.CHAINING_OPERATORS:
                return True
            stripped = self._strip_quotes(tok)
            for op in self.CHAINING_OPERATORS:
                if op in stripped:
                    return True
        return False

    def _validate_allowed_command(self, cmd: str, tokens: list[str]) -> tuple[bool, Optional[str]]:
        """Validate a command against structured per-command rules.

        Returns (is_valid, reason) where is_valid=True means allowed.
        """
        if cmd in ("rm", "del"):
            has_r = False
            has_f = False
            has_s = False
            has_q = False
            for raw_tok in tokens[1:]:
                tok = self._strip_quotes(raw_tok)
                if tok == "--":
                    break
                if cmd == "rm" and tok.startswith("-") and not tok.startswith("--"):
                    opts = tok[1:]
                    if "r" in opts or "R" in opts:
                        has_r = True
                    if "f" in opts or "F" in opts:
                        has_f = True
                elif cmd == "rm" and tok.startswith("--"):
                    tok_lower = tok.lower()
                    if tok_lower == "--recursive":
                        has_r = True
                    elif tok_lower == "--force":
                        has_f = True
                elif cmd == "del" and tok.startswith("/"):
                    opts = tok[1:].lower()
                    if "s" in opts:
                        has_s = True
                    if "q" in opts:
                        has_q = True
                    if "f" in opts:
                        has_f = True
            # rm -rf or del /s /q or del /f are dangerous
            if (cmd == "rm" and has_r and has_f) or (cmd == "del" and (has_s or has_q or has_f)):
                return False, f"{cmd} with dangerous flags is blocked"
            return True, None

        if cmd == "git":
            if self._has_cwd_escape_args_from_tokens(tokens):
                return False, "git command contains blocked arguments"
            return True, None

        # Interpreters: reject inline code execution flags
        interpreter_flags = {
            "python": {"-c"},
            "python3": {"-c"},
            "node": {"-e", "--eval", "-p", "--print"},
            "powershell": {"-enc", "-encodedcommand", "-encoded"},
            "pwsh": {"-enc", "-encodedcommand", "-encoded"},
        }
        flags = interpreter_flags.get(cmd)
        if flags:
            reason = f"{cmd} inline execution flag detected"
            for tok in tokens[1:]:
                stripped = self._strip_quotes(tok)
                if stripped.startswith("-") and not stripped.startswith("--") and len(stripped) > 2:
                    cluster = stripped[1:]
                    for f in flags:
                        if f.startswith("-") and len(f) == 2 and f[1] in cluster:
                            return False, reason
                if stripped in flags:
                    return False, reason
                for f in flags:
                    if f.startswith("--") and stripped.startswith(f):
                        return False, reason

        return True, None

    def is_command_dangerous(self, command: str) -> bool:
        """Structured whitelist validation: tokenize, check allowlist, validate per-command."""
        if "\n" in command or "\r" in command:
            return True

        # Block known dangerous patterns that bypass structured parsing
        if ":(){ :|:& };:" in command:
            return True

        # Pre-tokenization: detect shell chaining/redirect operators that
        # shlex (posix=False) may fuse with adjacent words (e.g. "safe;").
        if self._CHAINING_PATTERN.search(command):
            return True

        tokens = self._tokenize_command(command)
        if not tokens:
            return True

        if self._has_chaining(tokens):
            return True

        # Normalize base command (strip quotes, .exe suffix, and function-call suffix)
        cmd = tokens[0].strip('"\'').lower()
        if cmd.endswith(".exe"):
            cmd = cmd[:-4]
        # Extract command name before any function-call parenthesis
        paren_idx = cmd.find("(")
        if paren_idx != -1:
            cmd = cmd[:paren_idx]

        # Block explicitly dangerous standalone commands
        if cmd in self.BLOCKED_COMMANDS:
            return True

        # Single-word inputs that are not known dangerous commands are benign
        if len(tokens) == 1:
            return False

        # Multi-word text without shell syntax is likely benign prose, not a command
        if not self._has_shell_syntax(tokens):
            return False

        # Whitelist: only allow explicitly permitted commands
        if cmd not in self.ALLOWED_COMMANDS:
            return True

        # Per-command structured validation
        valid, _ = self._validate_allowed_command(cmd, tokens)
        return not valid

    def _strip_quotes(self, tok: str) -> str:
        if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in ('"', "'"):
            return tok[1:-1]
        return tok

    _GIT_SAFE_SUBCOMMANDS = {
        "status", "log", "diff", "show", "blame", "grep", "ls-files",
    }
    _GIT_ALLOWED_GLOBAL_OPTS = {
        "--bare", "--no-replace-objects", "--namespace", "--super-prefix",
        "--no-pager", "--paginate",
    }
    # Security contract: blocked options are matched by exact token for short flags,
    # by prefix for long flags (to catch abbreviations), and by cluster decomposition
    # for high-risk short flags that take arguments (currently only -o). Short-flag
    # clusters are decomposed to detect hidden -o; known-safe clusters are allowlisted
    # to prevent over-blocking legitimate options (e.g., -uno).
    _GIT_BLOCKED_SUBCOMMAND_OPTS = {
        "--output", "-o", "--patch", "--open-files-in-pager",
        "--no-index", "--ext-diff",
    }
    # Minimum unique prefixes for long-option abbreviation blocking.
    _GIT_BLOCKED_LONG_PREFIXES = {
        "--out",     # --output
        "--ext",     # --ext-diff
        "--no-in",   # --no-index
        "--open",    # --open-files-in-pager
        "--pat",     # --patch
    }
    # Known-safe short-option clusters that contain 'o' but are NOT -o escapes.
    # When adding entries, verify the cluster is never parsed as containing -o.
    _GIT_SAFE_SHORT_CLUSTERS = {"uno"}  # git status --untracked-files=no
    # Dangerous env vars that can bypass CLI-level git restrictions.
    # Callers must sanitize these before executing git commands.
    _GIT_DANGEROUS_ENV_VARS = {
        "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_PAGER", "GIT_EXTERNAL_DIFF",
        "GIT_DIFF_OPTS", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM",
    }

    def _parse_git_subcommand(self, tokens: list[str]) -> str | None:
        i = 1
        while i < len(tokens):
            tok = self._strip_quotes(tokens[i])
            if tok == "--":
                i += 1
                break
            if tok.startswith("-") and len(tok) > 1 and tok[1] != "-":
                if tok == "-C" or (len(tok) > 2 and tok[1] == "C"):
                    return None
                if tok.startswith("-c"):
                    return None
                i += 1
                continue
            if tok.startswith("--"):
                tok_lower = tok.lower()
                eq_idx = tok.find("=")
                opt_name = tok_lower[:eq_idx] if eq_idx != -1 else tok_lower
                if opt_name not in self._GIT_ALLOWED_GLOBAL_OPTS:
                    return None
                if eq_idx == -1 and opt_name in {"--namespace", "--super-prefix"}:
                    i += 2
                else:
                    i += 1
                continue
            break
        if i < len(tokens):
            return self._strip_quotes(tokens[i]).lower()
        return None

    def _has_cwd_escape_args(self, command: str) -> bool:
        tokens = self._tokenize_command(command)
        return self._has_cwd_escape_args_from_tokens(tokens)

    def _has_cwd_escape_args_from_tokens(self, tokens: list[str]) -> bool:
        if not tokens:
            return False
        cmd_base = tokens[0].strip('"\'').lower()
        if cmd_base.endswith(".exe"):
            cmd_base = cmd_base[:-4]
        if cmd_base != "git":
            return False
        subcommand = self._parse_git_subcommand(tokens)
        if subcommand is None:
            return True
        if subcommand not in self._GIT_SAFE_SUBCOMMANDS:
            return True
        for raw_tok in tokens:
            tok = self._strip_quotes(raw_tok).lower()
            # Exact short-flag match (e.g., -o) + attached-arg forms (e.g., -o../../x)
            for blocked in self._GIT_BLOCKED_SUBCOMMAND_OPTS:
                if tok == blocked:
                    return True
                if blocked.startswith("-") and not blocked.startswith("--"):
                    if tok.startswith(blocked) and len(tok) > len(blocked):
                        return True
            # Block short-option clusters (len>2) to prevent hidden -o bypasses
            # like -po../../x. Users should use separate flags (e.g., -p -o file).
            if tok.startswith("-") and not tok.startswith("--") and len(tok) > 2:
                cluster = tok[1:]
                if cluster not in self._GIT_SAFE_SHORT_CLUSTERS:
                    return True
            # Long-flag prefix match to catch abbreviations (e.g., --out for --output)
            for prefix in self._GIT_BLOCKED_LONG_PREFIXES:
                if tok.startswith(prefix):
                    return True
        return False

    def validate_command(self, command: str) -> tuple[bool, Optional[str]]:
        if not command or not command.strip():
            return False, "Empty command"

        if self.is_command_dangerous(command):
            return False, "Command matches dangerous pattern"

        cmd_base = command.strip().split()[0].lower()
        cmd_base = cmd_base.strip('"\'')
        if cmd_base.endswith(".exe"):
            cmd_base = cmd_base[:-4]
        if cmd_base not in self.ALLOWED_COMMANDS:
            return False, f"Command not in allowlist: {cmd_base}"

        if self._has_cwd_escape_args(command):
            return False, "Command contains working-directory escape arguments"

        return True, None
