"""
server.py - het dashboard van de Tennis Boeker add-on (pagina 'Tennisbaan' in de HA-zijbalk).
"""
from __future__ import annotations

import html
import json
import os
import shutil
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import boeker
import planner
from boeker import CFG, DAGEN, LOGMAP, log, momenten, nu
from planner import dag_tekst

e = html.escape
VERSIE = os.getenv("ADDON_VERSION", "onbekend")


def ontbrekende_instellingen() -> list[str]:
    return [naam for naam in ("club_website", "gebruiker", "wachtwoord") if not CFG.get(naam)]


def neem_sessie_over() -> None:
    """Sessie van de laptop overnemen: zet sessie.json in de Samba-map share/tennis/."""
    bron = Path("/share/tennis/sessie.json")
    if bron.exists() and not boeker.SESSIE.exists():
        shutil.copy(bron, boeker.SESSIE)
        log("Inlogsessie overgenomen uit /share/tennis/sessie.json")


# --------------------------------------------------------------------------- opmaak
CSS = """
:root{--bg:#f4f5f7;--kaart:#fff;--tekst:#1c1f24;--zacht:#6b7280;--rand:#e3e6ea;--accent:#2f6f4e;
--accent-zacht:#e7f2ec;--ok:#1f7a45;--fout:#b42318;--fout-zacht:#fdecea;--bezig:#a15c00}
@media (prefers-color-scheme:dark){:root{--bg:#111315;--kaart:#1b1e21;--tekst:#e8eaed;--zacht:#9aa0a6;
--rand:#2c3035;--accent:#5fb38a;--accent-zacht:#1d2c24;--ok:#5fb38a;--fout:#f28b82;--fout-zacht:#2c1c1b;
--bezig:#f6bf5e}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tekst);
font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:900px;margin:0 auto;padding:20px 16px 40px}
header{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:14px}
h1{font-size:22px;margin:0}h2{font-size:16px;margin:0 0 12px;display:flex;justify-content:space-between;
align-items:baseline;gap:8px;flex-wrap:wrap}
.kaart{background:var(--kaart);border:1px solid var(--rand);border-radius:12px;padding:16px;margin-bottom:16px}
.tegels{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:16px}
.tegel{background:var(--kaart);border:1px solid var(--rand);border-radius:12px;padding:12px 14px}
.tegel b{display:block;font-size:18px;margin:2px 0}.tegel.hoofd{background:var(--accent-zacht);border-color:transparent}
.velden{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;align-items:end}
.opties{display:flex;flex-wrap:wrap;gap:10px 22px;align-items:center;margin:14px 0}
label{display:flex;flex-direction:column;gap:4px;font-size:13px;color:var(--zacht)}
.check{flex-direction:row;align-items:center;gap:8px;color:var(--tekst);font-size:14px;cursor:pointer}
.check input{width:18px;height:18px;min-height:0;margin:0}
input,select,button{font:inherit;padding:9px 10px;border-radius:8px;border:1px solid var(--rand);
background:var(--kaart);color:var(--tekst);min-height:42px}
button{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600;cursor:pointer}
button.groot{padding:10px 22px}
button.licht{background:none;color:var(--accent);min-height:36px;padding:6px 12px}
button.link{background:none;border:none;padding:0;min-height:0;font-weight:500;color:var(--fout);font-size:14px}
button.link.grijs{color:var(--zacht)}
.melding{padding:10px 12px;border-radius:8px;margin-bottom:16px;background:var(--accent-zacht)}
.melding.fout{background:var(--fout-zacht);color:var(--fout)}
.lijst{display:flex;flex-direction:column}
.item{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:10px 0;
border-bottom:1px solid var(--rand)}.item:last-child{border-bottom:none}
.item .sub{font-size:13px;color:var(--zacht)}.item.reserve{padding-left:18px}
.status{display:inline-block;padding:0 8px;border-radius:999px;font-size:12px;font-weight:600;
border:1px solid currentColor;margin-left:6px;white-space:nowrap}
.s-gepland{color:var(--accent)}.s-wacht{color:var(--zacht)}.s-bezig{color:var(--bezig)}
.s-geboekt{color:var(--ok)}.s-mislukt,.s-overgeslagen{color:var(--fout)}
.s-geannuleerd,.s-verlopen,.s-niet-nodig{color:var(--zacht)}
.klein{font-size:12px;color:var(--zacht)}a{color:var(--accent)}.leeg{color:var(--zacht);font-size:14px;margin:0}
pre{white-space:pre-wrap;font-size:12px;margin:0;max-height:300px;overflow:auto}
details>summary{cursor:pointer;font-weight:600}
.verborgen{display:none!important}
.item:has(+ details.wijzig){border-bottom:none;padding-bottom:4px}
details.wijzig{margin:0;padding:0 0 10px;border-bottom:1px solid var(--rand)}
details.wijzig>summary{font-weight:500;font-size:14px;color:var(--accent);display:inline-block}
details.wijzig[open]>summary{margin-bottom:10px}
details.wijzig form{background:var(--bg);border-radius:10px;padding:12px}.inline{display:inline;margin:0}
"""

