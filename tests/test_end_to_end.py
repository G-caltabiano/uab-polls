import importlib
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

from openpyxl import load_workbook


def csrf(html: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match, html[:500]
    return match.group(1)


def test_complete_poll_flow(tmp_path: Path):
    os.environ["UAB_POLLS_DATA_DIR"] = str(tmp_path)
    os.environ["UAB_POLLS_SESSION_SECRET"] = "test-session-secret-with-enough-entropy"
    os.environ["UAB_POLLS_EMAIL_PROVIDER"] = "gog"
    os.environ["UAB_POLLS_GOG_PATH"] = "/bin/true"

    import app.config
    import app.db
    import app.main

    importlib.reload(app.config)
    importlib.reload(app.db)
    importlib.reload(app.main)

    from fastapi.testclient import TestClient

    with TestClient(app.main.app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["ok"] is True

        asset = client.get("/static/styles.css")
        assert asset.status_code == 200
        assert "--uab: #009639" in asset.text

        response = client.get("/admin/setup")
        token = csrf(response.text)
        response = client.post(
            "/admin/setup",
            data={
                "csrf": token,
                "name": "Gianluigi Caltabiano",
                "email": "gianluigi.caltabiano@uab.cat",
                "password": "contrasenya-molt-segura",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert "Les teves enquestes" in response.text

        response = client.get("/admin/polls/new")
        token = csrf(response.text)
        future = datetime.now() + timedelta(days=8)
        slots = [
            future.replace(hour=10, minute=0, second=0, microsecond=0).isoformat(),
            future.replace(hour=12, minute=30, second=0, microsecond=0).isoformat(),
        ]
        response = client.post(
            "/admin/polls/new",
            data={
                "csrf": token,
                "title": "Reunió de prova",
                "description": "Validació integral",
                "location": "Facultat de Medicina",
                "duration": "60",
                "deadline": "",
                "slots_json": json.dumps(slots),
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert "Enllaç per compartir" in response.text
        public_match = re.search(r'id="public-url" value="([^"]+/p/[^\"]+)"', response.text)
        assert public_match
        public_path = re.sub(r"^https?://[^/]+", "", public_match.group(1))

        public = client.get(public_path)
        token = csrf(public.text)
        slot_ids = re.findall(r'name="choice_(\d+)"', public.text)
        slot_ids = list(dict.fromkeys(slot_ids))
        assert len(slot_ids) == 2
        form = {
            "csrf": token,
            "name": "Participant Prova",
            "email": "participant@example.org",
            "privacy": "accepted",
            f"choice_{slot_ids[0]}": "yes",
            f"choice_{slot_ids[1]}": "maybe",
        }
        response = client.post(public_path, data=form, follow_redirects=True)
        assert response.status_code == 200
        assert "Resposta desada" in response.text
        assert "Participant Prova" in response.text
        assert "participant@example.org" not in response.text

        admin = client.get("/admin/polls/1")
        assert "participant@example.org" in admin.text
        assert "Gmail · Friday" in admin.text

        export = client.get("/admin/polls/1/export.xlsx")
        assert export.status_code == 200
        assert export.content[:2] == b"PK"
        export_path = tmp_path / "export.xlsx"
        export_path.write_bytes(export.content)
        workbook = load_workbook(export_path)
        assert workbook.sheetnames == ["Disponibilitats", "Resum"]
        assert workbook["Disponibilitats"]["A2"].value == "Participant Prova"
