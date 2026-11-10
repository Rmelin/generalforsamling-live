# Generalforsamling Live

Et enkelt, stabilt og webbaseret live-overblik over indslag under generalforsamlinger og konferencer.
Teknikere i FOH, dirigenter på scenen og teknikere rundt i salen ser **den samme tilstand i realtid**.

Systemet kører på et lokalt netværk **uden internet**. Én host-maskine i FOH kører server og database;
alle andre enheder bruger en almindelig browser.

| Skærm | URL | Adgang | Til |
|---|---|---|---|
| FOH | `/foh` | Brugernavn + adgangskode | Administration og afvikling (mus/tastatur) |
| Scene | `/stage` | Sceneadgangskode | Dirigenternes touchskærm (Raspberry Pi) |
| Monitor | `/monitor` | Intet login, kun visning | Teknikere i salen. Flere monitorer kan køre samtidig |
| Login | `/login` | – | Fanerne "FOH" og "Scene" |

Forsiden `/` linker til alle tre skærme.

---

## Hurtig start med Docker (anbefalet)

Kræver Docker og Docker Compose. Virker på x86-64, Linux og Raspberry Pi 5 (arm64).

```bash
cp .env.example .env        # ret adgangskoderne i .env
docker compose up -d --build
```

Åbn derefter `http://<host-ip>:8000` fra en hvilken som helst enhed på netværket.
Find host-maskinens IP med `hostname -I` (Linux) eller `ipconfig getifaddr en0` (macOS).

- Databasen ligger i Docker-volumenet `live-data` og overlever genstart og opdatering af containeren.
- Containeren starter automatisk igen efter strømsvigt (`restart: unless-stopped`).
- Status: `docker compose ps` (viser `healthy`) og logs: `docker compose logs -f`.

> **Byg imaget før arrangementet**, mens der er internet. Selve afviklingen kræver intet internet:
> Der bruges ingen CDN'er, eksterne fonte eller andre netværksressourcer.

## Start uden Docker (udvikling)

