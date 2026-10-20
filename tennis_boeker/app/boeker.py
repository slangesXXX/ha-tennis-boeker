"""
boeker.py - boekt een tennisbaan bij een KNLTB.Club-vereniging met een headless browser.
Onderdeel van de Home Assistant add-on 'Tennis Boeker'.

Boekingsflow van de site (vastgelegd 19-10-2026):
  /me/ReservationsPlayers  -> medespeler toevoegen  -> Volgende
  /me/ReservationsDay      -> dagdeel kiezen        -> Volgende
  /me/ReservationsCourt    -> tijdslot op een baan  -> Volgende
  /me/ReservationsConfirm  -> Bevestigen (Ajax: /Ajax/Profile/SaveReservation)
"""
from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import Page, TimeoutError as PWTimeout, sync_playwright

DATA = Path("/data") if Path("/data").exists() else Path(__file__).resolve().parent / "data"
DATA.mkdir(exist_ok=True)
LOGMAP = DATA / "logs"
LOGMAP.mkdir(exist_ok=True)
SESSIE = DATA / "sessie.json"
TZ = ZoneInfo("Europe/Amsterdam")

STANDAARD = {
    "club_website": "",
    "gebruiker": "",
    "wachtwoord": "",
    "login_met": "Bondsnummer",
    "standaard_partner": "",
    "reserve_partners": [],
    "extra_partners": [],
    "notify_service": "",
    "agenda": "",
    "max_boekingen_per_dag": 2,
    "voorkeursbaan": 0,
    "aantal_banen": 6,
    "max_minuten_proberen": 5,
    "dagen_vooruit": 3,
    "start_seconden_vooraf": 60,
    "verversen_seconden_voor_opening": 3,
    "verversen_seconden": 0.3,
    "foutwoorden_baan_bezet": ["bezet", "niet beschikbaar", "al gereserveerd", "niet meer vrij"],
    "foutwoorden_partner": ["medespeler", "speler", "partner"],
}


def laad_cfg() -> dict:
    cfg = dict(STANDAARD)
    opties = DATA / "options.json"
    if opties.exists():
        for k, v in json.loads(opties.read_text(encoding="utf-8")).items():
            if isinstance(v, str):
                v = v.strip().strip('"').strip("'").strip()   # '""' ingevuld = leeg
            if v not in (None, ""):
                cfg[k] = v
    return cfg


CFG = laad_cfg()

def club_basis() -> str:
    url = str(CFG.get("club_website") or "").strip().rstrip("/")
    if url and not url.startswith("http"):
        url = "https://" + url
    if url:                                    # alleen het domein houden, ook als iemand
        schema, rest = url.split("://", 1)     # een diepere link plakt (…/me/Reservations)
        url = f"{schema}://{rest.split('/', 1)[0]}"
    return url


BASIS = club_basis()
URL_SPELERS = BASIS + "/me/ReservationsPlayers"
URL_DAG = BASIS + "/me/ReservationsDay"
URL_OVERZICHT = BASIS + "/me/Reservations"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d  %(message)s",
    datefmt="%d-%m %H:%M:%S",
    handlers=[logging.StreamHandler(),
              logging.FileHandler(LOGMAP / "boeker.log", encoding="utf-8")],
)
logging.Formatter.converter = lambda *a: datetime.now(TZ).timetuple()
log = logging.info

DAGEN = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]


class PartnerBezet(Exception):
    """Site weigert de medespeler (bijv. die speelt al het uur ervoor/erna)."""


class BaanBezet(Exception):
    """Baan net door iemand anders weggekaapt."""


class SlotNietGekozen(Exception):
    """Pagina was nog niet klaar om een slot te kiezen - gewoon opnieuw proberen."""


class Geweigerd(Exception):
    """Site weigert de boeking om een andere reden (bijv. jouw eigen limiet)."""


def nu() -> datetime:
    """Huidige Nederlandse tijd (zonder tijdzone-info), los van de tijdzone van de container."""
    return datetime.now(TZ).replace(tzinfo=None)


