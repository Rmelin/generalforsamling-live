# Raspberry Pi – kiosk-opsætning

Gælder Raspberry Pi OS (Bookworm eller nyere, 64-bit, med desktop) på Raspberry Pi 4/5.

Der er to typer Pi'er:

1. **Scene-Pi** med touchskærm: viser `/stage`.
2. **Monitor-Pi** med almindelig skærm: viser `/monitor`.

Serveren kan også køre på en Pi 5. Se sidst i dokumentet.

## 1. Netværk

- Brug helst **kabelforbundet netværk** til alle enheder.
- Giv host-maskinen en **fast IP-adresse**, f.eks. via DHCP-reservation i routeren, så kiosk-URL'en ikke ændrer sig.
  I eksemplerne nedenfor er det `192.168.1.10`.

## 2. Forbered Pi'en

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y chromium-browser unclutter   # på nyere udgaver hedder pakken "chromium"
```

Slå skærmslukning fra: `sudo raspi-config` → *Display Options* → *Screen Blanking* → **No**.

Slå autologin til desktop til: `sudo raspi-config` → *System Options* → *Boot / Auto Login* → **Desktop Autologin**.

## 3. Kiosk-script

Opret `/home/pi/kiosk.sh`. Udskift URL'en med `/stage` eller `/monitor`:

```bash
#!/bin/bash
URL="http://192.168.1.10:8000/stage"

# Vent på at serveren svarer (op til ca. 2 minutter)
for i in $(seq 1 60); do
  curl -sf "http://192.168.1.10:8000/api/health" >/dev/null && break
  sleep 2
done

# Ryd evt. "Chromium blev ikke lukket korrekt"-advarsel
PREFS="$HOME/.config/chromium/Default/Preferences"
[ -f "$PREFS" ] && sed -i 's/"exited_cleanly":false/"exited_cleanly":true/; s/"exit_type":"[^"]*"/"exit_type":"Normal"/' "$PREFS"

unclutter -idle 3 &   # skjul musemarkør (ikke nødvendigt på ren touch)

exec chromium-browser \
  --kiosk "$URL" \
  --noerrdialogs --disable-infobars --no-first-run \
  --disable-translate --disable-features=Translate \
  --disable-pinch --overscroll-history-navigation=0 \
  --check-for-update-interval=31536000 \
  --password-store=basic
```

```bash
chmod +x /home/pi/kiosk.sh
```

(Heder browseren `chromium` på din udgave, så ret sidste linje.)

## 4. Autostart

**Bookworm med Wayland (labwc, standard på Pi 5):**

```bash
mkdir -p ~/.config/labwc
echo "/home/pi/kiosk.sh &" >> ~/.config/labwc/autostart
```

**Ældre udgaver / X11 (LXDE):**

```bash
mkdir -p ~/.config/lxsession/LXDE-pi
cp /etc/xdg/lxsession/LXDE-pi/autostart ~/.config/lxsession/LXDE-pi/
echo "@/home/pi/kiosk.sh" >> ~/.config/lxsession/LXDE-pi/autostart
```

Genstart: `sudo reboot`.

## 5. Første login på scene-Pi'en

Første gang viser scene-Pi'en login-siden. Tilslut et tastatur, eller brug skærmtastaturet (`sudo apt install squeekboard`),
og indtast **sceneadgangskoden**. Login-cookien gemmes i Chromium-profilen og gælder i
`SESSION_MAX_AGE` (standard 7 dage). Efter genstart er Pi'en derfor stadig logget ind.

Monitor-Pi'er kræver intet login.

## 6. Tips

- **Tema:** Tryk på *Tema* på den enkelte skærm. Valget gemmes lokalt i browseren på den pågældende enhed.
- **Forbindelsestab:** Skærmen viser en rød advarsel og genforbinder automatisk. Du skal ikke genindlæse siden.
- **Officiel 7"-touchskærm (800×480):** Scenevisningen er designet til at fungere ned til denne opløsning.
- **Skærmrotation:** Brug *Screen Configuration* i desktoppen eller `wlr-randr`.
- Afslut kiosk-mode med `Alt+F4` eller ved at logge ind via SSH og køre `pkill chromium`.

## 7. Serveren på en Raspberry Pi 5

Imaget bygges direkte til arm64:

```bash
curl -fsSL https://get.docker.com | sh       # én gang, kræver internet
sudo usermod -aG docker $USER && newgrp docker
git clone <repo> generalforsamling-live && cd generalforsamling-live
cp .env.example .env && nano .env
docker compose up -d --build
```

Brug gerne en **SSD (USB 3)** frem for SD-kort til databasen for bedre holdbarhed, og en
officiel strømforsyning. Byg imaget, **mens der er internet**. Derefter kører alt offline.
