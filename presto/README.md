# Pimoroni Presto som FOH-betjening

Prestoen viser afviklingen og har store knapper til de vigtigste FOH-handlinger.

```
┌──────────────────────────────┐
│ FOH  8 tilbage  ANMODNING  ● │
│┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓│  NU: gul med rød kant, når noget afvikles
│┃ NU > AFVIKLES        3:32  ┃│  (nedtælling kun for video)
│┃ Aarets projekter - video   ┃│
│┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛│
│ NAESTE  ca. 20 min   ONSKET  │  Dirigentens valg (ellers næste i programmet)
│ Bestyrelsens beretning       │
│ [   KLAR    ] [   START   ]  │  ← næste punkt
│ [ ANNULLER  ] [  AFSLUT   ]  │  ← annullér næste / afslut det, der afvikles
└──────────────────────────────┘
```

- **KLAR:** kvitterer for dirigentens anmodning.
- **START:** starter næste punkt. Afvikles et andet punkt, skal der trykkes to gange.
- **AFSLUT:** afslutter det punkt, der afvikles.
- **ANNULLER:** tager næste punkt ud af programmet. Kræver altid to tryk, og knappen viser BEKRAEFT? imellem.
- **Lysdioderne:** lyser gult ved en ny anmodning fra scenen, rødt mens noget afvikles, og Prestoen bipper ved en ny anmodning.
- **Ingen forbindelse:** viser OFFLINE. En handling, der ikke når frem, giver en rød besked og bliver **ikke** udført.
- **Æ, ø og å:** skærmens skrift kan ikke vise dem, så de skrives som ae, oe og aa.

## Opsætning

1. **Serveren:** generér en nøgle og sæt den i `.env`. Genstart derefter serveren (`docker compose up -d`).
   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
   ```
   DEVICE_TOKEN=<nøglen>
   ```
2. **Prestoen:** installér Pimoronis Presto-firmware (MicroPython). Se Pimoronis vejledning til Presto.
3. Kopiér `config_example.py` til `config.py`, og ret WiFi, serverens IP-adresse og `DEVICE_TOKEN`.
4. Læg `main.py` og `config.py` i roden af Prestoen, f.eks. med [Thonny](https://thonny.org) eller `mpremote`:
   ```bash
   mpremote cp main.py config.py :
   ```
5. Genstart Prestoen. Den forbinder til WiFi og viser afviklingen.

## Fejlfinding

Når der står **INGEN FORBINDELSE**, viser Prestoen årsagen, serveradressen og sin egen IP-adresse.
Den samme besked skrives i Thonny-konsollen.

| Besked | Betyder | Løsning |
|---|---|---|
| Noegle afvist (401) | Prestoen når serveren, men nøglen passer ikke | Sæt samme `DEVICE_TOKEN` i `.env` og `config.py`, og genstart serveren |
| Afvist (111) | IP'en svarer, men intet program lytter på porten | Tjek porten i `SERVER`. Kører du uden Docker, så start med `--host 0.0.0.0` |
| Timeout (110/116) | Ingen svarer på adressen | Forkert IP, forskellige netværk, eller firewall på serveren |
| Ingen rute (113) | Prestoen og serveren er på hvert sit net | Kom på samme WiFi/netværk |
| Kan ikke slaa serveradressen op | Navnet i `SERVER` findes ikke | Brug serverens IP-adresse i stedet for et navn |
| WiFi er afbrudt | Prestoen har mistet WiFi | Den forbinder selv igen. Tjek `WIFI_SSID` og adgangskode |

- **OFFLINE:**
  - Kontrollér, at Prestoen er på samme netværk som serveren.
  - Kontrollér, at `SERVER` bruger serverens IP-adresse og port, f.eks. `http://192.168.1.10:8000`.
  - Kontrollér, at `http://<ip>:8000/api/health` svarer fra en anden enhed.
- **Fejl 401:** `DEVICE_TOKEN` på Prestoen og på serveren er ikke ens, eller serveren er ikke genstartet efter ændringen.
- **"Status er aendret":** nogen ændrede punktet samtidig, f.eks. FOH eller dirigenten. Handlingen er afvist, og visningen er opdateret. Tryk igen, hvis det stadig er det rigtige.
- **Knapperne reagerer forkert:** Pimoronis firmware-versioner kan variere. Tjek Thonny-konsollen for fejl.
- **Lysdioder og bip:** kan slås fra i `config.py` (`USE_LEDS = False`, `BUZZER_PIN = None`).

Handlinger fra Prestoen står i FOH-historikken som `device:presto`.

## Test uden hardware

Programmets logik testes automatisk mod serveren i `tests/test_presto_client.py`, men skærmtegning og touch
kræver en rigtig Presto.
