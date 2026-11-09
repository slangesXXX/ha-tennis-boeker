# Wijzigingen

## 1.6.0
- **Agenda-afspraak + uitnodiging**: bij elke boeking staat een vinkje *Agenda* (standaard aan).
  Zodra je een boeking inplant komt er een afspraak in je Home Assistant-agenda, en de medespeler
  krijgt een mail met uitnodiging (.ics) als zijn/haar adres bekend is.
- De afspraak blijft kloppen: wijzig je tijd of medespeler, dan wordt hij bijgewerkt (nieuwe mail,
  eventueel annulering aan de vorige medespeler). Wordt de reservetijd gebruikt, dan verhuist hij mee.
  Zodra de baan bekend is komt het banennummer erbij. Mislukt de boeking, of annuleer je, dan
  verdwijnt de afspraak en krijgt de medespeler een annulering.
- Nieuwe instellingen: `mijn_naam`, `mijn_email`, `mail_service` en `partner_emails`
  (lijst `Naam=adres`). Het vinkje is alleen zichtbaar als `agenda` en/of `mail_service` is ingesteld.
- Ook voor vaste boekingen (vinkje bij aanmaken en wijzigen).
- De add-on mag nu in `/share` schrijven (tijdelijk bestand voor de mailbijlage).

## 1.5.0
- Vaste boekingen wijzigen: klik **Wijzigen** onder een vaste boeking en pas dag, tijd,
  medespeler, voorkeursbaan of reservetijd aan. Geldt voor alle komende weken.
- Al ingeplande weken van die vaste boeking worden direct opnieuw ingepland met de nieuwe
  instellingen; weken die je los hebt gewijzigd blijven zoals ze zijn.

## 1.4.1
- Boeken op dagen 1 t/m 9 van de maand mislukte: de clubsite schrijft '3-11-2026', de add-on
  zocht naar '03-11-2026' en stopte voor de zekerheid. Beide schrijfwijzen worden nu herkend.

## 1.4.0
- Geplande boekingen wijzigen: klik **Wijzigen** onder een boeking bij *Ingepland* en pas
  datum, tijd, medespeler, voorkeursbaan of reservetijd aan.
- Ook bij wijzigen worden de clubregels gecontroleerd (max. per dag, niet twee uur achter elkaar).
- Bij een vaste boeking geldt de wijziging alleen voor die ene week.

## 1.3.1
- Geslaagde boeking werd soms als "mislukt" gemeld (antwoord van de clubsite was al weg door
  de doorverwijzing). Nu controleert de add-on in dat geval je overzicht op de clubsite.

## 1.3.0
- Verhuisd naar GitHub: updates verschijnen nu als **Bijwerken** in Home Assistant.
- Versienummer zichtbaar bovenaan het dashboard en in het logboek.

## 1.2.4
- Slot kiezen werkt niet meer via de scripts van de clubsite, maar vult het formulier direct in.
- Geen zwarte lijst meer voor banen als de site de keuze niet accepteert; foutmelding van de site komt in het logboek.
- Apparaatnaam bij `notify_service` (bijv. `iPhone (2)`) wordt automatisch omgezet.

## 1.2.3
- "Test inloggen" werkt de inlogstatus in het dashboard bij.

## 1.2.2
- Voorkeursbaan instelbaar, ook per boeking in het dashboard.

## 1.2.0
- Generale repetitie, dagelijkse inlogcheck, vaste boekingen, reservetijd, clubregels,
  echte boekingen + annuleren, knoppen in meldingen, sensoren en agenda.
