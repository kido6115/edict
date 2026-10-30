"""Tests for scripts/claude_runtime.py — Claude Code 运行时适配层。"""
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import claude_runtime as cr  # noqa: E402


@pytest.fixture
def project(tmp_path, monkeypatch):
    agents = tmp_path / 'agents'
    (agents / 'menxia').mkdir(parents=True)
    (agents / 'menxia' / 'SOUL.md').write_text('# 门下省\n项目在 `__REPO_DIR__/`\n', encoding='utf-8')
    (agents / 'GLOBAL.md').write_text('# 全局规则\n', encoding='utf-8')
    reg = tmp_path / 'agents.json'
    reg.write_text(json.dumps({
        'defaultModel': 'inherit',
        'agents': [
            {'id': 'menxia', 'description': '门下省·审议', 'model': 'inherit', 'tools': ['Read', 'Bash']},
            {'id': 'gongbu', 'description': '工部', 'tools': []},
        ],
    }, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(cr, 'AGENTS_JSON', reg)
    monkeypatch.setattr(cr, 'AGENTS_SRC', agents)
    monkeypatch.setattr(cr, 'CLAUDE_AGENTS_DIR', tmp_path / '.claude' / 'agents')
    monkeypatch.setattr(cr, 'COURT_SKILL', tmp_path / '.claude' / 'skills' / 'edict' / 'SKILL.md')
    monkeypatch.delenv('EDICT_AGENTS_DIR', raising=False)
    monkeypatch.setenv('EDICT_RUNTIME_HOME', str(tmp_path / 'runtime'))
    return tmp_path


def test_build_renders_frontmatter_and_prompt(project):
    written = cr.build()
    assert {p.name for p in written} == {'menxia.md', 'gongbu.md'}
    text = (project / '.claude' / 'agents' / 'menxia.md').read_text(encoding='utf-8')
    assert text.startswith('---\nname: menxia\ndescription: "门下省·审议"\ntools: Read, Bash\nmodel: inherit\n---\n')
    assert '项目在 `./`' in text          # __REPO_DIR__ 已替换
    assert '# 全局规则' in text            # 拼接 GLOBAL.md
    gongbu = (project / '.claude' / 'agents' / 'gongbu.md').read_text(encoding='utf-8')
    assert 'tools:' not in gongbu          # 空 tools → 继承全部工具
    # 内容未变时不重复写入
    assert cr.build() == []


def test_build_lists_agent_skills(project):
    skill = project / 'agents' / 'menxia' / 'skills' / 'checklist' / 'SKILL.md'
    skill.parent.mkdir(parents=True)
    skill.write_text('---\nname: checklist\ndescription: 审议清单\n---\n正文\n', encoding='utf-8')
    cr.build(['menxia'])
    text = cr.agent_file('menxia').read_text(encoding='utf-8')
    assert '**checklist** — 审议清单' in text
    assert 'agents/menxia/skills/checklist/SKILL.md' in text


def test_set_agent_model_updates_registry_and_file(project):
    cr.build()
    old = cr.set_agent_model('menxia', 'opus')
    assert old == 'inherit'
    assert cr.get_agent_model('menxia') == 'opus'
    assert 'model: opus' in cr.agent_file('menxia').read_text(encoding='utf-8')
    with pytest.raises(KeyError):
        cr.set_agent_model('nobody', 'opus')


def test_build_command(monkeypatch):
    monkeypatch.setenv('EDICT_CLAUDE_PERMISSION_MODE', 'bypassPermissions')
    monkeypatch.setenv('EDICT_CLAUDE_ARGS', '--max-budget-usd 2')
    cmd = cr.build_command('你好', agent_id='taizi', claude_bin='/usr/bin/claude')
    assert cmd[:3] == ['/usr/bin/claude', '-p', '你好']
    assert cmd[cmd.index('--agent') + 1] == 'taizi'
    assert cmd[cmd.index('--permission-mode') + 1] == 'bypassPermissions'
    assert cmd[-2:] == ['--max-budget-usd', '2']


def test_session_recorder_routes_subagent_messages(project):
    rec = cr.SessionRecorder('taizi', label='JJC-1 · Zhongshu')
    rec.start('续办 JJC-1')
    rec.feed({'type': 'assistant', 'parent_tool_use_id': None, 'message': {'content': [
        {'type': 'tool_use', 'id': 'toolu_A', 'name': 'Agent', 'input': {'subagent_type': 'zhongshu', 'prompt': '起草'}},
    ]}})
    rec.feed({'type': 'assistant', 'parent_tool_use_id': 'toolu_A', 'message': {
        'content': [{'type': 'tool_use', 'id': 'toolu_B', 'name': 'Bash', 'input': {'command': 'python3 scripts/kanban_update.py state JJC-1 Menxia'}}],
        'usage': {'input_tokens': 10, 'output_tokens': 5},
    }})
    rec.feed({'type': 'user', 'parent_tool_use_id': 'toolu_A', 'message': {'content': [
        {'type': 'tool_result', 'tool_use_id': 'toolu_B', 'content': 'ok', 'is_error': False},
    ]}})
    rec.feed({'type': 'result', 'result': '已转交门下省', 'is_error': False,
              'usage': {'input_tokens': 100, 'output_tokens': 20}, 'total_cost_usd': 0.01})
    rec.finish(aborted=False)

    assert rec.result_text == '已转交门下省'
    zs = cr.sessions_dir('zhongshu')
    lines = [json.loads(l) for l in (zs / f'{rec.session_id}.jsonl').read_text(encoding='utf-8').splitlines()]
    assert lines[0]['message']['role'] == 'assistant'
    assert lines[1]['message'] == {
        'role': 'toolResult', 'toolName': 'Bash',
        'content': [{'type': 'text', 'text': 'ok'}], 'details': {'exitCode': 0},
    }
    zs_index = json.loads((zs / 'sessions.json').read_text(encoding='utf-8'))[rec.session_id]
    assert zs_index['inputTokens'] == 10 and zs_index['outputTokens'] == 5
    assert zs_index['origin']['label'] == 'agent:zhongshu:subagent:taizi'

    tz_index = json.loads((cr.sessions_dir('taizi') / 'sessions.json').read_text(encoding='utf-8'))[rec.session_id]
    assert tz_index['inputTokens'] == 100 and tz_index['costUsd'] == 0.01
    assert tz_index['abortedLastRun'] is False


def test_run_agent_without_cli(monkeypatch):
    monkeypatch.setattr(cr, 'resolve_claude_bin', lambda: None)
    r = cr.run_agent('taizi', 'hi')
    assert r['returncode'] == -1
    assert 'claude CLI' in r['stderr']
