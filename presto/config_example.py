# Kopiér til config.py på Prestoen og ret værdierne.

# WiFi på det lokale netværk (samme net som serveren)
WIFI_SSID = "Mit-netvaerk"
WIFI_PASSWORD = "hemmelig"

# Serverens adresse – brug IP-adressen, ikke "localhost"
SERVER = "http://192.168.1.10:8000"

# Samme værdi som DEVICE_TOKEN i serverens .env
DEVICE_TOKEN = "indsaet-den-lange-noegle-her"

# Hvor ofte tilstanden hentes (millisekunder)
POLL_MS = 1000

# Lysdioder bag skærmen viser status (gul = anmodning fra scenen, rød = afvikles)
USE_LEDS = True

# Bip ved ny anmodning fra scenen. Pin til Prestoens piezo (None = slået fra)
BUZZER_PIN = 43