def norm(tekst: str) -> str:
    """'Jan  Jänsen' -> 'jan jansen' (zonder accenten/dubbele spaties)."""
    t = unicodedata.normalize("NFKD", tekst)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.lower().split())


def dagdeel_uur(uur: int) -> int:
    """Site verdeelt de dag in Ochtend (8), Middag (12) en Avond (18)."""
    return 8 if uur < 12 else 12 if uur < 18 else 18


def maak_screenshot(page: Page, naam: str) -> Path | None:
    pad = LOGMAP / f"{nu():%Y%m%d_%H%M%S}_{naam}.png"
    try:
        page.screenshot(path=str(pad), full_page=True)
        return pad
    except Exception:
        return None


def wacht_tot(moment: datetime, label: str, gestopt=lambda: False) -> None:
    while (rest := (moment - nu()).total_seconds()) > 0:
        if gestopt():
            raise RuntimeError("GEANNULEERD")
        time.sleep(min(rest, 1.0 if rest > 5 else 0.05))


# --------------------------------------------------------------------------- site-acties
def weiger_cookies(page: Page) -> None:
    knop = page.get_by_text("Weigeren", exact=True)
    try:
        if knop.count() and knop.first.is_visible():
            knop.first.click(timeout=1000)
    except Exception:
        pass


def is_ingelogd(page: Page) -> bool:
    return page.locator('a[href="/mijn/logoff"]').count() > 0


def log_in(page: Page) -> None:
    page.goto(URL_OVERZICHT, wait_until="domcontentloaded")
    weiger_cookies(page)
    if is_ingelogd(page):
        log("Al ingelogd (opgeslagen sessie).")
        return
    log("Inloggen...")
    if not CFG.get("gebruiker") or not CFG.get("wachtwoord"):
        raise RuntimeError("Niet ingelogd en geen gebruiker/wachtwoord in de add-on-instellingen")
    try:
        page.get_by_text(CFG["login_met"], exact=True).first.click(timeout=2000)
    except Exception:
        pass
    pw = page.locator("input[type=password]").first
    gebruiker = page.locator(
        "form:has(input[type=password]) input:not([type=hidden]):not([type=password])"
        ":not([type=radio]):not([type=checkbox])").first
    gebruiker.fill(str(CFG["gebruiker"]))
    pw.fill(str(CFG["wachtwoord"]))
    pw.press("Enter")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(1500)
    if page.locator("input[type=password]").count() and not is_ingelogd(page):
        try:  # Enter werkte niet: klik de knop
            page.get_by_role("button", name=re.compile("log ?in", re.I)).first.click(timeout=3000)
            page.wait_for_load_state("domcontentloaded")
        except Exception:
            pass
    page.goto(URL_OVERZICHT, wait_until="domcontentloaded")
    if not is_ingelogd(page):
        raise RuntimeError("Inloggen mislukt - controleer gebruiker/wachtwoord in de add-on-instellingen")
    log("Ingelogd.")


def zet_medespeler(page: Page, partner: str) -> None:
    """Zorgt dat precies deze medespeler geselecteerd is en gaat naar de dagkeuze."""
    page.goto(URL_SPELERS, wait_until="domcontentloaded")
    weiger_cookies(page)
    if not is_ingelogd(page):
        log_in(page)
        page.goto(URL_SPELERS, wait_until="domcontentloaded")
    doel = norm(partner)
    gekozen = page.locator("#youPlayWith li")
    # Verwijder andere medespelers die nog in de sessie staan
    for i in range(gekozen.count() - 1, -1, -1):
        item = gekozen.nth(i)
        if norm(item.inner_text()) != doel:
            log(f"Verwijder medespeler: {item.inner_text().strip()}")
            item.locator("a.removePlayer").click()
            page.wait_for_timeout(800)
    if not any(norm(t) == doel for t in page.locator("#youPlayWith li").all_inner_texts()):
        log(f"Medespeler zoeken: {partner}")
        veld = page.locator("#searchPlayerText")
        veld.fill("")
        veld.type(norm(partner), delay=20)   # zonder accenten zoeken vindt ook namen mét accenten
        resultaat = page.locator(".searchresults .addPlayer").filter(
            has_text=partner.split()[0])
        resultaat.first.wait_for(state="visible", timeout=8000)
        treffers = [i for i in range(resultaat.count())
                    if norm(resultaat.nth(i).inner_text()) == doel]
        if not treffers:
            raise RuntimeError(f"Medespeler '{partner}' niet gevonden in de ledenlijst")
        resultaat.nth(treffers[0]).click()
        page.locator("#youPlayWith li").filter(has_text=partner.split()[0]).first.wait_for(
            timeout=8000)
    log(f"Medespeler staat klaar: {partner}")