Kræver Python 3.12 eller nyere.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
set -a; . ./.env; set +a
.venv/bin/uvicorn --factory app.main:build --host 0.0.0.0 --port 8000
```

Eksempeldata indlæses automatisk med `SEED_DEMO_DATA=true`, eller manuelt:

```bash
.venv/bin/python -m app.seed           # kun hvis databasen er tom
.venv/bin/python -m app.seed --force   # tilføj eksempeldata alligevel
```

## Login

- **FOH:** `/login` → fanen *FOH* → `FOH_USERNAME` / `FOH_PASSWORD` fra `.env`.
- **Scene:** `/login` → fanen *Scene* → `STAGE_PASSWORD` fra `.env` (kun adgangskode).
- **Monitor:** åbn `/monitor` direkte. Kræver intet login og kan ikke ændre noget.

Adgangskoderne gemmes som PBKDF2-hashes i databasen. Værdierne i `.env` er autoritative: ændrer du en
adgangskode og genstarter, opdateres hashen. Login varer 7 dage som standard (`SESSION_MAX_AGE`),
så en scene-Pi ikke logges ud midt i et arrangement.

Kører du uden `FOH_PASSWORD`/`STAGE_PASSWORD`, bruges `admin` og `scene`, og serveren skriver en advarsel i loggen.
**Sæt altid egne adgangskoder.**

## Sådan bruges systemet

### Statusmodel

| Status | Ikon | Hvem sætter den |
|---|---|---|
| Afventer | ○ | Ny punkt / FOH nulstiller / dirigent fortryder |
| Ønskes klargjort | ⚑ | Dirigenten vælger punktet |
| Klar | ✓ | FOH kvitterer |
| Afvikles | ▶ | FOH starter |
| Afsluttet | ■ | FOH afslutter |
| Annulleret | ✕ | FOH tager punktet ud af programmet |

Status vises altid med **ikon og tekst**, ikke kun farve.

### Tid: Video tæller ned, Tale og Andet er ca.-tider

- **Video** har en fast længde. Når FOH trykker *Start*, tæller alle skærme ned (`1:32` tilbage).
  Kører videoen over tid, vises `+0:05` i rødt.
- **Tale** og **Andet** har kun en anslået tid og vises som `ca. 5 min`. Når de startes, står der kun
  **Afvikles**, uden et ur, der kører.

### Skal afvikles eller Mulighed

Hvert punkt er enten **Skal** afvikles (standard) eller en **Mulighed**, der kan springes over, f.eks. hvis
tiden tillader det. FOH vælger det ved oprettelse (fluebenet *Mulighed*) og i redigeringen.

- På **scenen** har hvert punkt et mærke: **SKAL** (fuld kant) eller **MULIGHED** (stiplet kant og kursiv titel).
  Øverst står, hvor mange af hver slags der er tilbage.
- **FOH** og **monitoren** viser mærket *Mulighed* og en stiplet kant på valgfrie punkter.

- FOH kan springe trin over, f.eks. starte et punkt direkte fra *Afventer*.
- Kun ét punkt kan afvikles ad gangen. Starter FOH et nyt punkt, afsluttes det igangværende automatisk.
  FOH får en bekræftelsesdialog først.
- Dirigenten kan trække en anmodning tilbage, så længe punktet ikke afvikles.
- Afsluttede og annullerede punkter forsvinder fra scenelisten, men kan ses i FOH under *Vis afsluttede*
  og genåbnes derfra.
- *Slet* skjuler et punkt fra alle lister. Det bliver i databasen og i historikken og slettes aldrig permanent.

### FOH (`/foh`)

- **Venstre side:** hurtig oprettelse (titel, type, varighed som `mm:ss` eller minutter), programlisten med
  statusfarver og ▲/▼ til at ændre rækkefølgen. Nye anmodninger fra scenen blinker og vises øverst
  med en *Markér klar*-knap.
- **Højre side:** *Afvikles nu* (med forløbet tid i forhold til forventet tid og *Afslut*), *Næste (ønsket af
  scenen)* (*Klar* / *Start*) og redigering af det valgte punkt, inkl. **tekniske noter** til teknikerne.
- **Historik** (kryds af øverst) viser hændelsesloggen: tid, punkt, handling, status før og efter, og hvem.

### Scene (`/stage`)

Tryk på et punkt for at vælge det, og tryk derefter **Anmod om klargøring**. Når FOH har kvitteret, vises
**FOH: KLAR**. **Fortryd** trækker anmodningen tilbage. Scenen har ingen knapper til at starte eller
afslutte afvikling, og serveren afviser den slags kald fra scene-rollen.

### Monitor (`/monitor`)

Read-only teknikeroverblik, beregnet til at blive læst på afstand:

- **Nu:** titel, type, status, starttidspunkt, forløbet tid og forventet varighed.
- **Næste:** dirigentens valgte punkt med klargøringsstatus og tekniske noter. Er intet valgt, vises
  næste punkt i programmet med en markering af, at det ikke er valgt endnu.
- **Kommende:** resterende punkter. Ønskede eller klare punkter fremhæves, og nye punkter dukker op automatisk.

Tryk på **Fuldskærm** eller tasten `F`. Markøren og knapperne skjules efter få sekunders inaktivitet.

### Tema

Alle skærme har en **Tema**-knap, der skifter mellem *Mørk* (standard), *Lys* og *Auto* (følger enhedens
systemindstilling). Valget gemmes i browseren på den enkelte enhed og bevares efter genstart.

## Stabilitet

- **Serveren er autoritativ.** Klienter viser først en ændring, når serveren har accepteret den. Fejl vises
  tydeligt som en rød besked.
- **Realtid via WebSocket (`/ws`).** Ved hver ændring sender serveren et komplet snapshot med et
  revisionsnummer. Klienter afviser snapshots, der er ældre end det, de allerede har.
- **Genforbindelse:** Mister en klient forbindelsen, vises en rød advarsel øverst, og handlingsknapper
  låses. Klienten genforbinder automatisk og får den aktuelle tilstand med det samme. Serveren sender
  ping hvert 10. sekund, så en "død" forbindelse opdages inden for ca. 25 sekunder.
- **Samtidighed:** Alle skrivninger sker i én transaktion under en skrivelås. Statushandlinger sender den
  status, brugeren så (`expected_status`). Har en anden ændret punktet i mellemtiden, afvises handlingen
  med en forklaring. Redigering bruger et versionsnummer (`expected_version`) på samme måde.
- **Idempotens:** Gentages en handling, f.eks. ved et dobbeltklik på *Start*, sker der intet nyt.
- **SQLite i WAL-mode** med `synchronous=FULL`. Genstart af serveren mister hverken punkter, status
  eller historik.

## API

Skrivekald kræver login og headeren `X-Live-Client: 1` (simpel CSRF-beskyttelse). Interaktiv dokumentation findes på `/api/docs`.

| Metode | Sti | Rolle |
|---|---|---|
| GET | `/api/state` | alle (snapshot) |
| GET | `/api/health` | alle |
| GET | `/api/me` | alle |
| GET | `/api/events` | FOH |
| POST | `/api/items` | FOH |
| PATCH | `/api/items/{id}` | FOH (kræver `expected_version`) |
| DELETE | `/api/items/{id}` | FOH (blød sletning) |
| POST | `/api/items/{id}/move` | FOH (`{"direction": "up"|"down"}`) |
| POST | `/api/items/{id}/actions/{action}` | FOH / Scene (`request`, `withdraw`, `ready`, `start`, `finish`, `cancel`, `reopen`) |
| WS | `/ws` | alle (kun læsning) |

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

Testene dækker statusovergange, rettigheder pr. rolle (monitoren kan intet ændre), WebSocket-udsendelse til
flere klienter, ny klient og genforbindelse midt i afviklingen, samtidige og forældede ændringer,
idempotens, hashede adgangskoder samt genstart uden datatab.

## Raspberry Pi

Se [docs/raspberry-pi-kiosk.md](docs/raspberry-pi-kiosk.md) for opsætning af scene-touchskærm og monitorer i
Chromium kiosk-mode og for at køre selve serveren på en Pi 5.

## Projektstruktur

```
app/
  main.py        FastAPI-app, sider, API og WebSocket
  services.py    forretningslogik, transaktioner, revision, hændelseslog
  state.py       statusmodel og tilladte overgange
  models.py      SQLAlchemy-modeller (items, events, users, meta)
  auth.py        login, roller og password-hashing
  realtime.py    WebSocket-forbindelser og udsendelse
  seed.py        eksempeldata
  templates/     Jinja2 (foh, stage, monitor, login)
  static/        CSS (temaer via CSS-variabler) og vanilla JS
tests/           pytest
```

### Fremtidige udvidelser

Monitoren får hele snapshottet og renderer selv. Nye layouts eller profiler, f.eks. `/monitor?profile=mic`,
ur, nedtælling og beskeder fra FOH, kan derfor tilføjes som ren frontend eller som nye felter i
snapshottet uden at ændre synkroniseringen.
