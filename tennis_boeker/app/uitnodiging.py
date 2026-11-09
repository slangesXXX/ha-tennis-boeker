"""
uitnodiging.py - agenda-afspraak in Home Assistant + uitnodiging per mail naar de medespeler.

Werkt met een 'inv'-dict per boeking:
    doel   wat er in de agenda moet staan ({"start","partner","baan"}) of None = niets/weg
    gedaan wat er al is aangemaakt/verstuurd (zelfde vorm + "email"), of None
    uid    id van de uitnodiging, seq = versienummer (voor updates/annuleringen)
synchroniseer(inv) brengt 'gedaan' in lijn met 'doel': aanmaken, bijwerken of annuleren.
Alle aanroepen gaan één voor één via een wachtrij, zodat een update nooit voor het
aanmaken langs kan.
"""
from __future__ import annotations

import os
import queue
import threading
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ha
from boeker import CFG, DAGEN, DATA, TZ, log

DELEN = Path("/share/tennis_boeker")          # voor HA zichtbaar, nodig voor mailbijlagen
_Q: queue.Queue = queue.Queue()
_THREAD: threading.Thread | None = None


# --------------------------------------------------------------------------- instellingen
def _norm(naam: str) -> str:
    s = unicodedata.normalize("NFKD", naam or "").encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())


def partner_email(naam: str) -> str:
    """E-mailadres van een medespeler uit de lijst 'Naam=adres' (instelling partner_emails)."""
    wie = _norm(naam)
    for regel in CFG.get("partner_emails") or []:
        n, _, adres = str(regel).partition("=")
        if _norm(n) == wie and "@" in adres:
            return adres.strip()
    return ""


def mail_klaar() -> bool:
    return bool((CFG.get("mail_service") or "").strip() and (CFG.get("mijn_email") or "").strip())


def beschikbaar() -> bool:
    """True als er iets te doen valt: een agenda en/of een mailservice is ingesteld."""
    return bool(ha.agenda_entity()) or mail_klaar()