def open_baanoverzicht(page: Page, speelmoment: datetime) -> bool:
    """Dagkeuze-pagina: kies dag + dagdeel en ga naar het baanoverzicht.
    Geeft False als dat dagdeel nog niet open is."""
    page.goto(URL_DAG, wait_until="domcontentloaded")
    if "ReservationsPlayers" in page.url:     # sessie kwijt -> opnieuw beginnen
        raise RuntimeError("SESSIE_KWIJT")
    dag = speelmoment.strftime("%Y-%m-%d")
    sel = f'.daypart[data-date^="{dag}T{dagdeel_uur(speelmoment.hour):02d}:"]'
    for _ in range(3):                        # zo nodig naar de volgende week bladeren
        if page.locator(sel).count():
            break
        volgende = page.locator(".changeWeek").last
        if not volgende.count():
            break
        volgende.click()
        page.wait_for_timeout(700)
    dagdeel = page.locator(sel).first
    if not dagdeel.count():
        raise RuntimeError(f"Dag {dag} niet gevonden in de dagkeuze")
    if dagdeel.get_attribute("data-availability") != "True":
        return False
    # Gekozen dagdeel direct in het formulier zetten (wat de site-JavaScript ook doet),
    # zodat het niet uitmaakt of de scripts van de site al geladen zijn.
    page.locator("#dayForm #selectedDate").evaluate(
        "(el, v) => el.value = v", dagdeel.get_attribute("data-date"))
    with page.expect_navigation(wait_until="domcontentloaded"):
        page.locator("#dayForm").evaluate("f => f.submit()")
    # Wachten tot het baanrooster er staat (kan na het laden nog worden opgebouwd)
    try:
        page.locator(".timeincourt").first.wait_for(state="attached", timeout=5000)
    except PWTimeout:
        pass
    return True


def vrije_banen(page: Page, speelmoment: datetime,
                voorkeur: int | None = None) -> list[tuple[int, object]]:
    """Alle vrije banen op dit moment: eerst de voorkeursbaan (als ingesteld), dan de rest.
    Zoekt op de tijd in de keuzelijst van elk slot (bijv. '2026-10-23 12:00')."""
    prefix = f"{speelmoment:%Y-%m-%d %H:%M}"
    gevonden = page.evaluate("""(prefix) => {
        const uit = [];
        document.querySelectorAll('select[data-court]').forEach(sel => {
            if (sel.disabled || sel.closest('.timeincourt.disabled')) return;
            const opt = [...sel.options].find(o => o.value.startsWith(prefix));
            if (!opt) return;
            const knop = sel.closest('.court')?.querySelector('button');
            const m = (knop?.textContent || '').match(/Baan\\s*(\\d+)/);
            uit.push({baan: m ? parseInt(m[1]) : 0, court: sel.dataset.court});
        });
        return uit;
    }""", prefix)
    vrij = {}
    for g in gevonden:
        if g["baan"] and g["baan"] not in vrij:
            vrij[g["baan"]] = page.locator(
                f'select[data-court="{g["court"]}"]:has(option[value^="{prefix}"])').first
    if voorkeur is None:
        voorkeur = int(CFG.get("voorkeursbaan") or 0)
    return [(n, vrij[n]) for n in sorted(vrij, key=lambda n: (n != voorkeur, n))]


