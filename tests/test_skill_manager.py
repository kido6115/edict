import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


def _load_skill_manager(home, hub_base=None):
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "skill_manager.py"

    env = {"EDICT_AGENTS_DIR": str(home / "agents"), "EDICT_RUNTIME_HOME": str(home / "runtime")}
    if hub_base is not None:
        env["EDICT_SKILLS_HUB_BASE"] = hub_base

    spec = importlib.util.spec_from_file_location("skill_manager_under_test", script_path)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(os.environ, env, clear=False):
        if hub_base is None:
            os.environ.pop("EDICT_SKILLS_HUB_BASE", None)
        spec.loader.exec_module(module)
    return module


class SkillManagerTests(unittest.TestCase):
    def test_default_skills_do_not_use_removed_legacy_hub(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill_manager = _load_skill_manager(Path(tmp))

        self.assertIn("mmx_cli", skill_manager.OFFICIAL_SKILLS_HUB)
        self.assertTrue(
            all(
                "openclaw-ai/skills-hub" not in url
                for url in skill_manager.OFFICIAL_SKILLS_HUB.values()
            )
        )

    def test_custom_hub_base_restores_hub_skill_urls(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill_manager = _load_skill_manager(
                Path(tmp),
                hub_base="https://example.com/edict-skills",
            )

        self.assertEqual(
            skill_manager.OFFICIAL_SKILLS_HUB["code_review"],
            "https://example.com/edict-skills/code_review/SKILL.md",
        )
        self.assertEqual(
            skill_manager.OFFICIAL_SKILLS_HUB["test_framework"],
            "https://example.com/edict-skills/test_framework/SKILL.md",
        )
        self.assertEqual(
            skill_manager.OFFICIAL_SKILLS_HUB["mmx_cli"],
            "https://raw.githubusercontent.com/MiniMax-AI/cli/main/skill/SKILL.md",
        )

    def test_import_official_hub_uses_per_skill_recommended_agents(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill_manager = _load_skill_manager(Path(tmp))

        calls = []

        def fake_add_remote(agent_id, skill_name, source_url, description=""):
            calls.append((agent_id, skill_name, source_url, description))
            return True

        with mock.patch.object(skill_manager, "add_remote", fake_add_remote):
            self.assertTrue(skill_manager.import_official_hub([]))

        self.assertEqual(
            calls,
            [
                (
                    "menxia",
                    "mmx_cli",
                    "https://raw.githubusercontent.com/MiniMax-AI/cli/main/skill/SKILL.md",
                    "默认 skill：mmx_cli",
                ),
                (
                    "shangshu",
                    "mmx_cli",
                    "https://raw.githubusercontent.com/MiniMax-AI/cli/main/skill/SKILL.md",
                    "默认 skill：mmx_cli",
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
