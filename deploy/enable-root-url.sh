#!/usr/bin/env bash
set -euo pipefail

NGINX_SITE="/etc/nginx/sites-available/horario-uab"
BACKUP="${NGINX_SITE}_orig"
APP_SERVICE="/home/gian/.config/systemd/user/uab-polls.service"

if [[ ! -f "$NGINX_SITE" ]]; then
  echo "No s'ha trobat $NGINX_SITE" >&2
  exit 1
fi

sudo cp --update=none "$NGINX_SITE" "$BACKUP"
sudo python3 - "$NGINX_SITE" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
if "location /enquestes/" in text:
    print("La ruta /enquestes/ ja existeix")
    raise SystemExit(0)
marker = "    location = /horario {"
block = """    location = /enquestes {
        return 301 /enquestes/;
    }

    location /enquestes/ {
        proxy_pass http://127.0.0.1:8096/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

"""
if marker not in text:
    raise SystemExit("No s'ha trobat el punt d'inserció segur")
path.write_text(text.replace(marker, block + marker, 1))
PY

sudo nginx -t
sudo systemctl reload nginx
if [[ "${EUID}" -eq 0 ]]; then
  runuser -u gian -- sed -i 's#UAB_POLLS_ROOT_PATH=/horario/enquestes#UAB_POLLS_ROOT_PATH=/enquestes#' "$APP_SERVICE"
  runuser -u gian -- env XDG_RUNTIME_DIR=/run/user/1000 systemctl --user daemon-reload
  runuser -u gian -- env XDG_RUNTIME_DIR=/run/user/1000 systemctl --user restart uab-polls.service
else
  sed -i 's#UAB_POLLS_ROOT_PATH=/horario/enquestes#UAB_POLLS_ROOT_PATH=/enquestes#' "$APP_SERVICE"
  systemctl --user daemon-reload
  systemctl --user restart uab-polls.service
fi
curl -fsS http://127.0.0.1/enquestes/health -H 'Host: pomodoro.uab.cat'
echo
echo "Ruta activa: http://pomodoro.uab.cat/enquestes/"
