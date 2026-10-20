"""
ha.py - koppeling met Home Assistant via de Supervisor-API.

- meld():        pushmelding (notify-service) met optionele knoppen, anders melding in HA
- zet_sensor():  sensoren zoals sensor.tennis_volgende_baan
- agenda():      afspraak in een HA-agenda (calendar.create_event)
- luister_naar_knoppen(): ontvangt knopdrukken uit pushmeldingen (websocket)
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request

from boeker import CFG, log

TOKEN = os.getenv("SUPERVISOR_TOKEN")
API = "http://supervisor/core/api"
ACTIE_PREFIX = "TENNIS_"


def _post(pad: str, data: dict) -> bool:
    if not TOKEN:
        log(f"(geen HA-verbinding) {pad}: {json.dumps(data, ensure_ascii=False)[:200]}")
        return False
    req = urllib.request.Request(
        f"{API}/{pad}", data=json.dumps(data).encode("utf-8"),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        log(f"Home Assistant-aanroep mislukt ({pad}): {e}")
        return False


def notify_service() -> str:
    """'notify.mobile_app_x', 'mobile_app_x' of een apparaatnaam als 'iPhone (2)' -> 'mobile_app_iphone_2'."""
    import re
    import unicodedata
    naam = (CFG.get("notify_service") or "").strip().removeprefix("notify.")
    if not naam:
        return ""
    naam = unicodedata.normalize("NFKD", naam).encode("ascii", "ignore").decode().lower()
    naam = re.sub(r"[^a-z0-9]+", "_", naam).strip("_")
    if naam.startswith("mobile_app_") or naam in ("notify", "persistent_notification"):
        return naam
    return naam if "_" in naam and not re.search(r"(iphone|ipad|pixel|galaxy|sm_|phone)", naam) \
        else f"mobile_app_{naam}"


def meld(titel: str, tekst: str, knoppen: list[tuple[str, str]] | None = None) -> None:
    """knoppen: [(actie_id, label)] - werkt alleen met een mobile_app-notify-service."""
    service = notify_service()
    if service:
        data: dict = {"title": titel, "message": tekst}
        if knoppen and service.startswith("mobile_app"):
            data["data"] = {"actions": [{"action": ACTIE_PREFIX + a, "title": l}
                                        for a, l in knoppen]}
        _post(f"services/notify/{service}", data)
    else:
        _post("services/persistent_notification/create", {"title": titel, "message": tekst})


def zet_sensor(entity_id: str, staat: str, attributen: dict) -> None:
    _post(f"states/{entity_id}", {"state": staat, "attributes": attributen})


def agenda(titel: str, start: str, eind: str, omschrijving: str = "") -> None:
    """start/eind als 'YYYY-MM-DD HH:MM:SS'. Alleen als 'agenda' is ingesteld."""
    entity = (CFG.get("agenda") or "").strip()
    if not entity:
        return
    if not entity.startswith("calendar."):
        entity = "calendar." + entity
    _post("services/calendar/create_event",
          {"entity_id": entity, "summary": titel, "start_date_time": start,
           "end_date_time": eind, "description": omschrijving})


def luister_naar_knoppen(verwerk) -> None:
    """Start een achtergrondthread die knopdrukken uit meldingen doorgeeft aan verwerk(actie)."""
    if not TOKEN:
        return

    def lus():
        import websocket  # pakket websocket-client
        while True:
            try:
                ws = websocket.create_connection("ws://supervisor/core/websocket", timeout=60)
                json.loads(ws.recv())                                   # auth_required
                ws.send(json.dumps({"type": "auth", "access_token": TOKEN}))
                if json.loads(ws.recv()).get("type") != "auth_ok":
                    raise RuntimeError("websocket-authenticatie mislukt")
                ws.send(json.dumps({"id": 1, "type": "subscribe_events",
                                    "event_type": "mobile_app_notification_action"}))
                ws.settimeout(60)
                volgnummer = 1
                while True:
                    try:
                        bericht = json.loads(ws.recv())
                    except websocket.WebSocketTimeoutException:
                        volgnummer += 1                 # stil: even pingen of de lijn nog leeft
                        ws.send(json.dumps({"id": volgnummer, "type": "ping"}))
                        continue
                    actie = (bericht.get("event") or {}).get("data", {}).get("action", "")
                    if actie.startswith(ACTIE_PREFIX):
                        try:
                            verwerk(actie.removeprefix(ACTIE_PREFIX))
                        except Exception as e:
                            log(f"Knop '{actie}' verwerken mislukt: {e}")
            except Exception as e:
                log(f"Verbinding voor meldingsknoppen verbroken ({e}), opnieuw over 30 s")
                time.sleep(30)

    threading.Thread(target=lus, daemon=True, name="knoppen").start()
