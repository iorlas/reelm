"""Unit tests for skills MCP server."""

import pytest

from mcps.servers.skills import SKILLS, get_skill, list_skills


@pytest.mark.unit
class TestListSkills:
    def test_list_skills_returns_all(self):
        result = list_skills()
        assert "brainstorm" in result
        assert "acc" in result
        assert f"Available skills ({len(SKILLS)}):" in result

    def test_list_skills_includes_descriptions(self):
        result = list_skills()
        assert "decision coaching" in result.lower()
        assert "metacognitive" in result.lower()
        assert "crystallization" in result.lower()


@pytest.mark.unit
class TestGetSkill:
    def test_get_brainstorm(self):
        result = get_skill("brainstorm")
        assert "Phase 0: Tool Fit" in result
        assert "Adversarial" in result
        assert "ONE question/turn" in result

    def test_get_acc(self):
        result = get_skill("acc")
        assert "Seven Lenses" in result
        assert "Reframe" in result
        assert "Spend cheap tokens" in result

    def test_get_reflect(self):
        result = get_skill("reflect")
        assert "Crystallization" in result
        assert "What Shifted" in result
        assert "Still Open" in result
        assert "Don't flatter" in result

    def test_get_nonexistent(self):
        result = get_skill("nonexistent")
        assert "not found" in result.lower()
        assert "brainstorm" in result
        assert "acc" in result
