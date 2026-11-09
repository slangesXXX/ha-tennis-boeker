# Tennis Boeker

Boekt automatisch een tennisbaan bij een vereniging met een KNLTB.Club-website
(herkenbaar aan "Powered by KNLTB.Club" onderaan en de knop "Reserveer je baan").
Draait volledig zelfstandig in Home Assistant.

## Wat hij doet
- Start 1 minuut voor de opening (speeltijd min `dagen_vooruit`) en boekt de eerste vrije baan.
- **Generale repetitie**: 15 minuten vooraf controleert hij of inloggen lukt en de medespeler te vinden is.
- **Dagelijkse inlogcheck** om 08:00; melding als het niet werkt.
- **Vaste boeking**: vink "Elke week herhalen" aan.
- **Reservetijd**: vink aan en kies een later uur; alleen gebruikt als de eerste tijd mislukt.
- **Clubregels**: waarschuwt bij meer dan `max_boekingen_per_dag` per dag of twee uur achter elkaar.
- **Wijzigen**: geplande boekingen aanpassen (datum, tijd, medespeler, baan, reservetijd), en vaste boekingen (dag, tijd, medespeler, baan, reservetijd) voor alle komende weken.
- **Mijn banen**: je echte boekingen van de clubsite, met annuleerknop.
- **Meldingen met knoppen** (Companion-app): geplande boeking of geboekte baan annuleren.
- **Sensoren**: `sensor.tennis_volgende_baan` en `sensor.tennis_volgende_boekpoging`.
- **Agenda + uitnodiging** (optioneel): bij het inplannen een afspraak in je HA-agenda en een
  uitnodiging per mail naar je medespeler. Per boeking uit te zetten met het vinkje *Agenda*.

## Instellingen (tabblad Configuratie)
| Instelling | Uitleg |
|---|---|
| `club_website` | Website van je club, bijv. `https://www.mijnclub.nl` |
| `gebruiker` / `wachtwoord` | Je bondsnummer (of clublidnummer) en wachtwoord van de clubsite |
| `login_met` | Bondsnummer of Clublidnummer |
| `standaard_partner` | Met wie je normaal speelt (zoals in de ledenlijst) |
| `reserve_partners` | Wie geprobeerd wordt als de site de medespeler weigert, op volgorde |
| `extra_partners` | Extra namen voor de keuzelijst |
| `notify_service` | Bijv. `mobile_app_iphone` (zonder `notify.`). Leeg = melding in Home Assistant |
| `agenda` | Bijv. `calendar.tennis`. De agenda moet in Home Assistant gekoppeld zijn (bijv. Google Agenda of Lokale agenda). Leeg = geen agenda-afspraken |
| `mijn_naam` / `mijn_email` | Jouw naam en e-mailadres: afzender van de uitnodiging aan je medespeler |
| `mail_service` | Een e-mail-notify-service van Home Assistant, bijv. `smtp` of `email` (zonder `notify.`). Leeg = geen uitnodigingen per mail |
| `partner_emails` | Lijst `Naam=e-mailadres`, bijv. `Bram Romer=bram@voorbeeld.nl`. Alleen medespelers met een adres krijgen een uitnodiging |
| `voorkeursbaan` | Baan die eerst geprobeerd wordt (0 = geen voorkeur). Niet vrij? Dan elke andere vrije baan. Per boeking aan te passen in het dashboard |
| `aantal_banen` | Hoeveel banen je club heeft (voor de keuzelijst) |
| `dagen_vooruit` | Hoeveel dagen van tevoren banen opengaan (meestal 3) |
| `max_boekingen_per_dag` | Clubregel, meestal 2 |
| `max_minuten_proberen` | Na hoeveel minuten zonder vrije baan hij stopt |


## Agenda-uitnodigingen instellen
1. **Jouw agenda**: koppel een agenda in Home Assistant (Instellingen → Apparaten & services → Integratie toevoegen, bijv. *Google Agenda* of *Lokale agenda*) en vul de naam in bij `agenda`, bijv. `calendar.tennis`.
2. **Uitnodiging voor je medespeler**: Home Assistant kan zelf geen gasten uitnodigen. Daarom verstuurt de add-on een mail met een agenda-bijlage (.ics) via een e-mailservice van Home Assistant (bijv. de *SMTP*-integratie). Vul `mail_service`, `mijn_email` en bij `partner_emails` het adres van je medespeler in.
3. De bijlage wordt tijdelijk in de map `/share/tennis_boeker` gezet. Voeg in je Home Assistant `configuration.yaml` toe en herstart:
   ```yaml
   homeassistant:
     allowlist_external_dirs:
       - /share
   ```
   Lukt de bijlage niet, dan gaat de mail zonder bijlage (met datum en tijd in de tekst).
- Automatisch verwijderen van een afspraak uit je agenda werkt alleen bij agenda's die dat ondersteunen; lukt het niet, dan krijg je een melding om hem zelf te verwijderen.
