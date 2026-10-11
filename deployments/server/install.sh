#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
    exec sudo env WHEELHOUSE="${WHEELHOUSE:-}" ENABLE_TIMER="${ENABLE_TIMER:-0}" bash "$0"
fi

repo_dir=$(cd "$(dirname "$0")/../.." && pwd)
app_root=/opt/nest-climate-report
if systemctl is-active --quiet nest-climate-report.service; then
    echo "wait for the active report before installation" >&2
    exit 1
fi
[[ -r /etc/tg-server-control/bot.env ]] || { echo "missing Telegram environment" >&2; exit 1; }
[[ -r /etc/tg-server-control/ydb-sa-key.json ]] || { echo "missing YDB credential" >&2; exit 1; }
# The hashed lock matches Linux x86_64 CPython 3.12; other interpreters use the version ranges.
options=(--disable-pip-version-check)
if [[ "$(/usr/bin/python3 -c 'import platform,sys; print(platform.machine(), "%d.%d" % sys.version_info[:2])')" == "x86_64 3.12" ]]; then
    requirements="$repo_dir/deployments/server/requirements.lock"
    options+=(--require-hashes --only-binary=:all:)
else
    requirements="$repo_dir/deployments/server/requirements.txt"
fi
[[ -r /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf ]] || { echo "install fonts-dejavu-core" >&2; exit 1; }

install -d -o root -g root -m 0755 "$app_root" "$app_root/app" "$app_root/app/nest_climate"
/usr/bin/python3 -m venv "$app_root/venv"
if [[ -n ${WHEELHOUSE:-} ]]; then
    options+=(--no-index --find-links "$WHEELHOUSE")
else
    options+=(--index-url https://pypi.org/simple)
fi
"$app_root/venv/bin/python" -m pip install "${options[@]}" -r "$requirements"
"$app_root/venv/bin/python" -m pip check
"$app_root/venv/bin/python" -I -c 'import ydb, PIL, requests, socks'
install -o root -g root -m 0644 "$repo_dir/nest_climate/"*.py "$app_root/app/nest_climate/"
install -o root -g root -m 0644 "$requirements" "$app_root/requirements.lock"
chown -R root:root "$app_root"
chmod -R go-w "$app_root"
install -o root -g root -m 0644 "$repo_dir/deployments/server/nest-climate-report.service" /etc/systemd/system/
install -o root -g root -m 0644 "$repo_dir/deployments/server/nest-climate-report.timer" /etc/systemd/system/
systemctl daemon-reload
if [[ ${ENABLE_TIMER:-0} == 1 ]]; then
    systemctl enable --now nest-climate-report.timer
fi