JS = """
const kort=['zo','ma','di','wo','do','vr','za'],lang=['zondag','maandag','dinsdag','woensdag','donderdag','vrijdag','zaterdag'];
function bijwerken(f){
 const anders=f.querySelector('.anders'); if(anders) anders.classList.toggle('verborgen',f.partner.value!=='__anders__');
 const rv=f.querySelector('.reservevak');
 if(rv&&f.reserve){rv.classList.toggle('verborgen',!f.reserve.checked);
  if(f.reserve.checked&&f.reserve_tijd.value<=f.tijd.value){const u=Math.min(23,parseInt(f.tijd.value)+1);
  f.reserve_tijd.value=String(u).padStart(2,'0')+':00';}}
 const h=f.querySelector('.hint'),d=f.datum.value,t=f.tijd.value; if(!h||!d)return;
 const s=new Date(d+'T'+t),o=new Date(s.getTime()-DAGEN_VOORUIT*864e5);
 h.textContent=lang[s.getDay()]+' · baan gaat open '+kort[o.getDay()]+' '+
  o.toLocaleDateString('nl-NL',{day:'2-digit',month:'2-digit'})+' '+t+(f.herhaal&&f.herhaal.checked?' · daarna elke week':'');}
let bezig=false;
document.querySelectorAll('form.plan').forEach(f=>{
 f.addEventListener('change',()=>{bezig=true;bijwerken(f);}); f.addEventListener('input',()=>bezig=true); bijwerken(f);});
document.querySelectorAll('form[data-vraag]').forEach(x=>x.addEventListener('submit',ev=>{
 if(!confirm(x.dataset.vraag))ev.preventDefault();}));
setInterval(()=>{if(!bezig&&!document.querySelector('details[open]'))location.replace('./');},60000);
"""

STATUS = {"gepland": "Gepland", "wacht": "Reserve", "bezig": "Bezig…", "geboekt": "Geboekt",
          "mislukt": "Mislukt", "geannuleerd": "Geannuleerd", "verlopen": "Verlopen",
          "niet nodig": "Niet nodig", "overgeslagen": "Overgeslagen"}


def opties(waarden: list, gekozen, labels: dict | None = None) -> str:
    labels = labels or {}
    return "".join(f'<option value="{e(str(w))}"{" selected" if str(w) == str(gekozen) else ""}>'
                   f'{e(labels.get(w, str(w)))}</option>' for w in waarden)


def wijzig_formulier(p: dict, reserve: dict | None, namen: list[str], tijden: list[str]) -> str:
    """Inklapbaar formulier om een geplande boeking aan te passen."""
    partners = namen if p["partner"] in namen else [p["partner"]] + namen
    banen = list(range(0, CFG["aantal_banen"] + 1))
    heeft_reserve = bool(reserve and reserve["status"] in planner.ACTIEF)
    r_tijd = reserve["tijd"] if heeft_reserve else ""
    return f"""<details class="wijzig"><summary>Wijzigen</summary>
<form class="plan" method="post" action="wijzig"><input type="hidden" name="id" value="{e(p['id'])}">
<div class="velden">
<label>Speeldatum<input type="date" name="datum" value="{e(p['datum'])}" min="{nu():%Y-%m-%d}" required></label>
<label>Starttijd<select name="tijd">{opties(tijden, p['tijd'])}</select></label>
<label>Medespeler<select name="partner">{opties(partners + ['__anders__'], p['partner'], {'__anders__': 'Andere naam…'})}</select></label>
<label>Voorkeursbaan<select name="baan">{opties(banen, p.get('voorkeursbaan') or 0, {0: 'Geen voorkeur', **{n: f'Baan {n}' for n in banen if n}})}</select></label>
<label class="anders verborgen">Naam medespeler<input name="anders" placeholder="Voor- en achternaam"></label>
</div>
<div class="opties">
<label class="check"><input type="checkbox" name="reserve"{' checked' if heeft_reserve else ''}> Reservetijd als het niet lukt</label>
<label class="reservevak verborgen"><select name="reserve_tijd">{opties(tijden, r_tijd)}</select></label>
</div>
<div style="display:flex;gap:14px;align-items:center;flex-wrap:wrap">
<button>Wijziging opslaan</button><span class="hint klein"></span></div>
</form></details>"""


