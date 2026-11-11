#!/usr/bin/env bash
# Install only these four owned units; do not modify Compose or .env.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run as root' >&2; exit 1; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# systemd command/path escaping is deliberately restricted.
[[ "$ROOT" =~ ^/[a-zA-Z0-9_./-]+$ ]] || { echo 'Use a path without spaces/special characters' >&2; exit 1; }
command -v python3 >/dev/null
command -v flock >/dev/null
command -v docker >/dev/null
systemctl --version >/dev/null
install -d -m 700 /var/lib/gram-market-ops
for action in backup monitor; do
    cat > "/etc/systemd/system/gram-market-$action.service" <<EOF
[Unit]
Description=Gram Market $action
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$ROOT
ExecStart=/usr/bin/env python3 $ROOT/scripts/ops.py $action
UMask=0077
TimeoutStartSec=70min
EOF
    if [[ "$action" == backup ]]; then
        schedule='OnCalendar=*-*-* 03:30:00 Europe/Moscow'
        extra='Persistent=true'
    else
        schedule='OnBootSec=2min'
        extra='OnUnitActiveSec=60s'
    fi
    cat > "/etc/systemd/system/gram-market-$action.timer" <<EOF
[Unit]
Description=Gram Market $action timer

[Timer]
$schedule
$extra
AccuracySec=10s

[Install]
WantedBy=timers.target
EOF
done
systemctl daemon-reload
systemctl enable --now gram-market-backup.timer gram-market-monitor.timer
systemctl list-timers gram-market-backup.timer gram-market-monitor.timer --no-pager
