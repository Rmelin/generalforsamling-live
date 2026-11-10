# Generalforsamling Live – FOH-betjening på Pimoroni Presto (MicroPython)
#
# Viser det punkt, der afvikles, og det næste punkt, og giver store knapper til
# KLAR, START, AFSLUT og ANNULLER. Taler med serveren via /api/device/state og
# /api/items/<id>/actions/<handling> med en enhedsnøgle (DEVICE_TOKEN).
#
# Læg main.py og config.py på Prestoen (f.eks. med Thonny).

import time

try:
    import ujson as json
except ImportError:
    import json

try:
    import urequests as requests
except ImportError:
    import requests

import config

try:
    ticks_ms = time.ticks_ms
    ticks_diff = time.ticks_diff
except AttributeError:  # kørsel på en almindelig computer (test)
    def ticks_ms():
        return int(time.monotonic() * 1000)

    def ticks_diff(a, b):
        return a - b


# ---------------------------------------------------------------- tekst

# Skærmens indbyggede skrift kan kun ASCII.
_TR = {
    "æ": "ae", "ø": "oe", "å": "aa", "Æ": "Ae", "Ø": "Oe", "Å": "Aa",
    "é": "e", "è": "e", "ü": "u", "ö": "o", "ä": "a", "Ü": "U", "Ö": "O", "Ä": "A",
    "–": "-", "—": "-", "’": "'", "‘": "'", "“": '"', "”": '"', "…": "...",
}


def ascii_text(s):
    out = []
    for c in s or "":
        if ord(c) < 128:
            out.append(c)
        else:
            out.append(_TR.get(c, "?"))
    return "".join(out)


def shorten(s, n):
    return s if len(s) <= n else s[: n - 2] + ".."


def fmt_dur(sec):
    sec = int(sec)
    neg = sec < 0
    sec = abs(sec)
    m, s = sec // 60, sec % 60
    h, m = m // 60, m % 60
    txt = "%d:%02d:%02d" % (h, m, s) if h else "%d:%02d" % (m, s)
    return ("+" if neg else "") + txt