def knop(actie: str, label: str, waarde: str = "", klasse: str = "link", vraag: str = "") -> str:
    v = f' data-vraag="{e(vraag)}"' if vraag else ""
    return (f'<form method="post" action="{actie}" class="inline"{v}>'
            f'<input type="hidden" name="id" value="{e(waarde)}">'
            f'<button class="{klasse}">{label}</button></form>')


def status_label(status: str) -> str:
    return f'<span class="status s-{status.replace(" ", "-")}">{STATUS.get(status, status)}</span>'


# --------------------------------------------------------------------------- pagina
def pagina(bericht: str = "", fout: bool = False) -> str:
    alle = planner.plannen()
    clubdata = planner.club()
    st = planner.staat()

    # ---- tegels
    toekomst = [b for b in clubdata["boekingen"]
                if datetime.strptime(f"{b['datum']} {b['tijd']}", "%Y-%m-%d %H:%M") > nu()]
    if toekomst:
        b = toekomst[0]
        t1 = f"<b>{dag_tekst(b['datum'], b['tijd'])}</b><span class='klein'>{e(b['baan'])}</span>"
    else:
        t1 = "<b>—</b><span class='klein'>geen geboekte baan</span>"
    gepland = sorted([p for p in alle if p["status"] in ("gepland", "bezig") and not p.get("test")
                      and not p.get("reserve_van")], key=lambda p: (p["datum"], p["tijd"]))
    if gepland:
        p = gepland[0]
        _, opening, _ = momenten(p["datum"], p["tijd"])
        t2 = (f"<b>{dag_tekst(p['datum'], p['tijd'])}</b><span class='klein'>met {e(p['partner'])}"
              f" · opent {DAGEN[opening.weekday()][:2]} {opening:%d-%m %H:%M}</span>")
    else:
        t2 = "<b>—</b><span class='klein'>niets ingepland</span>"
    if st.get("dagcheck_tijd"):
        t3 = (f"<b>{'✓ Werkt' if st.get('dagcheck_ok') else '✗ Werkt niet'}</b>"
              f"<span class='klein'>gecontroleerd {e(st['dagcheck_tijd'])}</span>")
    else:
        t3 = f"<b>Nog niet gecontroleerd</b><span class='klein'>elke dag om {planner.DAGCHECK_UUR:02d}:00</span>"
    tegels = (f'<div class="tegels"><div class="tegel hoofd"><span class="klein">Volgende baan</span>{t1}</div>'
              f'<div class="tegel"><span class="klein">Volgende automatische boeking</span>{t2}</div>'
              f'<div class="tegel"><span class="klein">Inloggen bij de club</span>{t3}</div></div>')

    # ---- meldingen bovenaan
    boven = ""
    if (ontbreekt := ontbrekende_instellingen()):
        boven += (f'<div class="melding fout">Nog niet ingesteld: <b>{e(", ".join(ontbreekt))}</b>. '
                  f'Vul dit in bij Instellingen → Add-ons → Tennis Boeker → Configuratie.</div>')
    elif st.get("dagcheck_tijd") and not st.get("dagcheck_ok"):
        boven += (f'<div class="melding fout">Inloggen werkt niet: {e(st.get("dagcheck_tekst", ""))} '
                  f'Geplande boekingen gaan dan mis.</div>')
    if bericht:
        boven += f'<div class="melding{" fout" if fout else ""}">{e(bericht)}</div>'

    # ---- formulier
    namen = list(dict.fromkeys(n for n in [CFG["standaard_partner"]] + CFG["reserve_partners"]
                               + CFG["extra_partners"] if n))
    opties_p = "".join(f"<option>{e(n)}</option>" for n in namen) + \
        '<option value="__anders__">Andere naam…</option>'
    tijden = [f"{u:02d}:00" for u in range(7, 24)]
    laatste = next((p for p in sorted(alle, key=lambda p: p.get("aangemaakt", ""), reverse=True)
                    if not p.get("reserve_van")), None)
    standaard_tijd = laatste["tijd"] if laatste else "20:00"
    opties_t = "".join(f'<option{" selected" if t == standaard_tijd else ""}>{t}</option>' for t in tijden)
    opties_r = "".join(f"<option>{t}</option>" for t in tijden)
    vk = int(CFG.get("voorkeursbaan") or 0)
    opties_b = "".join(f'<option value="{n}"{" selected" if n == vk else ""}>'
                       f'{"Geen voorkeur" if n == 0 else f"Baan {n}"}</option>'
                       for n in range(0, CFG["aantal_banen"] + 1))
    standaard_datum = (nu() + timedelta(days=CFG["dagen_vooruit"])).strftime("%Y-%m-%d")
    formulier = f"""<div class="kaart"><h2>Nieuwe boeking</h2>
<form class="plan" method="post" action="plan">
<div class="velden">
<label>Speeldatum<input type="date" name="datum" value="{standaard_datum}" min="{nu():%Y-%m-%d}" required></label>
<label>Starttijd<select name="tijd">{opties_t}</select></label>
<label>Medespeler<select name="partner">{opties_p}</select></label>
<label>Voorkeursbaan<select name="baan">{opties_b}</select></label>
<label class="anders verborgen">Naam medespeler<input name="anders" placeholder="Voor- en achternaam"></label>
</div>
<div class="opties">
<label class="check"><input type="checkbox" name="herhaal"> Elke week herhalen</label>
<label class="check"><input type="checkbox" name="reserve"> Reservetijd als het niet lukt</label>
<label class="reservevak verborgen"><select name="reserve_tijd">{opties_r}</select></label>
<label class="check"><input type="checkbox" name="test"> Test (niet bevestigen)</label>
</div>
<div style="display:flex;gap:14px;align-items:center;flex-wrap:wrap">
<button class="groot">Plan boeking</button><span class="hint klein"></span></div>
</form></div>"""

    # ---- mijn banen (clubsite)
    if clubdata["boekingen"]:
        items = "".join(
            f'<div class="item"><div><b>{dag_tekst(b["datum"], b["tijd"])}–{e(b["eind"])}</b>'
            f'<div class="sub">{e(b["baan"])}</div></div>'
            + knop("clubannuleer", "Annuleren", b["id"],
                   vraag=f"Baan op {dag_tekst(b['datum'], b['tijd'])} echt annuleren op de clubsite?")
            + "</div>" for b in clubdata["boekingen"])
    else:
        items = '<p class="leeg">Geen boekingen gevonden op de clubsite.</p>'
    clubfout = (f'<p class="klein" style="color:var(--fout)">Ophalen mislukt: {e(clubdata["fout"])}</p>'
                if clubdata.get("fout") else "")
    mijn = (f'<div class="kaart"><h2>Mijn banen <span class="klein">bijgewerkt '
            f'{e(clubdata.get("bijgewerkt") or "nog niet")} · {knop("clubververs", "ververs", klasse="link grijs")}'
            f'</span></h2>{clubfout}<div class="lijst">{items}</div></div>')

    # ---- ingepland
    actief = sorted([p for p in alle if p["status"] in planner.ACTIEF and not p.get("reserve_van")],
                    key=lambda p: (p["datum"], p["tijd"]))
    per_id = {p["id"]: p for p in alle}
    regels = ""
    for p in actief:
        _, opening, _ = momenten(p["datum"], p["tijd"])
        extra = []
        if p.get("voorkeursbaan"):
            extra.append(f"voorkeur baan {p['voorkeursbaan']}")
        if p.get("reeks"):
            extra.append("vaste boeking")
        if p.get("test"):
            extra.append("test")
        if p.get("repetitie"):
            extra.append("controle " + ("OK" if p["repetitie"] == "OK" else "mislukt"))
        sub = (f"met {e(p['partner'])} · opent {DAGEN[opening.weekday()][:2]} {opening:%d-%m %H:%M}"
               + (f" · {', '.join(extra)}" if extra else ""))
        actie = knop("annuleer", "Annuleren", p["id"]) if p["status"] == "gepland" else ""
        r = per_id.get(p.get("reserve_id") or "")
        regels += (f'<div class="item"><div><b>{dag_tekst(p["datum"], p["tijd"])}</b>'
                   f'{status_label(p["status"])}<div class="sub">{sub}</div></div>{actie}</div>')
        if p["status"] == "gepland":
            regels += wijzig_formulier(p, r, namen, tijden)
        if r and r["status"] in planner.ACTIEF:
            regels += (f'<div class="item reserve"><div>↳ Reserve <b>{e(r["tijd"])}</b>'
                       f'{status_label(r["status"])}<div class="sub">alleen als {e(p["tijd"])} niet lukt</div>'
                       f'</div></div>')
    ingepland = (f'<div class="kaart"><h2>Ingepland</h2>'
                 f'<div class="lijst">{regels or "<p class=leeg>Niets ingepland.</p>"}</div></div>')

    # ---- vaste boekingen
    vast = [r for r in planner.reeksen() if r["actief"]]
    vaste = ""
    if vast:
        items = "".join(
            f'<div class="item"><div><b>Elke {DAGEN[r["weekdag"]]} {e(r["tijd"])}</b>'
            f'<div class="sub">met {e(r["partner"])}'
            f'{" · reserve " + e(r["reserve_tijd"]) if r.get("reserve_tijd") else ""}'
            f'{" · voorkeur baan " + str(r["voorkeursbaan"]) if r.get("voorkeursbaan") else ""}'
            f' · sinds {e(r["sinds"])}</div></div>'
            + knop("stopreeks", "Stoppen", r["id"],
                   vraag=f"Vaste boeking elke {DAGEN[r['weekdag']]} {r['tijd']} stoppen? "
                         f"Geplande boekingen hiervan worden ook geannuleerd.")
            + "</div>" for r in vast)
        vaste = f'<div class="kaart"><h2>Vaste boekingen</h2><div class="lijst">{items}</div></div>'

    # ---- afgerond
    klaar = sorted([p for p in alle if p["status"] not in planner.ACTIEF],
                   key=lambda p: (p["datum"], p["tijd"]), reverse=True)[:20]
    items = ""
    for p in klaar:
        info = e(p.get("resultaat", ""))
        if p.get("screenshot"):
            info += f' · <a href="screenshot/{e(p["screenshot"])}" target="_blank">screenshot</a>'
        items += (f'<div class="item"><div><b>{dag_tekst(p["datum"], p["tijd"])}</b>'
                  f'{" <span class=klein>(reserve)</span>" if p.get("reserve_van") else ""}'
                  f'{status_label(p["status"])}<div class="sub">{info}</div></div>'
                  f'{knop("verwijder", "Verwijderen", p["id"], "link grijs")}</div>')
    afgerond = ""
    if klaar:
        afgerond = (f'<div class="kaart"><details><summary>Afgerond ({len(klaar)})</summary>'
                    f'<div style="margin-top:10px">{knop("opruimen", "Alles opruimen", klasse="licht")}</div>'
                    f'<div class="lijst">{items}</div></details></div>')

    # ---- logboek
    try:
        logregels = (LOGMAP / "boeker.log").read_text(encoding="utf-8").splitlines()[-80:]
    except Exception:
        logregels = []
    logboek = (f'<div class="kaart"><details><summary>Logboek en test</summary>'
               f'<div style="margin:12px 0">{knop("testlogin", "Test inloggen", klasse="licht")}</div>'
               f'<pre>{e(chr(10).join(logregels)) or "Leeg."}</pre></details></div>')

    club_naam = boeker.BASIS.split("://")[-1] if boeker.BASIS else "geen club ingesteld"
    js = JS.replace("DAGEN_VOORUIT", str(CFG["dagen_vooruit"]))
    return f"""<!doctype html><html lang="nl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Tennisbaan</title>
<style>{CSS}</style></head><body><main>
<header><h1>🎾 Tennisbaan</h1><span class="klein">{e(club_naam)} · versie {e(VERSIE)} · <a href="./">ververs</a></span></header>
{boven}{tegels}{formulier}{mijn}{ingepland}{vaste}{afgerond}{logboek}
<p class="klein">Tijd nu: {nu():%d-%m-%Y %H:%M} · De add-on start {CFG['start_seconden_vooraf']} s voor
de opening, controleert {planner.REPETITIE_MINUTEN} min vooraf of alles klaarstaat en stopt na
{CFG['max_minuten_proberen']} min zonder vrije baan. Kan de medespeler niet, dan probeert hij:
{e(', '.join(CFG['reserve_partners']) or 'niemand')}.</p>
</main><script>{js}</script></body></html>"""


