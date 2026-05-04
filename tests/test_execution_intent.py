"""5.4 ExecutionIntentRouter tests — validates keyword-based intent routing."""

import pytest
from core.agent.execution_intent import ExecutionIntentRouter, ExecutionIntent, ExecutionRoute


class TestExecutionIntentRouter:
    def test_open_desktop_game_routes_to_local_open_target(self):
        router = ExecutionIntentRouter()
        route = router.route("帮我打开桌面的洛克王国：世界")
        assert route.intent == ExecutionIntent.LOCAL_OPEN_TARGET
        assert route.confidence >= 0.75
        assert "exec" in route.forbidden_tools
        assert "local_app_resolve" in route.preferred_tools
        assert "local_open" in route.preferred_tools
        assert route.target

    def test_open_wechat_routes_to_local_open_target(self):
        router = ExecutionIntentRouter()
        route = router.route("打开微信")
        assert route.intent == ExecutionIntent.LOCAL_OPEN_TARGET

    def test_find_file_routes_to_local_find_file(self):
        router = ExecutionIntentRouter()
        route = router.route("帮我找一下 report.docx")
        assert route.intent == ExecutionIntent.LOCAL_FIND_FILE
        assert "exec" in route.forbidden_tools

    def test_memory_question_routes_to_memory_question(self):
        router = ExecutionIntentRouter()
        route = router.route("我喜欢玩什么游戏？")
        assert route.intent == ExecutionIntent.MEMORY_QUESTION

    def test_general_chat_routes_to_general(self):
        router = ExecutionIntentRouter()
        route = router.route("讲个笑话")
        assert route.intent == ExecutionIntent.GENERAL_CHAT
        assert route.confidence == 0.0

    def test_empty_prompt_returns_general_chat(self):
        router = ExecutionIntentRouter()
        route = router.route("")
        assert route.intent == ExecutionIntent.GENERAL_CHAT
        assert route.confidence == 0.0

    def test_whitespace_only_returns_general_chat(self):
        router = ExecutionIntentRouter()
        route = router.route("   ")
        assert route.intent == ExecutionIntent.GENERAL_CHAT

    def test_should_govern_true_for_local_open_target(self):
        router = ExecutionIntentRouter()
        route = router.route("帮我打开桌面的微信")
        assert route.intent == ExecutionIntent.LOCAL_OPEN_TARGET
        assert router.should_govern(route) is True

    def test_should_govern_false_for_general_chat(self):
        router = ExecutionIntentRouter()
        route = router.route("讲个笑话")
        assert router.should_govern(route) is False

    def test_should_govern_false_low_confidence(self):
        route = ExecutionRoute(
            intent=ExecutionIntent.LOCAL_OPEN_TARGET,
            confidence=0.5,
            requires_tools=True,
            preferred_tools=["local_app_resolve"],
            forbidden_tools=["exec"],
        )
        router = ExecutionIntentRouter()
        assert router.should_govern(route) is False

    def test_is_local_action_returns_true_for_local_intents(self):
        route = ExecutionRoute(intent=ExecutionIntent.LOCAL_OPEN_TARGET)
        assert route.is_local_action is True
        route.intent = ExecutionIntent.LOCAL_FIND_FILE
        assert route.is_local_action is True

    def test_is_local_action_false_for_general_chat(self):
        route = ExecutionRoute(intent=ExecutionIntent.GENERAL_CHAT)
        assert route.is_local_action is False

    def test_target_extraction_for_quoted_name(self):
        router = ExecutionIntentRouter()
        route = router.route("打开桌面的「微信」")
        assert "微信" in route.target

    def test_execution_intent_enum_values(self):
        assert ExecutionIntent.GENERAL_CHAT.value == "general_chat"
        assert ExecutionIntent.LOCAL_OPEN_TARGET.value == "local_open_target"
        assert ExecutionIntent.LOCAL_FIND_FILE.value == "local_find_file"
        assert ExecutionIntent.MEMORY_QUESTION.value == "memory_question"
