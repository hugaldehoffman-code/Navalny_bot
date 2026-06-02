"""
Tests for prompt content — verify that FBK figures (Volkov, Zhdanov, Pevchikh)
are NOT hard-coded as proactive mentions in SYSTEM_PROMPT or button prompts.

Strategy: parse config.py as source text to extract SYSTEM_PROMPT and
BUTTON_PROMPTS without executing the full module (avoids aiogram/openai deps).
"""
import ast
import os
import sys

import pytest

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config.py")

# ── Extract string literals from config.py via AST ───────────────────────────

def _extract_config_strings() -> dict:
    """Return {'SYSTEM_PROMPT': str, 'BUTTON_PROMPTS': dict[str, str]}."""
    with open(CONFIG_PATH, encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source)

    result = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            name = target.id

            if name == "SYSTEM_PROMPT":
                result["SYSTEM_PROMPT"] = ast.literal_eval(node.value)

            elif name == "BUTTON_PROMPTS":
                raw = ast.literal_eval(node.value)
                result["BUTTON_PROMPTS"] = raw

    return result


_config = _extract_config_strings()
SYSTEM_PROMPT: str = _config["SYSTEM_PROMPT"]
BUTTON_PROMPTS: dict = _config["BUTTON_PROMPTS"]

FBK_FIGURES = ["Волков", "Жданов", "Певчих"]


# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM_PROMPT
# ─────────────────────────────────────────────────────────────────────────────

class TestSystemPromptFBKMentions:
    """
    SYSTEM_PROMPT must NOT instruct bot to proactively mention FBK figures.
    It MAY say bot can respond if the user brings them up.
    """

    def test_no_instruction_to_mock_volkov_proactively(self):
        """Removed: 'Подкалывай их за то, что они сидят в безопасной Европе...'"""
        assert "Подкалывай" not in SYSTEM_PROMPT

    def test_no_instruction_dobray_uhm_volkov_zhdanov(self):
        """Removed: 'Добрая ухмылка над Волковым и Ждановым'"""
        assert "Добрая ухмылка над Волковым" not in SYSTEM_PROMPT

    def test_no_volkov_budget_joke(self):
        """Removed: 'Ой, Волков увидит — лишит бюджета на мерч'"""
        assert "лишит бюджета на мерч" not in SYSTEM_PROMPT

    def test_colleagues_section_is_reactive(self):
        """
        Коллеги section must tell bot to respond only when user asks,
        not instruct it to proactively bring up names.
        """
        assert "Коллеги" in SYSTEM_PROMPT
        # must contain a conditional/reactive phrasing
        reactive_words = ("спрашивает", "сам", "если пользователь", "только если")
        assert any(w in SYSTEM_PROMPT.lower() for w in reactive_words), (
            "Коллеги section must say to respond only when user asks"
        )


# ─────────────────────────────────────────────────────────────────────────────
# BUTTON_PROMPTS
# ─────────────────────────────────────────────────────────────────────────────

class TestButtonPromptsNoProactiveFBK:
    """
    Button prompts (except leaks) must not hard-code FBK figure names.
    """

    def test_merch_prompt_no_volkov(self):
        """Removed: 'Постеби маркетинг Волкова'"""
        assert "Волков" not in BUTTON_PROMPTS["merch"]

    def test_sud_prompt_no_pevchikh(self):
        """Removed: 'обязательный просмотр стримов Певчих'"""
        assert "Певчих" not in BUTTON_PROMPTS["sud"]

    def test_sud_prompt_no_volkov(self):
        assert "Волков" not in BUTTON_PROMPTS["sud"]

    def test_chat_prompt_no_fbk_figures(self):
        for name in FBK_FIGURES:
            assert name not in BUTTON_PROMPTS["chat"], (
                f"chat prompt must not mention {name}"
            )

    def test_joke_prompt_no_fbk_figures(self):
        for name in FBK_FIGURES:
            assert name not in BUTTON_PROMPTS["joke"], (
                f"joke prompt must not mention {name}"
            )

    def test_food_prompt_no_fbk_figures(self):
        for name in FBK_FIGURES:
            assert name not in BUTTON_PROMPTS["food"]

    def test_vision_comment_no_fbk_figures(self):
        for name in FBK_FIGURES:
            assert name not in BUTTON_PROMPTS["vision_comment"]

    def test_news_prompt_no_fbk_figures(self):
        for name in FBK_FIGURES:
            assert name not in BUTTON_PROMPTS["news"]


class TestLeaksPromptIsException:
    """
    The leaks button is USER-INITIATED — user explicitly asks for FBK chat.
    It SHOULD still contain figure names (that's its whole point).
    """

    def test_leaks_has_volkov(self):
        assert "Волков" in BUTTON_PROMPTS["leaks"]

    def test_leaks_has_pevchikh(self):
        assert "Певчих" in BUTTON_PROMPTS["leaks"]

    def test_leaks_has_zhdanov(self):
        assert "Жданов" in BUTTON_PROMPTS["leaks"]


# ─────────────────────────────────────────────────────────────────────────────
# Sanity: core content wasn't accidentally removed
# ─────────────────────────────────────────────────────────────────────────────

class TestPromptsStillFunctional:

    def test_system_prompt_has_digital_navalny(self):
        assert "Цифровой Навальный" in SYSTEM_PROMPT

    def test_system_prompt_has_kamon(self):
        assert "Камон" in SYSTEM_PROMPT

    def test_system_prompt_has_background_lore(self):
        assert "Новичком" in SYSTEM_PROMPT or "ТикТок" in SYSTEM_PROMPT

    def test_merch_still_has_fbk_and_2007(self):
        assert "ФБК" in BUTTON_PROMPTS["merch"]
        assert "2007" in BUTTON_PROMPTS["merch"]

    def test_sud_still_has_lustration(self):
        assert "Люстрации" in BUTTON_PROMPTS["sud"]

    def test_sud_still_has_punishment(self):
        assert "наказание" in BUTTON_PROMPTS["sud"].lower() or "Придумай" in BUTTON_PROMPTS["sud"]

    def test_all_expected_button_keys_present(self):
        expected = {"chat", "news", "joke", "merch", "food", "complaint",
                    "leaks", "vision_comment", "sud"}
        assert expected.issubset(BUTTON_PROMPTS.keys())
