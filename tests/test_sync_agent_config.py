import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import claude_runtime  # noqa: E402
import sync_agent_config  # noqa: E402


def _setup_registry(tmp_path, monkeypatch, agents):
    reg = tmp_path / "agents.json"
    reg.write_text(json.dumps({"defaultModel": "inherit", "agents": agents}, ensure_ascii=False))
    monkeypatch.setattr(claude_runtime, "AGENTS_JSON", reg)
    monkeypatch.setattr(claude_runtime, "CLAUDE_AGENTS_DIR", tmp_path / ".claude" / "agents")
    monkeypatch.setenv("EDICT_AGENTS_DIR", str(tmp_path / "agents"))
    monkeypatch.setattr(sync_agent_config, "DATA", tmp_path / "data")


def test_sync_agent_config_reads_registry(tmp_path, monkeypatch):
    _setup_registry(tmp_path, monkeypatch, [
        {"id": "taizi", "description": "太子", "model": "opus", "allowAgents": ["zhongshu"]},
        {"id": "menxia", "description": "门下省", "allowAgents": []},
    ])
    skill = tmp_path / "agents" / "menxia" / "skills" / "audit" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: audit\ndescription: 审计清单\n---\n")

    sync_agent_config.main()

    out = json.loads((tmp_path / "data" / "agent_config.json").read_text())
    assert out["runtime"] == "claude-code"
    taizi = next(a for a in out["agents"] if a["id"] == "taizi")
    menxia = next(a for a in out["agents"] if a["id"] == "menxia")
    assert taizi["allowAgents"] == ["zhongshu"]
    assert taizi["model"] == "opus" and not taizi["isDefaultModel"]
    assert menxia["model"] == "inherit" and menxia["isDefaultModel"]
    assert menxia["skills"][0]["name"] == "audit"
    assert any(m["id"] == "sonnet" for m in out["knownModels"])
    # 同时生成了 .claude/agents/*.md
    assert (tmp_path / ".claude" / "agents" / "taizi.md").exists()


def test_sync_agent_config_keeps_dispatch_channel(tmp_path, monkeypatch):
    _setup_registry(tmp_path, monkeypatch, [{"id": "taizi"}])
    data = tmp_path / "data"
    data.mkdir()
    (data / "agent_config.json").write_text(json.dumps({"dispatchChannel": "telegram"}))

    sync_agent_config.main()

    out = json.loads((data / "agent_config.json").read_text())
    assert out["dispatchChannel"] == "telegram"