def melding_van_site(page: Page) -> str:
    """Zoekt een foutmelding die de clubsite toont (notify/alert) en bewaart de pagina."""
    try:
        tekst = page.evaluate("""() => {
            const uit = [];
            document.querySelectorAll('script').forEach(s => {
                for (const m of s.textContent.matchAll(/notify\\(\\s*['"]([^'"]+)['"]/g)) uit.push(m[1]); });
            document.querySelectorAll('.alert, .notifyjs-container, .validation-summary-errors, .field-validation-error')
                .forEach(el => { const t = el.textContent.trim(); if (t) uit.push(t); });
            return [...new Set(uit)].join(' | ');
        }""")
    except Exception:
        tekst = ""
    try:
        (LOGMAP / f"{nu():%Y%m%d_%H%M%S}_terugverwezen.html").write_text(page.content(), encoding="utf-8")
        maak_screenshot(page, "terugverwezen")
    except Exception:
        pass
    return f"Melding van de site: {tekst}" if tekst else "Geen melding van de site gevonden."


def rooster_info(page: Page, speelmoment: datetime) -> str:
    """Korte beschrijving van wat er op het baanoverzicht staat (voor het logboek)."""
    try:
        return page.evaluate("""(dag) => {
            const sel = [...document.querySelectorAll('select[data-court]')];
            const tijden = new Set();
            sel.forEach(s => [...s.options].forEach(o => { if (o.value.startsWith(dag)) tijden.add(o.value.slice(11,16)); }));
            const datum = document.querySelector('.selectdate .page-link.disabled')?.textContent.trim() || '?';
            return `pagina ${location.pathname}, datum ${datum}, ${sel.length} slots, vrij: ${[...tijden].sort().join(' ') || 'geen'}`;
        }""", f"{speelmoment:%Y-%m-%d}")
    except Exception as e:
        return f"(rooster niet leesbaar: {e})"


def kies_slot_en_bevestig(page: Page, select, speelmoment: datetime, partner: str,
                          test: bool) -> None:
    # Slot kiezen: precies de velden invullen die de site-JavaScript ook invult
    # (baan-id, begin- en eindtijd in UTC), zodat het niet uitmaakt of die scripts al klaar zijn.
    gegevens = select.evaluate("""sel => { const o = sel.options[0];
        return {court: sel.dataset.court, start: o.value, eind: o.dataset.endTime}; }""")
    try:
        start_utc = datetime.fromisoformat(gegevens["start"]).astimezone(timezone.utc)
        eind_utc = datetime.fromisoformat(gegevens["eind"]).astimezone(timezone.utc)
    except (TypeError, ValueError):
        raise SlotNietGekozen(f"Onbekend tijdformaat: {gegevens}")
    page.evaluate("""([c, s, e]) => {
        document.querySelector('#selectedCourt').value = c;
        document.querySelector('#timeForm #selectedDate').value = s;
        document.querySelector('#selectedEndDate').value = e; }""",
        [gegevens["court"], f"{start_utc:%Y-%m-%dT%H:%M:%SZ}", f"{eind_utc:%Y-%m-%dT%H:%M:%SZ}"])
    with page.expect_navigation(wait_until="domcontentloaded"):
        page.locator("#timeForm").evaluate("f => f.submit()")
    if "ReservationsConfirm" not in page.url:
        raise SlotNietGekozen(f"Clubsite stuurde terug naar {page.url.split('.nl')[-1] or '/'} "
                              f"(verstuurd: baan-id {gegevens['court'][:8]}…, "
                              f"{start_utc:%H:%M}-{eind_utc:%H:%M} UTC). "
                              f"{melding_van_site(page)}")
    tekst = norm(page.locator("body").inner_text())
    verwacht = f"{speelmoment:%d-%m-%Y} van {speelmoment:%H:%M}"
    if verwacht not in tekst:
        raise RuntimeError(f"Bevestigpagina toont niet {verwacht} - gestopt voor de zekerheid")
    if norm(partner) not in tekst:
        raise RuntimeError("SESSIE_KWIJT")   # medespeler niet meer geselecteerd
    if test:
        log("TESTMODUS: gestopt vlak voor 'Bevestigen'.")
        return
    # 'Bevestigen' werkt via JavaScript van de site: wachten tot die geladen is
    page.wait_for_load_state("load")
    page.wait_for_function("() => window.jQuery !== undefined", timeout=10000)
    with page.expect_response(lambda r: "SaveReservation" in r.url, timeout=15000) as info:
        page.locator("#confirmReservationButton").click()
    antwoord = info.value.text()
    if "Guid" in antwoord:
        return
    fout = antwoord.replace('"', "").strip() or f"HTTP {info.value.status}"
    f = norm(fout)
    if any(w in f for w in CFG["foutwoorden_baan_bezet"]):
        raise BaanBezet(fout)
    achternaam = norm(partner).split()[-1]
    if achternaam in f or any(w in f for w in CFG["foutwoorden_partner"]):
        raise PartnerBezet(fout)
    raise Geweigerd(fout)