# --------------------------------------------------------------------------- acties
def voer_actie(actie: str, v: dict) -> str:
    if actie == "plan":
        if (ontbreekt := ontbrekende_instellingen()):
            raise ValueError("Vul eerst in bij de add-on-instellingen: " + ", ".join(ontbreekt))
        partner = v.get("anders", "").strip() if v.get("partner") == "__anders__" else v.get("partner", "")
        reserve = v.get("reserve_tijd") if "reserve" in v else None
        baan = int(v.get("baan") or 0)
        if "herhaal" in v:
            if "test" in v:
                raise ValueError("Een vaste boeking kan niet als test.")
            return planner.maak_reeks(v["datum"], v["tijd"], partner, reserve, baan)
        return planner.plan(v["datum"], v["tijd"], partner, test="test" in v, reserve_tijd=reserve,
                            voorkeursbaan=baan)
    if actie == "wijzig":
        partner = v.get("anders", "").strip() if v.get("partner") == "__anders__" else v.get("partner", "")
        reserve = v.get("reserve_tijd") if "reserve" in v else None
        return planner.wijzig(v["id"], v["datum"], v["tijd"], partner, int(v.get("baan") or 0), reserve)
    if actie == "annuleer":
        planner.annuleer(v["id"])
        return "Geplande boeking geannuleerd."
    if actie == "verwijder":
        planner.verwijder(v["id"])
        return ""
    if actie == "opruimen":
        for p in planner.plannen():
            if p["status"] not in planner.ACTIEF:
                planner.verwijder(p["id"])
        return "Afgeronde boekingen opgeruimd."
    if actie == "stopreeks":
        planner.stop_reeks(v["id"])
        return "Vaste boeking gestopt."
    if actie == "clubannuleer":
        return planner.annuleer_club(v["id"])
    if actie == "clubververs":
        planner.ververs_club()
        if (fout_tekst := planner.club().get("fout")):
            raise ValueError(f"Ophalen mislukt: {fout_tekst}")
        return "Boekingen van de clubsite opgehaald."
    if actie == "testlogin":
        ok, tekst = planner.inlog_check(melden=False)
        if not ok:
            raise ValueError(tekst)
        return tekst
    raise ValueError("Onbekende actie.")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def stuur(self, code: int, body: bytes, soort: str = "text/html; charset=utf-8") -> None:
        self.send_response(code)
        self.send_header("Content-Type", soort)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        pad = urlparse(self.path).path
        if "/screenshot/" in pad:
            bestand = LOGMAP / os.path.basename(pad)
            if bestand.exists() and bestand.suffix == ".png":
                return self.stuur(200, bestand.read_bytes(), "image/png")
            return self.stuur(404, b"niet gevonden", "text/plain")
        if pad.rstrip("/").endswith("/api"):
            data = {"plannen": planner.plannen(), "reeksen": planner.reeksen(), "club": planner.club()}
            return self.stuur(200, json.dumps(data, ensure_ascii=False).encode(), "application/json")
        q = parse_qs(urlparse(self.path).query)
        self.stuur(200, pagina(q.get("m", [""])[0], q.get("f", ["0"])[0] == "1").encode("utf-8"))

    def do_POST(self):
        lengte = int(self.headers.get("Content-Length", 0))
        velden = {k: v[0] for k, v in parse_qs(self.rfile.read(lengte).decode("utf-8")).items()}
        actie = urlparse(self.path).path.rstrip("/").split("/")[-1]
        try:
            bericht, fout = voer_actie(actie, velden), False
        except Exception as ex:
            bericht, fout = str(ex), True
        self.send_response(303)
        self.send_header("Location", f"./?m={quote(bericht)}&f={1 if fout else 0}" if bericht else "./")
        self.end_headers()


if __name__ == "__main__":
    log(f"Tennis Boeker {VERSIE} gestart. Tijd nu: {nu():%d-%m-%Y %H:%M:%S}")
    if ontbrekende_instellingen():
        log("LET OP: vul in bij de add-on-instellingen: " + ", ".join(ontbrekende_instellingen()))
    neem_sessie_over()
    planner.opstarten()
    ThreadingHTTPServer(("0.0.0.0", 8099), Handler).serve_forever()
