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
- **Mijn banen**: je echte boekingen van de clubsite, met annuleerknop.
- **Meldingen met knoppen** (Companion-app): geplande boeking of geboekte baan annuleren.
- **Sensoren**: `sensor.tennis_volgende_baan` en `sensor.tennis_volgende_boekpoging`.
- **Agenda** (optioneel): geboekte banen in een HA-agenda.

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
| `agenda` | Bijv. `calendar.tennis`. Leeg = geen agenda |
| `voorkeursbaan` | Baan die eerst geprobeerd wordt (0 = geen voorkeur). Niet vrij? Dan elke andere vrije baan. Per boeking aan te passen in het dashboard |
| `aantal_banen` | Hoeveel banen je club heeft (voor de keuzelijst) |
| `dagen_vooruit` | Hoeveel dagen van tevoren banen opengaan (meestal 3) |
| `max_boekingen_per_dag` | Clubregel, meestal 2 |
| `max_minuten_proberen` | Na hoeveel minuten zonder vrije baan hij stopt |