def probeer_te_boeken(page: Page, speelmoment: datetime, partners: list[str],
                      deadline: datetime, test: bool,
                      voorkeur: int | None = None) -> tuple[int, str]:
    poging = 0
    partner_idx = 0
    mislukte_banen: set[int] = set()
    onbekende_fouten: list[str] = []
    slotfouten = 0
    laatste_slotfout = ""
    while nu() < deadline:
        if partner_idx >= len(partners):
            raise RuntimeError("Geen enkele medespeler kon mee. Meldingen van de site: "
                               + " | ".join(onbekende_fouten))
        partner = partners[partner_idx]
        poging += 1
        try:
            if not open_baanoverzicht(page, speelmoment):
                if poging % 20 == 1:
                    log(f"Dagdeel nog niet open (poging {poging})")
                time.sleep(CFG["verversen_seconden"])
                continue
            vrij = [(n, s) for n, s in vrije_banen(page, speelmoment, voorkeur)
                    if n not in mislukte_banen]
            if not vrij:
                if poging % 20 == 1:
                    log(f"Nog geen vrije baan om {speelmoment:%H:%M} (poging {poging}) - "
                        f"{rooster_info(page, speelmoment)}")
                time.sleep(CFG["verversen_seconden"])
                continue
            baan, select = vrij[0]
            log(f"Baan {baan} vrij om {speelmoment:%H:%M} - boeken met {partner}")
            kies_slot_en_bevestig(page, select, speelmoment, partner, test)
            return baan, partner
        except SlotNietGekozen as e:
            slotfouten += 1
            if slotfouten <= 3 or slotfouten % 10 == 0:
                log(f"Slot kiezen lukte niet (keer {slotfouten}), opnieuw: {e}")
            laatste_slotfout = str(e)
            time.sleep(min(2.0, 0.3 * slotfouten))
        except BaanBezet as e:
            log(f"Baan net weg: {e}")
            mislukte_banen.add(baan)
        except PartnerBezet as e:
            log(f"Medespeler {partner} geweigerd: {e}")
            onbekende_fouten.append(f"{partner}: {e}")
            partner_idx += 1
            mislukte_banen.clear()
            if partner_idx < len(partners):
                zet_medespeler(page, partners[partner_idx])
        except Geweigerd as e:
            # Onbekende weigering: met een andere medespeler proberen kan helpen,
            # anders ligt het aan jouw eigen limiet en heeft doorgaan geen zin.
            log(f"Site weigert boeking: {e}")
            onbekende_fouten.append(f"{partner}: {e}")
            partner_idx += 1
            if partner_idx < len(partners):
                zet_medespeler(page, partners[partner_idx])
        except RuntimeError as e:
            if str(e) != "SESSIE_KWIJT":
                raise
            log("Sessie/medespeler kwijt - opnieuw klaarzetten")
            zet_medespeler(page, partner)
        except PWTimeout as e:
            log(f"Pagina reageerde te traag, opnieuw: {str(e).splitlines()[0]}")
    if slotfouten:
        raise RuntimeError(f"Er waren wel vrije banen, maar de clubsite accepteerde de keuze niet "
                           f"({slotfouten} keer). Laatste: {laatste_slotfout}")
    raise RuntimeError(f"Geen vrije baan kunnen boeken binnen {CFG['max_minuten_proberen']} "
                       f"minuten ({poging} pogingen)"
                       + (". Meldingen: " + " | ".join(onbekende_fouten) if onbekende_fouten else ""))