def fmt_approx(sec):
    if not sec:
        return "-"
    if sec < 60:
        return "ca. %ds" % sec
    return "ca. %d min" % ((sec + 30) // 60)


STATUS_TAG = {
    "pending": ("I PROGRAM", "grey"),
    "requested": ("ONSKET", "amber"),
    "ready": ("KLAR", "green"),
    "live": ("AFVIKLES", "red"),
}


# ---------------------------------------------------------------- server


class Server:
    def __init__(self, base, token):
        self.base = base.rstrip("/")
        self.headers = {
            "Authorization": "Bearer " + token,
            "X-Live-Client": "1",
            "Content-Type": "application/json",
        }

    def _req(self, method, path, body=None):
        url = self.base + path
        data = json.dumps(body) if body is not None else None
        try:
            r = requests.request(method, url, data=data, headers=self.headers, timeout=4)
        except TypeError:  # ældre urequests uden timeout
            r = requests.request(method, url, data=data, headers=self.headers)
        try:
            status = r.status_code
            try:
                payload = r.json()
            except Exception:
                payload = None
        finally:
            r.close()
        return status, payload

    def state(self):
        status, payload = self._req("GET", "/api/device/state")
        if status != 200:
            raise RuntimeError("HTTP %d" % status)
        return payload

    def action(self, item, action):
        path = "/api/items/%d/actions/%s" % (item["id"], action)
        return self._req("POST", path, {"expected_status": item["status"]})


# ---------------------------------------------------------------- app


class App:
    W = 240
    H = 240
    CONFIRM_MS = 3000

    def __init__(self, display=None, presto=None, server=None):
        self.presto = presto
        self.display = display
        self.server = server or Server(config.SERVER, config.DEVICE_TOKEN)
        self.state = None
        self.fetched_at = 0
        self.online = False
        self.last_poll = -100000
        self.message = None  # (tekst, farve, udløber)
        self.confirm = None  # (nøgle, udløber)
        self.buttons = []  # (x, y, w, h, nøgle, handling, punkt)
        self.pressed = None
        self.press_xy = (0, 0)
        self.last_requests = 0
        self.dirty = True
        self.pens = {}
        if display is not None:
            self.W, self.H = display.get_bounds()
            self._make_pens()
        self.buzzer = None
        pin = getattr(config, "BUZZER_PIN", None)
        if pin is not None:
            try:
                from machine import PWM, Pin
                self.buzzer = PWM(Pin(pin))
                self.buzzer.duty_u16(0)
            except Exception:
                self.buzzer = None

    # ------------------------------------------------ tilstand

    def poll(self):
        self.last_poll = ticks_ms()
        try:
            st = self.server.state()
        except Exception as exc:  # netværksfejl
            if self.online:
                self.dirty = True
            self.online = False
            self.error = str(exc)
            return False
        if not self.online or st != self.state:
            self.dirty = True
        self.online = True
        self.state = st
        self.fetched_at = ticks_ms()
        req = st.get("requests", 0)
        if req > self.last_requests:
            self.beep()
        self.last_requests = req
        self.update_leds()
        return True

    def remaining_now(self, cur):
        """Resterende sekunder for video, talt ned lokalt siden sidste hentning."""
        if not cur or not cur.get("timed") or cur.get("remaining_seconds") is None:
            return None
        gone = ticks_diff(ticks_ms(), self.fetched_at) // 1000
        return cur["remaining_seconds"] - gone

    # ------------------------------------------------ handlinger

    def handle_tap(self, x, y):
        for (bx, by, bw, bh, key, action, item) in self.buttons:
            if bx <= x < bx + bw and by <= y < by + bh:
                self.press(key, action, item)
                return True
        return False

    def needs_confirm(self, action):
        if action == "cancel":
            return True
        if action == "start" and self.state and self.state.get("current"):
            return True  # et andet punkt afvikles stadig
        return False

    def press(self, key, action, item):
        now = ticks_ms()
        if self.needs_confirm(action):
            if not (self.confirm and self.confirm[0] == key and ticks_diff(self.confirm[1], now) > 0):
                self.confirm = (key, now + self.CONFIRM_MS)
                self.dirty = True
                return "confirm"
        self.confirm = None
        self.show("Sender ...", "white", 2000)
        self.draw()
        try:
            status, payload = self.server.action(item, action)
        except Exception:
            self.show("Ingen forbindelse - IKKE udfoert", "red", 4000)
            self.online = False
            return "error"
        if status == 200:
            self.show("OK", "green", 1200)
            result = "ok"
        elif status == 409:
            self.show("Status er aendret - opdateret", "amber", 3500)
            result = "conflict"
        else:
            detail = payload.get("detail") if isinstance(payload, dict) else None
            self.show(ascii_text(detail if isinstance(detail, str) else "Fejl %d" % status), "red", 4000)
            result = "error"
        self.poll()
        self.dirty = True
        return result

    def show(self, text, color, ms):
        self.message = (text, color, ticks_ms() + ms)
        self.dirty = True

    # ------------------------------------------------ lys og lyd

    def update_leds(self):
        if not getattr(config, "USE_LEDS", True) or self.presto is None:
            return
        st = self.state or {}
        if st.get("requests"):
            rgb = (255, 150, 0)
        elif st.get("current"):
            rgb = (200, 0, 0)
        else:
            rgb = (0, 0, 0)
        try:
            for i in range(7):
                self.presto.set_led_rgb(i, *rgb)
        except Exception:
            pass

    def beep(self):
        if not self.buzzer:
            return
        try:
            for f in (1200, 1600):
                self.buzzer.freq(f)
                self.buzzer.duty_u16(20000)
                time.sleep_ms(90)
            self.buzzer.duty_u16(0)
        except Exception:
            pass

    # ------------------------------------------------ tegning

    def _make_pens(self):
        d = self.display
        p = self.pens
        p["bg"] = d.create_pen(14, 17, 22)
        p["panel"] = d.create_pen(30, 37, 46)
        p["white"] = d.create_pen(238, 242, 246)
        p["muted"] = d.create_pen(150, 160, 170)
        p["ink"] = d.create_pen(20, 20, 20)
        p["yellow"] = d.create_pen(255, 210, 63)
        p["red"] = d.create_pen(230, 40, 40)
        p["green"] = d.create_pen(40, 200, 110)
        p["amber"] = d.create_pen(255, 170, 30)
        p["grey"] = d.create_pen(120, 130, 140)
        p["blue"] = d.create_pen(60, 140, 255)
        p["dark"] = d.create_pen(55, 62, 72)

    def _text(self, txt, x, y, pen, scale=2, wrap=None):
        d = self.display
        d.set_pen(self.pens[pen])
        d.text(txt, x, y, wrap or (self.W - x - 4), scale)

    def _rect(self, x, y, w, h, pen):
        self.display.set_pen(self.pens[pen])
        self.display.rectangle(x, y, w, h)

    def _button(self, x, y, w, h, label, pen, key, action, item, ink="white"):
        if action is None:  # deaktiveret plads (holder knapperne på faste pladser)
            self._rect(x, y, w, h, "panel")
            tw = self.display.measure_text(label, 2)
            self._text(label, x + max(2, (w - tw) // 2), y + (h - 14) // 2, "dark", 2, w)
            return
        confirming = self.confirm and self.confirm[0] == key and ticks_diff(self.confirm[1], ticks_ms()) > 0
        if confirming:
            pen, ink, label = "amber", "ink", "BEKRAEFT?"
        if self.pressed == key:
            pen = "white"
            ink = "ink"
        self._rect(x, y, w, h, pen)
        scale = 2 if self.display.measure_text(label, 2) <= w - 6 else 1
        tw = self.display.measure_text(label, scale)
        self._text(label, x + max(2, (w - tw) // 2), y + (h - 7 * scale) // 2, ink, scale, w)
        self.buttons.append((x, y, w, h, key, action, item))

    def draw(self):
        if self.display is None:
            self.buttons = []
            self._layout_buttons_only()
            return
        W = self.W
        d = self.display
        self.buttons = []
        self._rect(0, 0, W, self.H, "bg")
        st = self.state or {}
        cur = st.get("current")
        nxt = st.get("next")

        # Topbjælke
        self._rect(0, 0, W, 18, "panel")
        self._text("FOH", 4, 3, "white", 1)
        if st:
            self._text("%d tilbage" % st.get("remaining", 0), 40, 3, "muted", 1)
        if st.get("requests"):
            tw = d.measure_text("ANMODNING", 1)
            self._rect(W - 54 - tw - 8, 1, tw + 8, 16, "amber")
            self._text("ANMODNING", W - 54 - tw - 4, 5, "ink", 1)
        self._rect(W - 46, 1, 44, 16, "green" if self.online else "red")
        self._text("ONLINE" if self.online else "OFFLINE", W - 43, 5, "ink" if self.online else "white", 1)

        # NU
        y = 21
        if cur:
            self._rect(2, y, W - 4, 72, "red")
            self._rect(5, y + 3, W - 10, 66, "yellow")
            self._text("NU  > AFVIKLES", 9, y + 6, "ink", 1)
            rem = self.remaining_now(cur)
            if rem is not None:
                t = fmt_dur(rem)
                tw = d.measure_text(t, 3)
                self._text(t, W - 10 - tw, y + 5, "red" if rem < 0 else "ink", 3)
            else:
                t = fmt_approx(cur.get("duration_seconds"))
                tw = d.measure_text(t, 1)
                self._text(t, W - 10 - tw, y + 6, "ink", 1)
            ty = y + 31 if rem is not None else y + 22
            self._text(shorten(ascii_text(cur["title"]), 36), 9, ty, "ink", 2, W - 18)
        else:
            self._rect(2, y, W - 4, 72, "panel")
            self._text("NU", 9, y + 6, "muted", 1)
            self._text("Intet i gang", 9, y + 30, "muted", 2)

        # NÆSTE
        y = 97
        self._rect(2, y, W - 4, 64, "panel")
        if nxt:
            label, pen = STATUS_TAG.get(nxt["status"], (nxt["status"].upper(), "grey"))
            if not st.get("next_chosen"):
                label = "I PROGRAM"
            self._text("NAESTE", 9, y + 5, "muted", 1)
            tw = d.measure_text(label, 1)
            self._rect(W - 14 - tw, y + 2, tw + 8, 13, pen)
            self._text(label, W - 10 - tw, y + 5, "ink", 1)
            extra = "MULIGHED  " if nxt.get("optional") else ""
            dur = fmt_dur(nxt["duration_seconds"]) if nxt.get("timed") else fmt_approx(nxt.get("duration_seconds"))
            self._text(extra + dur, 60, y + 5, "muted", 1)
            self._text(shorten(ascii_text(nxt["title"]), 36), 9, y + 20, "white", 2, W - 18)
        else:
            self._text("NAESTE", 9, y + 5, "muted", 1)
            self._text("Ingen flere punkter", 9, y + 26, "muted", 2)

        # Knapper
        self._layout_buttons(cur, nxt)

        # Besked
        if self.message and ticks_diff(self.message[2], ticks_ms()) > 0:
            text, color, _ = self.message
            # Over bunden af NÆSTE-feltet, så knapperne ikke dækkes
            self._rect(0, 139, W, 22, color)
            self._text(text, 6, 143, "ink" if color != "red" else "white", 2)
        else:
            self.message = None

        if self.presto is not None:
            self.presto.update()
        self.dirty = False

    def _button_specs(self, cur, nxt):
        """Knapper på faste pladser: (række, label, farve, nøgle, handling, punkt, tekstfarve).

        Øverst:  KLAR | START      (næste punkt)
        Nederst: ANNULLER | AFSLUT (annullér næste / afslut det, der afvikles)
        handling=None betyder en tom, deaktiveret plads.
        """
        specs = []
        if nxt:
            if nxt["status"] in ("pending", "requested"):
                specs.append((0, "KLAR", "green", "ready", "ready", nxt, "ink"))
            else:
                specs.append((0, "ER KLAR", "panel", "ready", None, None, "dark"))
            specs.append((0, "START", "red", "start", "start", nxt, "white"))
            specs.append((1, "ANNULLER", "dark", "cancel", "cancel", nxt, "white"))
        else:
            specs.append((1, "", "panel", "cancel", None, None, "dark"))
        if cur:
            specs.append((1, "AFSLUT", "blue", "finish", "finish", cur, "white"))
        else:
            specs.append((1, "AFSLUT", "panel", "finish", None, None, "dark"))
        return specs

    def _layout_buttons(self, cur, nxt):
        W = self.W
        rows = {0: [], 1: []}
        for spec in self._button_specs(cur, nxt):
            rows[spec[0]].append(spec)
        for r, y in ((0, 166), (1, 204)):
            specs = rows[r]
            if not specs:
                continue
            gap = 4
            w = (W - 4 - gap * (len(specs) - 1)) // len(specs)
            for i, (_, label, pen, key, action, item, ink) in enumerate(specs):
                self._button(2 + i * (w + gap), y, w, 34, label, pen, key, action, item, ink)

    def _layout_buttons_only(self):
        """Uden skærm (test): beregn kun knappernes placering."""
        st = self.state or {}
        cur, nxt = st.get("current"), st.get("next")
        rows = {0: [], 1: []}
        for spec in self._button_specs(cur, nxt):
            rows[spec[0]].append(spec)
        for r, y in ((0, 166), (1, 204)):
            specs = rows[r]
            if not specs:
                continue
            w = (self.W - 4 - 4 * (len(specs) - 1)) // len(specs)
            for i, (_, _l, _p, key, action, item, _i) in enumerate(specs):
                if action is not None:
                    self.buttons.append((2 + i * (w + 4), y, w, 34, key, action, item))

    # ------------------------------------------------ hovedløkke

    def run(self, touch):
        last_draw = 0
        while True:
            now = ticks_ms()
            if ticks_diff(now, self.last_poll) >= getattr(config, "POLL_MS", 1000):
                self.poll()
            touch.poll()
            if touch.state:
                x, y = self._touch_xy(touch)
                if self.pressed is None:
                    self.pressed = self._key_at(x, y)
                    self.press_xy = (x, y)
                    self.dirty = True
            elif self.pressed is not None:
                key = self.pressed
                self.pressed = None
                x, y = self.press_xy
                if self._key_at(x, y) == key:
                    self.handle_tap(x, y)
                self.dirty = True
            # Tegn ved ændringer og hvert sekund (nedtælling)
            if self.dirty or ticks_diff(now, last_draw) >= 1000:
                self.draw()
                last_draw = now
            time.sleep_ms(20)

    def _touch_xy(self, touch):
        x, y = touch.x, touch.y
        if x >= self.W or y >= self.H:  # fuld opløsning -> skaleret visning
            x, y = x * self.W // 480, y * self.H // 480
        return x, y

    def _key_at(self, x, y):
        for (bx, by, bw, bh, key, _a, _i) in self.buttons:
            if bx <= x < bx + bw and by <= y < by + bh:
                return key
        return None


# ---------------------------------------------------------------- opstart


def connect_wifi(display_msg):
    import network

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
        for i in range(60):
            if wlan.isconnected():
                break
            display_msg("Forbinder til WiFi ... %d" % i)
            time.sleep(0.5)
    return wlan.isconnected()


def main():
    from presto import Presto

    presto = Presto(ambient_light=False)
    display = presto.display
    display.set_font("bitmap8")
    app = App(display=display, presto=presto)

    def msg(text):
        app._rect(0, 0, app.W, app.H, "bg")
        app._text(ascii_text(text), 8, app.H // 2 - 8, "white", 2)
        presto.update()

    while not connect_wifi(msg):
        msg("WiFi fejlede - proever igen")
        time.sleep(3)
    msg("Forbinder til server ...")
    app.run(presto.touch)


if __name__ == "__main__":
    main()
