"""
planner.py - plant boekingen in en voert ze op het juiste moment uit.

Begrippen:
  boeking (job)   één poging om op een datum/tijd een baan te boeken
  reserve         tweede job op een later uur; draait alleen als de hoofdboeking mislukt
  vaste boeking   (reeks) maakt elke week automatisch een job aan

Statussen: gepland, wacht (reserve), bezig, geboekt, mislukt, geannuleerd,
           niet nodig (reserve), overgeslagen (conflict), verlopen
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import boeker
import ha
from boeker import CFG, DAGEN, DATA, TZ, log, momenten, nu

PLANNEN = DATA / "plannen.json"
REEKSEN = DATA / "reeksen.json"
CLUB = DATA / "clubboekingen.json"
STAAT = DATA / "staat.json"
SLOT = threading.RLock()
STOP: dict[str, threading.Event] = {}
ACTIEF = ("gepland", "wacht", "bezig")
REPETITIE_MINUTEN = 15
DAGCHECK_UUR = 8


# --------------------------------------------------------------------------- opslag
def _lees(pad: Path, standaard):
    try:
        return json.loads(pad.read_text(encoding="utf-8"))
    except Exception:
        return standaard


def _schrijf(pad: Path, data) -> None:
    tmp = pad.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(pad)


def plannen() -> list[dict]:
    return _lees(PLANNEN, [])


def reeksen() -> list[dict]:
    return _lees(REEKSEN, [])


def club() -> dict:
    return _lees(CLUB, {"bijgewerkt": None, "boekingen": [], "fout": None})


def job(job_id: str) -> dict | None:
    return next((p for p in plannen() if p["id"] == job_id), None)


def werk_bij(job_id: str, **velden) -> None:
    with SLOT:
        lijst = plannen()
        for p in lijst:
            if p["id"] == job_id:
                p.update(velden)
        _schrijf(PLANNEN, lijst)


def dag_tekst(datum: str, tijd: str | None = None) -> str:
    d = datetime.strptime(datum, "%Y-%m-%d")
    return f"{DAGEN[d.weekday()]} {d:%d-%m}" + (f" {tijd}" if tijd else "")


# --------------------------------------------------------------------------- clubregels
def conflict(datum: str, tijd: str, negeer: tuple[str, ...] = ()) -> str | None:
    """Controleert de clubregels: max. N boekingen per dag en niet twee uur achter elkaar."""
    uur = int(tijd[:2])
    bezette = {}  # uur -> omschrijving
    for b in club()["boekingen"]:
        if b["datum"] == datum:
            bezette[int(b["tijd"][:2])] = f"een boeking om {b['tijd']}"
    for p in plannen():
        if (p["datum"] == datum and p["status"] in ("gepland", "bezig") and not p.get("test")
                and p["id"] not in negeer):
            bezette.setdefault(int(p["tijd"][:2]), f"al een geplande boeking om {p['tijd']}")
    if uur in bezette:
        return f"Je hebt op {dag_tekst(datum)} al {bezette[uur]}."
    for ander in (uur - 1, uur + 1):
        if ander in bezette:
            return (f"Op {dag_tekst(datum)} heb je {bezette[ander]}: dan speel je twee uur "
                    f"achter elkaar, dat staat de club niet toe.")
    if len(bezette) >= CFG["max_boekingen_per_dag"]:
        return (f"Je hebt op {dag_tekst(datum)} al {len(bezette)} boekingen "
                f"(maximaal {CFG['max_boekingen_per_dag']} per dag).")
    return None


# --------------------------------------------------------------------------- inplannen
def plan(datum: str, tijd: str, partner: str, test: bool = False,
         reserve_tijd: str | None = None, reeks: str | None = None,
         stil: bool = False, voorkeursbaan: int | None = None) -> str:
    partner = (partner or CFG["standaard_partner"] or "").strip()
    if not partner:
        raise ValueError("Kies een medespeler (of vul standaard_partner in bij de instellingen).")
    speelmoment, _, start = momenten(datum, tijd)
    if speelmoment <= nu():
        raise ValueError("Dat moment ligt in het verleden.")
    if reserve_tijd and reserve_tijd <= tijd:
        raise ValueError("De reservetijd moet later zijn dan de gewenste tijd.")
    with SLOT:
        lijst = plannen()
        for p in lijst:
            if (p["datum"], p["tijd"]) == (datum, tijd) and p["status"] in ACTIEF:
                raise ValueError(f"Voor {dag_tekst(datum, tijd)} staat al een boeking ingepland.")
        if not test:
            fout = conflict(datum, tijd)
            if fout:
                raise ValueError(fout)
        hoofd = {"id": uuid.uuid4().hex[:8], "datum": datum, "tijd": tijd, "partner": partner,
                 "test": test, "status": "gepland", "reeks": reeks,
                 "voorkeursbaan": voorkeursbaan,
                 "aangemaakt": f"{nu():%d-%m %H:%M}"}
        nieuw = [hoofd]
        if reserve_tijd:
            if not test and (fout := conflict(datum, reserve_tijd)):
                raise ValueError(f"Reservetijd {reserve_tijd}: {fout}")
            reserve = dict(hoofd, id=uuid.uuid4().hex[:8], tijd=reserve_tijd, status="wacht",
                           reserve_van=hoofd["id"])
            hoofd["reserve_id"] = reserve["id"]
            nieuw.append(reserve)
        _schrijf(PLANNEN, lijst + nieuw)
    for j in nieuw:
        start_thread(j)
    wanneer = "nu direct (de baan is al open)" if start <= nu() else \
        f"{DAGEN[start.weekday()]} {start:%d-%m %H:%M}"
    tekst = (f"{'Test: ' if test else ''}{dag_tekst(datum, tijd)} met {partner}"
             f"{f', reserve {reserve_tijd}' if reserve_tijd else ''}. Start: {wanneer}.")
    log(f"Ingepland: {tekst}")
    if not stil:
        ha.meld("Tennisboeking ingepland", tekst, [(f"ANNULEER_{hoofd['id']}", "Annuleren")])
    werk_sensoren_bij()
    return f"Ingepland: {tekst}"


def annuleer(job_id: str, reden: str = "geannuleerd") -> None:
    j = job(job_id)
    if not j:
        return
    for jid in (job_id, j.get("reserve_id")):
        if not jid:
            continue
        STOP.setdefault(jid, threading.Event()).set()
        k = job(jid)
        if k and k["status"] in ("gepland", "wacht"):
            werk_bij(jid, status="geannuleerd")
    log(f"Boeking {dag_tekst(j['datum'], j['tijd'])} {reden}.")
    werk_sensoren_bij()


def verwijder(job_id: str) -> None:
    with SLOT:
        _schrijf(PLANNEN, [p for p in plannen()
                           if not (p["id"] == job_id and p["status"] not in ACTIEF)])


# --------------------------------------------------------------------------- uitvoeren
def _wacht(moment: datetime, stop: threading.Event) -> bool:
    """Wacht tot moment. False als de boeking intussen is geannuleerd."""
    try:
        boeker.wacht_tot(moment, "", stop.is_set)
        return True
    except RuntimeError:
        return False


def voer_uit(j: dict) -> None:
    stop = STOP.setdefault(j["id"], threading.Event())
    speelmoment, opening, start = momenten(j["datum"], j["tijd"])

    if j.get("reserve_van"):
        if not _wacht(start, stop):
            return
        while (hoofd := job(j["reserve_van"])) and hoofd["status"] in ("gepland", "bezig"):
            if stop.wait(5):
                return
        if not hoofd or hoofd["status"] == "geboekt":
            werk_bij(j["id"], status="niet nodig", resultaat="Hoofdboeking is gelukt.")
            werk_sensoren_bij()
            return
        if hoofd["status"] == "geannuleerd":
            werk_bij(j["id"], status="geannuleerd")
            return
        werk_bij(j["id"], status="gepland")
        log(f"Hoofdboeking mislukt - reservetijd {j['tijd']} wordt geprobeerd.")
    else:
        repetitie = opening - timedelta(minutes=REPETITIE_MINUTEN)
        if not j.get("test") and repetitie - nu() > timedelta(minutes=1):
            if not _wacht(repetitie, stop):
                return
            ok, tekst = boeker.generale_repetitie(j["partner"])
            werk_bij(j["id"], repetitie=("OK" if ok else tekst))
            log(f"Generale repetitie {dag_tekst(j['datum'], j['tijd'])}: {tekst}")
            if not ok:
                ha.meld("Let op: tennisboeking in gevaar",
                        f"Controle voor {dag_tekst(j['datum'], j['tijd'])} mislukt: {tekst} "
                        f"De baan gaat over {REPETITIE_MINUTEN} minuten open; de add-on probeert "
                        f"het wel, maar boek eventueel zelf.")
        if not _wacht(start, stop):
            return

    werk_bij(j["id"], status="bezig")
    werk_sensoren_bij()
    u = boeker.boek(j["datum"], j["tijd"], j["partner"], j.get("test", False), stop.is_set,
                    j.get("voorkeursbaan"))
    if stop.is_set():
        werk_bij(j["id"], status="geannuleerd", resultaat=u["tekst"])
        return
    werk_bij(j["id"], status="geboekt" if u["gelukt"] else "mislukt", resultaat=u["tekst"],
             screenshot=u["screenshot"].name if u["screenshot"] else None, baan=u["baan"])

    knoppen = []
    if u["gelukt"] and not j.get("test"):
        if u["clubboekingen"] is not None:
            _bewaar_club(u["clubboekingen"])
            rid = next((b["id"] for b in u["clubboekingen"]
                        if b["datum"] == j["datum"] and b["tijd"] == j["tijd"]), None)
            if rid:
                knoppen.append((f"CLUBANNULEER_{rid}", "Baan annuleren"))
        eind = speelmoment + timedelta(hours=1)
        ha.agenda(f"Tennis met {u['partner']} (baan {u['baan']})",
                  f"{speelmoment:%Y-%m-%d %H:%M:%S}", f"{eind:%Y-%m-%d %H:%M:%S}",
                  "Geboekt door Tennis Boeker")
    titel = "Tennisbaan geboekt" if u["gelukt"] else "Tennisbaan NIET geboekt"
    if not u["gelukt"] and j.get("reserve_id"):
        titel += " - reservetijd volgt"
    ha.meld(titel, u["tekst"], knoppen)
    werk_sensoren_bij()


def start_thread(j: dict) -> None:
    threading.Thread(target=voer_uit, args=(j,), daemon=True, name=j["id"]).start()


# --------------------------------------------------------------------------- vaste boekingen
def maak_reeks(datum: str, tijd: str, partner: str, reserve_tijd: str | None,
               voorkeursbaan: int | None = None) -> str:
    partner = (partner or CFG["standaard_partner"] or "").strip()
    weekdag = datetime.strptime(datum, "%Y-%m-%d").weekday()
    reeks = {"id": uuid.uuid4().hex[:8], "weekdag": weekdag, "tijd": tijd, "partner": partner,
             "reserve_tijd": reserve_tijd, "voorkeursbaan": voorkeursbaan, "actief": True,
             "sinds": f"{nu():%d-%m-%Y}"}
    tekst = plan(datum, tijd, partner, reserve_tijd=reserve_tijd, reeks=reeks["id"], stil=True,
                 voorkeursbaan=voorkeursbaan)
    with SLOT:
        _schrijf(REEKSEN, reeksen() + [reeks])
    ha.meld("Vaste tennisboeking ingesteld",
            f"Elke {DAGEN[weekdag]} om {tijd} met {partner}. Eerste: {tekst.removeprefix('Ingepland: ')}")
    return f"Vaste boeking ingesteld: elke {DAGEN[weekdag]} om {tijd} met {partner}."


def stop_reeks(reeks_id: str) -> None:
    with SLOT:
        lijst = reeksen()
        for r in lijst:
            if r["id"] == reeks_id:
                r["actief"] = False
        _schrijf(REEKSEN, lijst)
    for p in plannen():
        if p.get("reeks") == reeks_id and p["status"] == "gepland" and not p.get("reserve_van"):
            annuleer(p["id"], "geannuleerd (vaste boeking gestopt)")


def vul_reeksen() -> None:
    """Maakt voor elke vaste boeking de eerstvolgende boeking aan zodra die in beeld komt."""
    for r in [r for r in reeksen() if r["actief"]]:
        for dagen in range(0, CFG["dagen_vooruit"] + 8):
            d = (nu() + timedelta(days=dagen)).date()
            if d.weekday() != r["weekdag"]:
                continue
            datum = d.strftime("%Y-%m-%d")
            _, opening, _ = momenten(datum, r["tijd"])
            if opening <= nu():
                continue                     # te laat voor deze week
            if any(p.get("reeks") == r["id"] and p["datum"] == datum for p in plannen()):
                continue                     # bestaat al (of is bewust geannuleerd)
            try:
                plan(datum, r["tijd"], r["partner"], reserve_tijd=r.get("reserve_tijd"),
                     reeks=r["id"], voorkeursbaan=r.get("voorkeursbaan"))
            except ValueError as e:
                with SLOT:
                    _schrijf(PLANNEN, plannen() + [{
                        "id": uuid.uuid4().hex[:8], "datum": datum, "tijd": r["tijd"],
                        "partner": r["partner"], "status": "overgeslagen", "reeks": r["id"],
                        "resultaat": str(e), "aangemaakt": f"{nu():%d-%m %H:%M}"}])
                ha.meld("Vaste tennisboeking overgeslagen", f"{dag_tekst(datum, r['tijd'])}: {e}")
            break


# --------------------------------------------------------------------------- clubboekingen
def _bewaar_club(boekingen: list[dict], fout: str | None = None) -> None:
    oud = club()
    _schrijf(CLUB, {"bijgewerkt": f"{nu():%d-%m %H:%M}" if fout is None else oud["bijgewerkt"],
                    "boekingen": boekingen if fout is None else oud["boekingen"], "fout": fout})


def ververs_club() -> None:
    try:
        _bewaar_club(boeker.haal_clubboekingen())
    except Exception as e:
        _bewaar_club([], fout=str(e))
        log(f"Boekingen ophalen van de clubsite mislukt: {e}")
    werk_sensoren_bij()


def annuleer_club(reservation_id: str) -> str:
    b = next((b for b in club()["boekingen"] if b["id"] == reservation_id), None)
    omschrijving = dag_tekst(b["datum"], b["tijd"]) if b else "boeking"
    _bewaar_club(boeker.annuleer_clubboeking(reservation_id))
    ha.meld("Tennisbaan geannuleerd", f"{omschrijving} is geannuleerd op de clubsite.")
    werk_sensoren_bij()
    return f"{omschrijving} is geannuleerd op de clubsite."


def drukte() -> bool:
    """True als er nu of binnenkort geboekt wordt - dan geen extra browsers starten."""
    for p in plannen():
        if p["status"] == "bezig":
            return True
        if p["status"] == "gepland":
            _, _, start = momenten(p["datum"], p["tijd"])
            if timedelta(0) <= start - nu() <= timedelta(minutes=10):
                return True
    return False


# --------------------------------------------------------------------------- knoppen in meldingen
def verwerk_knop(actie: str) -> None:
    if actie.startswith("ANNULEER_"):
        annuleer(actie.removeprefix("ANNULEER_"), "geannuleerd via melding")
        ha.meld("Tennisboeking geannuleerd", "De geplande boeking is geannuleerd.")
    elif actie.startswith("CLUBANNULEER_"):
        try:
            annuleer_club(actie.removeprefix("CLUBANNULEER_"))
        except Exception as e:
            ha.meld("Annuleren mislukt", f"Kon de baan niet annuleren: {e}")


# --------------------------------------------------------------------------- sensoren
def _iso(moment: datetime) -> str:
    return moment.replace(tzinfo=TZ).isoformat()


def werk_sensoren_bij() -> None:
    try:
        toekomst = [b for b in club()["boekingen"]
                    if datetime.strptime(f"{b['datum']} {b['tijd']}", "%Y-%m-%d %H:%M") > nu()]
        if toekomst:
            b = toekomst[0]
            sm = datetime.strptime(f"{b['datum']} {b['tijd']}", "%Y-%m-%d %H:%M")
            ha.zet_sensor("sensor.tennis_volgende_baan", _iso(sm), {
                "friendly_name": "Volgende tennisbaan", "icon": "mdi:tennis",
                "device_class": "timestamp", "baan": b["baan"], "eind": b["eind"],
                "omschrijving": f"{dag_tekst(b['datum'], b['tijd'])}, {b['baan']}",
                "aantal": len(toekomst)})
        else:
            ha.zet_sensor("sensor.tennis_volgende_baan", "unknown", {
                "friendly_name": "Volgende tennisbaan", "icon": "mdi:tennis",
                "device_class": "timestamp", "aantal": 0})
        gepland = sorted([p for p in plannen() if p["status"] in ("gepland", "bezig")
                          and not p.get("test")], key=lambda p: (p["datum"], p["tijd"]))
        if gepland:
            p = gepland[0]
            sm, opening, _ = momenten(p["datum"], p["tijd"])
            ha.zet_sensor("sensor.tennis_volgende_boekpoging", _iso(sm), {
                "friendly_name": "Volgende automatische boeking", "icon": "mdi:calendar-clock",
                "device_class": "timestamp", "medespeler": p["partner"], "status": p["status"],
                "opent": _iso(opening), "omschrijving": f"{dag_tekst(p['datum'], p['tijd'])} met {p['partner']}",
                "aantal": len(gepland)})
        else:
            ha.zet_sensor("sensor.tennis_volgende_boekpoging", "unknown", {
                "friendly_name": "Volgende automatische boeking", "icon": "mdi:calendar-clock",
                "device_class": "timestamp", "aantal": 0})
    except Exception as e:
        log(f"Sensoren bijwerken mislukt: {e}")


# --------------------------------------------------------------------------- achtergrond
def instellingen_compleet() -> bool:
    return all(CFG.get(k) for k in ("club_website", "gebruiker", "wachtwoord"))


def inlog_check(melden: bool = True) -> tuple[bool, str]:
    """Test het inloggen en bewaart de uitkomst (tegel 'Inloggen bij de club')."""
    ok, tekst = boeker.test_inloggen()
    log(f"Inlogcheck: {tekst}")
    staat = _lees(STAAT, {})
    staat.update(laatste_dagcheck=f"{nu():%Y-%m-%d}", dagcheck_ok=ok, dagcheck_tekst=tekst,
                 dagcheck_tijd=f"{nu():%d-%m %H:%M}")
    _schrijf(STAAT, staat)
    if not ok and melden:
        ha.meld("Tennis Boeker: inloggen werkt niet",
                f"{tekst} Controleer je gebruiker/wachtwoord in de add-on-instellingen, "
                f"anders mislukken geplande boekingen.")
    return ok, tekst


def staat() -> dict:
    return _lees(STAAT, {})


def achtergrond() -> None:
    teller = 0
    while True:
        try:
            if teller % 10 == 0:
                vul_reeksen()
            if teller % 5 == 0:
                werk_sensoren_bij()
            s = staat()
            if (nu().hour >= DAGCHECK_UUR and s.get("laatste_dagcheck") != f"{nu():%Y-%m-%d}"
                    and instellingen_compleet() and not drukte()):
                inlog_check()
            if teller % 30 == 0 and teller and not drukte():
                ververs_club()
        except Exception as e:
            log(f"Achtergrondtaak fout: {e}")
        teller += 1
        time.sleep(60)


def opstarten() -> None:
    """Na een (her)start: planning herstellen en achtergrondtaken starten."""
    s = staat()
    if s.get("dagcheck_ok") is False:          # vorige check mislukt: na herstart opnieuw testen
        s.pop("laatste_dagcheck", None)
        _schrijf(STAAT, s)
    with SLOT:
        lijst = plannen()
        for p in lijst:
            if p["status"] == "bezig":
                p["status"] = "mislukt"
                p["resultaat"] = "Onderbroken door een herstart van de add-on."
            elif p["status"] in ("gepland", "wacht"):
                if momenten(p["datum"], p["tijd"])[0] <= nu():
                    p["status"] = "verlopen"
        _schrijf(PLANNEN, lijst)
    for p in plannen():
        if p["status"] in ("gepland", "wacht"):
            start_thread(p)
    threading.Thread(target=ververs_club, daemon=True).start()
    threading.Thread(target=achtergrond, daemon=True, name="achtergrond").start()
    ha.luister_naar_knoppen(verwerk_knop)