# --------------------------------------------------------------------------- ics
def _esc(t: str) -> str:
    return (str(t).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r", "").replace("\n", "\\n"))


def _vouw(regel: str) -> list[str]:
    b = regel.encode("utf-8")
    delen, eerste = [], True
    while b:
        n = 75 if eerste else 74
        stuk = b[:n]
        while True:                               # niet midden in een teken knippen
            try:
                stuk.decode("utf-8")
                break
            except UnicodeDecodeError:
                stuk = stuk[:-1]
        delen.append(("" if eerste else " ") + stuk.decode("utf-8"))
        b, eerste = b[len(stuk):], False
    return delen


def _utc(naief: datetime) -> str:
    return naief.replace(tzinfo=TZ).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _mijn_naam() -> str:
    return (CFG.get("mijn_naam") or "").strip() or (CFG.get("mijn_email") or "").split("@")[0]


def maak_ics(uid: str, seq: int, methode: str, start: datetime, titel: str, locatie: str,
             partner: str, adres: str) -> str:
    eind = start + timedelta(hours=1)
    ik, mijn = _mijn_naam(), (CFG.get("mijn_email") or "").strip()
    regels = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Tennis Boeker//NL",
              "CALSCALE:GREGORIAN", f"METHOD:{methode}", "BEGIN:VEVENT",
              f"UID:{uid}", f"SEQUENCE:{seq}", f"DTSTAMP:{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}",
              f"DTSTART:{_utc(start)}", f"DTEND:{_utc(eind)}", f"SUMMARY:{_esc(titel)}",
              f"STATUS:{'CANCELLED' if methode == 'CANCEL' else 'CONFIRMED'}",
              f"ORGANIZER;CN={_esc(ik)}:mailto:{mijn}",
              f"ATTENDEE;CN={_esc(partner)};ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:{adres}"]
    if locatie:
        regels.append(f"LOCATION:{_esc(locatie)}")
    regels += ["DESCRIPTION:" + _esc("Geboekt via Tennis Boeker."), "END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(r for l in regels for r in _vouw(l)) + "\r\n"


# --------------------------------------------------------------------------- opbouw
def nieuw(datum: str, tijd: str, partner: str) -> dict:
    return {"uid": f"{uuid.uuid4()}@tennisboeker", "seq": 0, "gedaan": None,
            "doel": {"start": f"{datum} {tijd}", "partner": partner, "baan": None}}


def _titel(d: dict) -> str:
    return f"Tennis met {d['partner']}" + (f" (baan {d['baan']})" if d.get("baan") else "")


def _start(d: dict) -> datetime:
    return datetime.strptime(d["start"], "%Y-%m-%d %H:%M")


def _wanneer(start: datetime) -> str:
    return f"{DAGEN[start.weekday()].lower()} {start:%d-%m} om {start:%H:%M}"


# --------------------------------------------------------------------------- uitvoeren
def _stuur_mail(inv: dict, methode: str, d: dict, adres: str) -> bool:
    if not (mail_klaar() and adres):
        return False
    start = _start(d)
    locatie = f"Baan {d['baan']}" if d.get("baan") else ""
    ics = maak_ics(inv["uid"], inv["seq"], methode, start, _titel(d), locatie, d["partner"], adres)
    ik = _mijn_naam()
    if methode == "CANCEL":
        onderwerp = f"Geannuleerd: tennis {_wanneer(start)}"
        tekst = f"{ik} heeft de tennisafspraak van {_wanneer(start)} geannuleerd."
    else:
        onderwerp = f"Uitnodiging: tennis {_wanneer(start)}"
        tekst = (f"{ik} nodigt je uit voor tennis op {_wanneer(start)}"
                 f"{f' ({locatie})' if locatie else ''}. Open de bijlage om het in je agenda te zetten.")
    pad = None
    try:
        try:
            DELEN.mkdir(parents=True, exist_ok=True)
            pad = DELEN / f"uitnodiging-{uuid.uuid4().hex[:8]}.ics"
        except OSError:
            pad = None
        if pad:
            pad.write_text(ics, encoding="utf-8")
        return ha.mail(CFG["mail_service"], adres, onderwerp, tekst, str(pad) if pad else None)
    finally:
        if pad:
            try:
                pad.unlink()
            except OSError:
                pass


def _agenda_marker(uid: str) -> str:
    return f"Tennis Boeker ref: {uid}"


def synchroniseer(inv: dict) -> dict:
    """Brengt agenda en mail in lijn met inv['doel']. Geeft de bijgewerkte inv terug."""
    doel, gedaan = inv.get("doel"), inv.get("gedaan")
    sleutels = ("start", "partner", "baan")
    if doel and gedaan and all(doel.get(k) == gedaan.get(k) for k in sleutels):
        return inv                                                   # niets te doen
    meldingen = []

    # 1. oude agenda-afspraak weg (bij wijzigen of annuleren)
    if gedaan and gedaan.get("agenda"):
        if not ha.agenda_verwijder(_agenda_marker(gedaan.get("agenda_uid", inv["uid"])),
                                   f"{gedaan['start']}:00"):
            meldingen.append(f"Verwijder de agenda-afspraak '{_titel(gedaan)}' van "
                             f"{_wanneer(_start(gedaan))} zelf; automatisch wissen lukte niet.")

    # 2. oude mail annuleren als er niets meer is of de ontvanger verandert
    oud_adres = (gedaan or {}).get("email", "")
    nieuw_adres = partner_email(doel["partner"]) if doel else ""
    if gedaan and oud_adres and (not doel or oud_adres != nieuw_adres):
        inv["seq"] += 1
        if not _stuur_mail(inv, "CANCEL", gedaan, oud_adres):
            meldingen.append(f"Annuleringsmail naar {gedaan['partner']} versturen mislukte.")

    if not doel:
        inv["gedaan"] = None
        _meld(meldingen)
        return inv

    # 3. nieuwe afspraak
    nieuwe = dict(doel, email="", agenda=False)
    if nieuw_adres and ((oud_adres and oud_adres != nieuw_adres) or (not gedaan and inv["seq"] > 0)):
        inv["uid"], inv["seq"] = f"{uuid.uuid4()}@tennisboeker", 0         # nieuw id (andere ontvanger of na annulering)
    elif nieuw_adres and oud_adres:
        inv["seq"] += 1
    nieuwe["agenda_uid"] = inv["uid"]
    if ha.agenda_entity():
        titel = _titel(doel)
        start = _start(doel)
        eind = start + timedelta(hours=1)
        nieuwe["agenda"] = ha.agenda(titel, f"{start:%Y-%m-%d %H:%M:%S}", f"{eind:%Y-%m-%d %H:%M:%S}",
                                     f"Geboekt via Tennis Boeker.\n{_agenda_marker(inv['uid'])}",
                                     f"Baan {doel['baan']}" if doel.get("baan") else "")
        if not nieuwe["agenda"]:
            meldingen.append("De agenda-afspraak kon niet worden aangemaakt (controleer de instelling 'agenda').")
    if nieuw_adres:
        if _stuur_mail(inv, "REQUEST", doel, nieuw_adres):
            nieuwe["email"] = nieuw_adres
        else:
            meldingen.append(f"De uitnodiging naar {doel['partner']} kon niet worden verstuurd "
                             f"(controleer 'mail_service' en 'mijn_email').")
    elif mail_klaar():
        log(f"Geen e-mailadres bekend voor {doel['partner']} (instelling partner_emails): geen uitnodiging verstuurd.")
    inv["gedaan"] = nieuwe
    _meld(meldingen)
    return inv


def _meld(meldingen: list[str]) -> None:
    for m in meldingen:
        log(f"Uitnodiging: {m}")
    if meldingen:
        ha.meld("Tennis: agenda/uitnodiging", " ".join(meldingen))


# --------------------------------------------------------------------------- wachtrij
def _werker() -> None:
    while True:
        taak = _Q.get()
        try:
            taak()
        except Exception as e:
            log(f"Uitnodiging mislukt: {e}")
        finally:
            _Q.task_done()


def in_wachtrij(taak) -> None:
    global _THREAD
    if _THREAD is None or not _THREAD.is_alive():
        _THREAD = threading.Thread(target=_werker, daemon=True, name="uitnodiging")
        _THREAD.start()
    _Q.put(taak)


def wacht_klaar(timeout: float = 5.0) -> None:
    """Voor tests: wacht tot de wachtrij leeg is."""
    import time
    t0 = time.time()
    while _Q.unfinished_tasks and time.time() - t0 < timeout:
        time.sleep(0.05)
