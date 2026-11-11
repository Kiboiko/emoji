#!/usr/bin/env python3
"""Host checks. Python stdlib only; never emits raw logs or exception details."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ['docker', 'compose', '-f', str(ROOT / 'docker-compose.yml')]


def config():
    values = {}
    for line in (ROOT / '.env').read_text(encoding='utf-8-sig').splitlines():
        key, sep, value = line.partition('=')
        if sep and not key.lstrip().startswith('#'):
            values[key.strip()] = value.strip().strip('\"\'')
    # The deployed .env is authoritative; never shell-evaluate its values.
    return dict(os.environ) | values


def run(args, timeout=45, env=None):
    result = subprocess.run(args, cwd=ROOT, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=env, text=True, errors='replace', timeout=timeout)
    if result.returncode:
        raise RuntimeError('command failed')
    return result.stdout


def notify(cfg, message):
    token = cfg.get('TELEGRAM_BOT_TOKEN', '')
    chats = [v.strip() for v in cfg.get('ADMIN_CHAT_ID', '').split(',') if v.strip()]
    if not token or not chats:
        raise RuntimeError('notification configuration missing')
    for chat in chats:
        body = json.dumps({'chat_id': chat, 'text': 'Gram Market: ' + message}).encode()
        req = urllib.request.Request('https://api.telegram.org/bot' + token + '/sendMessage',
                                     data=body, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=15) as response:
            if not json.load(response).get('ok'):
                raise RuntimeError('notification rejected')


def check(cfg, state):
    issues = set()
    services = cfg.get('OPS_SERVICES', 'postgres backend bot nginx frontend admin').split()
    try:
        ids = run(COMPOSE + ['ps', '-aq']).split()
        containers = json.loads(run(['docker', 'inspect', *ids])) if ids else []
        by_service = {}
        for item in containers:
            service = item['Config']['Labels'].get('com.docker.compose.service')
            by_service.setdefault(service, []).append(item['State'])
        for service in services:
            statuses = by_service.get(service, [])
            if not statuses or any(s.get('Status') != 'running' or
                s.get('Health', {}).get('Status', 'healthy') != 'healthy' for s in statuses):
                issues.add('container:' + service)
    except Exception:
        issues.add('docker')
    try:
        run(COMPOSE + ['exec', '-T', 'backend', 'curl', '-fsS', '--max-time', '10',
                       'http://localhost:8000/health'])
    except Exception:
        issues.add('backend-health')
    public_url = cfg.get('OPS_PUBLIC_HEALTH_URL') or (cfg.get('SITE_URL', '').rstrip('/') + '/health' if cfg.get('SITE_URL') else '')
    if public_url:
        try:
            with urllib.request.urlopen(public_url, timeout=15) as response:
                if response.status != 200:
                    issues.add('public-health')
        except Exception:
            issues.add('public-health')
    cutoff = time.time()
    since = state.get('log_since', cutoff - 60)
    try:
        # Bounded output per service. Raw log text is used only in memory, never forwarded.
        stamp = dt.datetime.fromtimestamp(since, dt.timezone.utc).isoformat()
        logs = run(COMPOSE + ['logs', '--no-color', '--since', stamp, '--tail', '2000',
                              'backend', 'bot'])
        if re.search(r'\bERROR\b|Traceback \(most recent call last\)', logs):
            issues.add('application-errors')
            state['last_log_error'] = cutoff
        elif cutoff - state.get('last_log_error', 0) < 300:
            issues.add('application-errors')
        state['log_since'] = cutoff
    except Exception:
        issues.add('log-reader')
    marker = Path(cfg.get('BACKUP_DIR', str(ROOT / 'backups'))) / '.last-success'
    if not marker.is_absolute():
        marker = ROOT / marker
    if not marker.exists() or cutoff - marker.stat().st_mtime > 26 * 3600:
        issues.add('backup-older-than-26h')
    return issues


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['monitor', 'backup', 'test-notification'])
    args = parser.parse_args()
    os.umask(0o077)
    cfg = config()
    directory = Path(cfg.get('OPS_STATE_DIR', '/var/lib/gram-market-ops'))
    directory.mkdir(parents=True, exist_ok=True)
    # Linux only: lock serializes timer and manual invocations.
    import fcntl
    with (directory / (args.action + '.lock')).open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        if args.action == 'test-notification':
            notify(cfg, 'Тест доставки эксплуатационных уведомлений.')
            return
        path = directory / (args.action + '.json')
        state = json.loads(path.read_text()) if path.exists() else {}
        if args.action == 'backup':
            try:
                run(['bash', str(ROOT / 'scripts/backup-db.sh')], timeout=3600, env=cfg)
                issues = set()
            except Exception:
                issues = {'backup-failed'}
        else:
            issues = check(cfg, state)
        previous = set(state.get('issues', []))
        deliveries = state.setdefault('notified_issues', {})
        chats = [v.strip() for v in cfg.get('ADMIN_CHAT_ID', '').split(',') if v.strip()]
        delivery_failed = not chats and issues != previous
        for chat in dict.fromkeys(chats):
            # Each recipient advances independently. A failed second delivery
            # must not repeat a successful first delivery on every timer tick.
            key = hashlib.sha256(chat.encode()).hexdigest()
            delivered = set(deliveries.setdefault(key, sorted(previous)))
            added, cleared = sorted(issues - delivered), sorted(delivered - issues)
            if not (added or cleared):
                continue
            chunks = []
            if added:
                chunks.append('Сбой: ' + ', '.join(added))
            if cleared:
                chunks.append('Восстановлено: ' + ', '.join(cleared))
            try:
                notify(cfg | {'ADMIN_CHAT_ID': chat}, '\n'.join(chunks))
            except Exception:
                delivery_failed = True
                continue
            deliveries[key] = sorted(issues)
            # Persist successful deliveries before attempting the next chat.
            temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps(state), encoding='utf-8')
            temp.replace(path)
        state['issues'] = sorted(issues)
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(state), encoding='utf-8')
        temp.replace(path)
        if issues or delivery_failed:
            sys.exit(1)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # urllib exception includes the bot token URL; never print its representation.
        print('OPS failed; check Docker/configuration/notification delivery locally.', file=sys.stderr)
        sys.exit(1)
