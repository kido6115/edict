#!/usr/bin/env python3
"""应用 data/pending_model_changes.json → agents.json，并重新生成 .claude/agents/*.md

Claude Code 每次启动 Agent 时都会读取 .claude/agents/<id>.md，因此无需重启任何服务。
"""
import pathlib, datetime, logging
from file_lock import atomic_json_write, atomic_json_read
import claude_runtime

log = logging.getLogger('model_change')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s', datefmt='%H:%M:%S')

BASE = pathlib.Path(__file__).parent.parent
DATA = BASE / 'data'
PENDING = DATA / 'pending_model_changes.json'
CHANGE_LOG = DATA / 'model_change_log.json'


def main():
    if not PENDING.exists():
        return
    pending = atomic_json_read(PENDING, [])
    if not pending:
        return

    applied, errors = [], []
    for change in pending:
        ag_id = (change.get('agentId') or '').strip()
        new_model = (change.get('model') or '').strip()
        if not ag_id or not new_model:
            errors.append({'change': change, 'error': 'missing fields'})
            continue
        try:
            old = claude_runtime.set_agent_model(ag_id, new_model)
        except KeyError as e:
            errors.append({'change': change, 'error': str(e)})
            continue
        applied.append({'at': datetime.datetime.now().isoformat(), 'agentId': ag_id, 'oldModel': old, 'newModel': new_model})
        log.info(f'{ag_id}: {old} → {new_model}')

    if applied:
        log_data = atomic_json_read(CHANGE_LOG, [])
        if not isinstance(log_data, list):
            log_data = []
        log_data.extend(applied)
        atomic_json_write(CHANGE_LOG, log_data[-200:])
    elif errors:
        log.warning(f'{len(errors)} changes failed, 0 applied')

    atomic_json_write(PENDING, [])
    atomic_json_write(DATA / 'last_model_change_result.json', {
        'at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'applied': applied, 'errors': errors,
        # 保留字段名以兼容前端；Claude Code 无需重启，生效即为 True
        'gatewayRestarted': bool(applied), 'rolledBack': False,
    })


if __name__ == '__main__':
    main()
