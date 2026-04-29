"""Prompt strings for profile operations."""

PROFILE_UPDATE_PROMPT = """分析以下对话，提取用户相关信息。

**要求**：
1. 只提取稳定、明确的信息
2. 忽略临时性、情绪化的内容
3. 不要包含任何敏感信息（API密钥、密码、邮箱等）

**输出格式**：JSON数组
```json
[
  {
    "section": "section_name",
    "action": "add|update|remove",
    "content": "提取的信息",
    "confidence": 0.0-1.0,
    "reason": "提取原因"
  }
]
```

**有效section**：Basic Notes, Preferences, Work And Projects, Communication Style, Long-Term Goals, Boundaries And Dislikes, Open Questions

**对话内容**：
{conversation}

**当前用户配置**：
{current_profile}"""

PROFILE_INJECTION_HEADER = "## 用户配置信息\n\n"