# --------------------------------------------------------------------------- hoofdfuncties
from contextlib import contextmanager


@contextmanager
def browser_pagina(timeout_ms: int = 10000):
    """Opent een headless browser met de opgeslagen inlogsessie en geeft een pagina."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
        ctx = browser.new_context(storage_state=str(SESSIE) if SESSIE.exists() else None,
                                  locale="nl-NL", timezone_id="Europe/Amsterdam",
                                  viewport={"width": 1280, "height": 1000})
        page = ctx.new_page()
        page.set_default_timeout(timeout_ms)
        try:
            yield page
        finally:
            try:
                ctx.storage_state(path=str(SESSIE))
            except Exception:
                pass
            browser.close()


def ingelogd_op(page: Page) -> None:
    if not BASIS:
        raise RuntimeError("Geen club_website ingevuld in de add-on-instellingen.")
    log_in(page)


def momenten(datum: str, tijd: str) -> tuple[datetime, datetime, datetime]:
    """(speelmoment, opening, start) voor datum 'YYYY-MM-DD' en tijd 'HH:MM'."""
    speelmoment = datetime.strptime(f"{datum} {tijd}", "%Y-%m-%d %H:%M")
    opening = speelmoment - timedelta(days=CFG["dagen_vooruit"])
    start = opening - timedelta(seconds=CFG["start_seconden_vooraf"])
    return speelmoment, opening, start


def lees_clubboekingen(page: Page) -> list[dict]:
    """Leest 'Mijn boekingen' op het reserveringsoverzicht (pagina moet daar al staan)."""
    boekingen = []
    rijen = page.locator("table tr:has(input[name=ReservationId])")
    for i in range(rijen.count()):
        cellen = [c.strip() for c in rijen.nth(i).locator("td").all_text_contents()]
        rid = rijen.nth(i).locator("input[name=ReservationId]").first.get_attribute("value")
        try:
            datum = datetime.strptime(cellen[0], "%d-%m-%Y").strftime("%Y-%m-%d")
            tijd, eind = [t.strip() for t in cellen[1].split("-")]
        except (ValueError, IndexError):
            continue
        boekingen.append({"id": rid, "datum": datum, "tijd": tijd, "eind": eind,
                          "baan": cellen[2] if len(cellen) > 2 else ""})
    return sorted(boekingen, key=lambda b: (b["datum"], b["tijd"]))


def haal_clubboekingen() -> list[dict]:
    """Haalt je huidige boekingen van de clubsite op."""
    with browser_pagina() as page:
        ingelogd_op(page)
        page.goto(URL_OVERZICHT, wait_until="domcontentloaded")
        return lees_clubboekingen(page)


def annuleer_clubboeking(reservation_id: str) -> list[dict]:
    """Annuleert een echte boeking op de clubsite. Geeft de boekingen daarna terug."""
    with browser_pagina() as page:
        ingelogd_op(page)
        page.goto(URL_OVERZICHT, wait_until="domcontentloaded")
        formulier = page.locator(
            f'form[action$="RemoveReservation"]:has(input[name=ReservationId][value="{reservation_id}"])')
        if not formulier.count():
            raise RuntimeError("Deze boeking staat niet (meer) op de clubsite.")
        # Formulier direct versturen: dezelfde POST als de knop 'Annuleren', zonder pop-up
        with page.expect_navigation(wait_until="domcontentloaded"):
            formulier.first.evaluate("f => f.submit()")
        page.goto(URL_OVERZICHT, wait_until="domcontentloaded")
        over = lees_clubboekingen(page)
        if any(b["id"] == reservation_id for b in over):
            maak_screenshot(page, "annuleren_mislukt")
            raise RuntimeError("De clubsite heeft de boeking niet geannuleerd.")
        log(f"Clubboeking {reservation_id} geannuleerd.")
        return over


def test_inloggen() -> tuple[bool, str]:
    """Logt in (of gebruikt de opgeslagen sessie) en bewaart de sessie."""
    try:
        with browser_pagina(15000) as page:
            try:
                ingelogd_op(page)
                return True, "Inloggen gelukt."
            except Exception:
                maak_screenshot(page, "inloggen_mislukt")
                raise
    except Exception as e:
        return False, f"Inloggen mislukt: {e}"


def generale_repetitie(partner: str) -> tuple[bool, str]:
    """Controleert vooraf of inloggen lukt en de medespeler te vinden is. Wijzigt niets."""
    try:
        with browser_pagina(15000) as page:
            ingelogd_op(page)
            page.goto(URL_SPELERS, wait_until="domcontentloaded")
            weiger_cookies(page)
            veld = page.locator("#searchPlayerText")
            veld.fill("")
            veld.type(norm(partner), delay=20)
            resultaat = page.locator(".searchresults .addPlayer")
            try:
                resultaat.first.wait_for(state="visible", timeout=8000)
            except PWTimeout:
                pass
            namen = [norm(t) for t in resultaat.all_inner_texts()]
            if norm(partner) not in namen:
                maak_screenshot(page, "repetitie_mislukt")
                return False, f"Medespeler '{partner}' niet gevonden in de ledenlijst."
            return True, "Inloggen en medespeler OK."
    except Exception as e:
        return False, str(e)


def boek(datum: str, tijd: str, partner: str | None, test: bool = False,
         gestopt=lambda: False, voorkeursbaan: int | None = None) -> dict:
    """Voert één boeking uit. Wacht zelf tot de opening.
    Geeft {gelukt, tekst, screenshot, baan, partner, clubboekingen}."""
    speelmoment, opening, _ = momenten(datum, tijd)
    partners = [p for p in [partner or CFG["standaard_partner"]] if p]
    partners += [p for p in CFG["reserve_partners"] if p and p not in partners]
    uitkomst = {"gelukt": False, "tekst": "", "screenshot": None, "baan": None,
                "partner": None, "clubboekingen": None}
    if not partners:
        uitkomst["tekst"] = "Geen medespeler opgegeven."
        return uitkomst
    omschrijving = f"{DAGEN[speelmoment.weekday()]} {speelmoment:%d-%m-%Y} om {tijd}"
    log(f"Start: {omschrijving}. Baan gaat open {opening:%d-%m %H:%M}. "
        f"Medespelers: {', '.join(partners)}{' [TEST]' if test else ''}")
    try:
        with browser_pagina() as page:
            try:
                ingelogd_op(page)
                zet_medespeler(page, partners[0])
                wacht_tot(opening - timedelta(seconds=CFG["verversen_seconden_voor_opening"]),
                          "verversen", gestopt)
                deadline = max(opening, nu()) + timedelta(minutes=CFG["max_minuten_proberen"])
                baan, wie = probeer_te_boeken(page, speelmoment, partners, deadline, test,
                                              voorkeursbaan)
                if not test:
                    page.goto(URL_OVERZICHT, wait_until="domcontentloaded")
                    uitkomst["clubboekingen"] = lees_clubboekingen(page)
                uitkomst["screenshot"] = maak_screenshot(page, "geboekt")
                eind = speelmoment + timedelta(minutes=60)
                prefix = "[TEST - NIET bevestigd] " if test else ""
                uitkomst.update(gelukt=True, baan=baan, partner=wie,
                                tekst=f"{prefix}Baan {baan}, {omschrijving}-{eind:%H:%M}, met {wie}.")
                log(f"GELUKT: {uitkomst['tekst']}")
            except Exception as e:
                uitkomst["screenshot"] = maak_screenshot(page, "mislukt")
                raise e
    except Exception as e:
        reden = "geannuleerd" if str(e) == "GEANNULEERD" else str(e)
        uitkomst["tekst"] = f"Boeken voor {omschrijving} is niet gelukt. Reden: {reden}"
        log(f"MISLUKT: {uitkomst['tekst']}")
    return uitkomst
