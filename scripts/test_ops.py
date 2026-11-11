"""Isolated host checks: no Docker, network, .env or database access."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('ops', Path(__file__).with_name('ops.py'))
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)


class OpsTests(unittest.TestCase):
    def test_notifications_only_on_transition_and_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = {'OPS_STATE_DIR': directory, 'ADMIN_CHAT_ID': '111'}
            fake_lock = types.SimpleNamespace(LOCK_EX=1, LOCK_NB=2, flock=lambda *args: None)
            with patch.object(ops, 'config', return_value=cfg), patch.object(ops, 'notify') as notify, patch.dict(sys.modules, {'fcntl': fake_lock}), patch.object(sys, 'argv', ['ops.py', 'monitor']):
                for index, issues in enumerate([set(), set(), {'docker'}, {'docker'}, set(), set()]):
                    with patch.object(ops, 'check', return_value=issues):
                        try:
                            ops.main()
                        except SystemExit as error:
                            self.assertEqual(error.code, 1)
                    self.assertEqual(notify.call_count, [0, 0, 1, 1, 2, 2][index])
                self.assertEqual(notify.call_count, 2)
                self.assertIn('Сбой', notify.call_args_list[0].args[1])
                self.assertIn('Восстановлено', notify.call_args_list[1].args[1])


    def test_public_health_defaults_to_site_url(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / '.last-success').touch()
            response = types.SimpleNamespace(status=200)
            context = unittest.mock.MagicMock()
            context.__enter__.return_value = response
            with patch.object(ops, 'run', return_value=''), patch.object(ops.urllib.request, 'urlopen', return_value=context) as request:
                ops.check({'SITE_URL': 'https://example.test/', 'BACKUP_DIR': directory}, {})
            request.assert_called_once_with('https://example.test/health', timeout=15)

    def test_env_file_overrides_stale_process_environment_without_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.env').write_text('DB_NAME="current"\nBACKUP_DIR="/tmp/backups"\n', encoding='utf-8')
            with patch.object(ops, 'ROOT', root), patch.dict(ops.os.environ, {'DB_NAME': 'stale'}):
                cfg = ops.config()
            self.assertEqual(cfg['DB_NAME'], 'current')
            self.assertEqual(cfg['BACKUP_DIR'], '/tmp/backups')

    def test_failed_delivery_keeps_previous_notification_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'monitor.json'
            path.write_text(json.dumps({'issues': []}))
            fake_lock = types.SimpleNamespace(LOCK_EX=1, LOCK_NB=2, flock=lambda *args: None)
            with patch.object(ops, 'config', return_value={'OPS_STATE_DIR': directory, 'ADMIN_CHAT_ID': '111'}), patch.object(ops, 'notify', side_effect=RuntimeError('offline')), patch.object(ops, 'check', return_value={'docker'}), patch.dict(sys.modules, {'fcntl': fake_lock}), patch.object(sys, 'argv', ['ops.py', 'monitor']):
                with self.assertRaises(SystemExit):
                    ops.main()
            state = json.loads(path.read_text())
            self.assertEqual(state['issues'], ['docker'])
            self.assertEqual(list(state['notified_issues'].values()), [[]])

    def test_partial_delivery_retries_only_failed_recipient_and_recovers(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = {'OPS_STATE_DIR': directory, 'ADMIN_CHAT_ID': '111,222'}
            fake_lock = types.SimpleNamespace(LOCK_EX=1, LOCK_NB=2, flock=lambda *args: None)
            delivered = []
            second_available = False

            def send(config, message):
                chat = config['ADMIN_CHAT_ID']
                if chat == '222' and not second_available:
                    raise RuntimeError('chat unavailable')
                delivered.append((chat, message))

            with patch.object(ops, 'config', return_value=cfg), patch.object(ops, 'notify', side_effect=send), patch.dict(sys.modules, {'fcntl': fake_lock}), patch.object(sys, 'argv', ['ops.py', 'monitor']):
                for _ in range(3):
                    with patch.object(ops, 'check', return_value={'application-errors'}):
                        with self.assertRaises(SystemExit):
                            ops.main()
                self.assertEqual([chat for chat, _ in delivered], ['111'])
                second_available = True
                with patch.object(ops, 'check', return_value={'application-errors'}):
                    with self.assertRaises(SystemExit):
                        ops.main()
                self.assertEqual([chat for chat, _ in delivered], ['111', '222'])
                with patch.object(ops, 'check', return_value=set()):
                    ops.main()
                    ops.main()
                self.assertEqual([chat for chat, _ in delivered], ['111', '222', '111', '222'])
                self.assertTrue(all('Восстановлено' in message for _, message in delivered[-2:]))

    def test_error_logs_are_not_forwarded(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / '.last-success'
            marker.touch()
            containers = [{'Config': {'Labels': {'com.docker.compose.service': 'backend'}}, 'State': {'Status': 'running', 'Health': {'Status': 'healthy'}}}]
            def command(args, **kwargs):
                if 'inspect' in args:
                    return json.dumps(containers)
                if 'ps' in args:
                    return 'container-id'
                if 'logs' in args:
                    return 'ERROR secret-token-do-not-send'
                return 'OK'
            state = {}
            with patch.object(ops, 'run', side_effect=command):
                issues = ops.check({'OPS_SERVICES': 'backend', 'BACKUP_DIR': directory}, state)
            self.assertEqual(issues, {'application-errors'})
            self.assertNotIn('secret', json.dumps(state))


if __name__ == '__main__':
    unittest.main()
