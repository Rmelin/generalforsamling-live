/* Fælles klientlogik: WebSocket-synkronisering, API-kald, tema og formatering.
 * Serveren er autoritativ – klienten viser kun det, serveren har bekræftet. */
(function () {
  "use strict";

  var STATUS = {
    pending:   { label: "Afventer",          short: "Afventer",  icon: "○" },
    requested: { label: "Ønskes klargjort",  short: "Ønsket",    icon: "⚑" },
    ready:     { label: "Klar",              short: "Klar",      icon: "✓" },
    live:      { label: "Afvikles",          short: "Afvikles",  icon: "▶" },
    done:      { label: "Afsluttet",         short: "Afsluttet", icon: "■" },
    cancelled: { label: "Annulleret",        short: "Annulleret", icon: "✕" }
  };
  var TYPES = { speech: "Tale", video: "Video", other: "Andet" };
  var ACTIVE = { pending: 1, requested: 1, ready: 1, live: 1 };

  // ------------------------------------------------------------ formatering

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function fmtDur(sec) {
    if (sec == null || isNaN(sec)) return "–";
    sec = Math.max(0, Math.floor(sec));
    var h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    var ss = (s < 10 ? "0" : "") + s;
    if (h) return h + ":" + (m < 10 ? "0" : "") + m + ":" + ss;
    return m + ":" + ss;
  }

  // "5" = 5 min, "5:30" = 5 min 30 s, "1:05:00" = 1 t 5 min. Returnerer null ved fejl.
  function parseDur(str) {
    str = String(str || "").trim().replace(",", ".");
    if (!str) return 0;
    if (/^\d+(\.\d+)?$/.test(str)) return Math.round(parseFloat(str) * 60);
    var parts = str.split(":");
    if (parts.length < 2 || parts.length > 3) return null;
    var total = 0;
    for (var i = 0; i < parts.length; i++) {
      if (!/^\d+$/.test(parts[i])) return null;
      total = total * 60 + parseInt(parts[i], 10);
    }
    return total;
  }

  function parseIso(iso) { return iso ? Date.parse(iso) : null; }

  function fmtClock(iso) {
    var t = parseIso(iso);
    if (!t) return "–";
    var d = new Date(t);
    return pad(d.getHours()) + ":" + pad(d.getMinutes());
  }
  function fmtClockSec(iso) {
    var t = parseIso(iso);
    if (!t) return "–";
    var d = new Date(t);
    return pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
  }
  function pad(n) { return (n < 10 ? "0" : "") + n; }

  function statusBadge(status, opts) {
    var s = STATUS[status] || { label: status, icon: "?" };
    var big = opts && opts.big ? " badge-lg" : "";
    return '<span class="badge st-' + esc(status) + big + '"><span class="badge-icon" aria-hidden="true">' +
      s.icon + "</span>" + esc(s.label) + "</span>";
  }
  function typeChip(t) {
    return '<span class="chip type-' + esc(t) + '">' + esc(TYPES[t] || t) + "</span>";
  }

  // ------------------------------------------------------------ tilstand

  var listeners = [];
  var Live = {
    STATUS: STATUS, TYPES: TYPES,
    esc: esc, fmtDur: fmtDur, parseDur: parseDur, fmtClock: fmtClock, fmtClockSec: fmtClockSec,
    statusBadge: statusBadge, typeChip: typeChip, parseIso: parseIso,
    items: [], revision: -1, dbId: null, offset: 0, connected: false, hasState: false,

    onState: function (fn) { listeners.push(fn); if (this.hasState) fn(this); },

    now: function () { return Date.now() + this.offset; },

    applySnapshot: function (snap) {
      if (!snap || !snap.items) return;
      var sameDb = snap.db_id === this.dbId;
      if (sameDb && snap.revision < this.revision) return; // forældet – ignorér
      var changed = !sameDb || snap.revision !== this.revision || !this.hasState;
      this.dbId = snap.db_id;
      this.revision = snap.revision;
      this.items = snap.items;
      this.hasState = true;
      if (snap.server_time) this.offset = parseIso(snap.server_time) - Date.now();
      if (changed) {
        for (var i = 0; i < listeners.length; i++) {
          try { listeners[i](this); } catch (e) { console.error(e); }
        }
      }
    },

    byId: function (id) {
      for (var i = 0; i < this.items.length; i++) if (this.items[i].id === id) return this.items[i];
      return null;
    },
    active: function () { return this.items.filter(function (i) { return ACTIVE[i.status]; }); },
    current: function () {
      for (var i = 0; i < this.items.length; i++) if (this.items[i].status === "live") return this.items[i];
      return null;
    },
    queue: function () { return this.items.filter(function (i) { return ACTIVE[i.status] && i.status !== "live"; }); },
    // Punkter dirigenten har valgt: klar først, derefter i den rækkefølge de blev ønsket.
    chosen: function () {
      return this.items.filter(function (i) { return i.status === "requested" || i.status === "ready"; })
        .sort(function (a, b) {
          return (parseIso(a.requested_at) || 0) - (parseIso(b.requested_at) || 0) || a.sort_order - b.sort_order;
        });
    },
    next: function () { var c = this.chosen(); return c.length ? c[0] : null; },
    finished: function () {
      return this.items.filter(function (i) { return i.status === "done" || i.status === "cancelled"; })
        .sort(function (a, b) {
          return (parseIso(b.ended_at || b.updated_at) || 0) - (parseIso(a.ended_at || a.updated_at) || 0);
        });
    },
    elapsed: function (item) {
      var st = parseIso(item && item.started_at);
      if (!st) return null;
      var end = item.status === "live" ? this.now() : parseIso(item.ended_at);
      return end ? Math.max(0, (end - st) / 1000) : null;
    }
  };

  // ------------------------------------------------------------ toast / fejl

  function toast(msg, kind) {
    var box = document.getElementById("toasts");
    if (!box) { alert(msg); return; }
    var el = document.createElement("div");
    el.className = "toast toast-" + (kind || "info");
    el.setAttribute("role", kind === "error" ? "alert" : "status");
    el.innerHTML = '<span>' + esc(msg) + '</span><button type="button" class="toast-x" aria-label="Luk">×</button>';
    el.querySelector("button").onclick = function () { el.remove(); };
    box.appendChild(el);
    setTimeout(function () { el.remove(); }, kind === "error" ? 9000 : 3500);
  }
  Live.toast = toast;

  function ApiError(message, status) { this.message = message; this.status = status; }

  Live.api = function (method, url, body) {
    var opts = {
      method: method, credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-Live-Client": "1", "Accept": "application/json" }
    };
    if (body !== undefined) opts.body = JSON.stringify(body);
    return fetch(url, opts).catch(function () {
      throw new ApiError("Kunne ikke kontakte serveren. Handlingen er IKKE gennemført.", 0);
    }).then(function (res) {
      return res.json().catch(function () { return null; }).then(function (data) {
        if (data && data.state) Live.applySnapshot(data.state);
        if (res.ok) return data;
        if (res.status === 401) {
          location.href = "/login?next=" + encodeURIComponent(location.pathname);
        }
        if (res.status === 409) Live.refresh();
        var msg = "Handlingen mislykkedes (" + res.status + ").";
        if (data && typeof data.detail === "string") msg = data.detail;
        else if (data && Array.isArray(data.detail)) {
          msg = "Ugyldige data: " + data.detail.map(function (d) {
            return (d.loc ? d.loc[d.loc.length - 1] + " – " : "") + d.msg;
          }).join("; ");
        }
        throw new ApiError(msg, res.status);
      });
    });
  };

  Live.refresh = function () {
    return fetch("/api/state", { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (snap) { Live.applySnapshot(snap); })
      .catch(function () {});
  };

  // Kør en handling fra en knap: lås knappen, vis fejl, vis først resultat når serveren har svaret.
  Live.run = function (btn, fn, okMsg) {
    if (btn && btn.dataset.busy === "1") return Promise.resolve();
    if (btn) { btn.dataset.busy = "1"; btn.classList.add("busy"); btn.disabled = true; }
    return Promise.resolve().then(fn).then(function (res) {
      if (okMsg) toast(okMsg, "ok");
      return res;
    }).catch(function (err) {
      toast((err && err.message) || "Der opstod en fejl.", "error");
    }).finally(function () {
      if (btn) { btn.dataset.busy = ""; btn.classList.remove("busy"); btn.disabled = false; }
      notifyAll();
    });
  };

  Live.action = function (item, action) {
    return Live.api("POST", "/api/items/" + item.id + "/actions/" + action, { expected_status: item.status });
  };

  function notifyAll() {
    if (!Live.hasState) return;
    for (var i = 0; i < listeners.length; i++) { try { listeners[i](Live); } catch (e) { console.error(e); } }
  }
  Live.rerender = notifyAll;

  // ------------------------------------------------------------ WebSocket

  var ws = null, retries = 0, lastMsg = 0, reconnectTimer = null, started = false;

  function setConnected(ok) {
    var changed = Live.connected !== ok;
    Live.connected = ok;
    if (changed) setTimeout(notifyAll, 0);
    document.body.classList.toggle("is-offline", !ok);
    var banner = document.getElementById("conn-banner");
    if (banner) banner.hidden = ok;
    var dots = document.querySelectorAll(".conn-dot");
    for (var i = 0; i < dots.length; i++) {
      dots[i].classList.toggle("ok", ok);
      dots[i].classList.toggle("bad", !ok);
      var t = dots[i].querySelector(".conn-dot-text");
      if (t) t.textContent = ok ? "Online" : "Offline";
    }
  }

  function connect() {
    clearTimeout(reconnectTimer);
    if (ws && (ws.readyState === 0 || ws.readyState === 1)) return;
    var proto = location.protocol === "https:" ? "wss://" : "ws://";
    try { ws = new WebSocket(proto + location.host + "/ws"); }
    catch (e) { scheduleReconnect(); return; }
    var sock = ws;
    sock.onopen = function () { lastMsg = Date.now(); };
    sock.onmessage = function (ev) {
      lastMsg = Date.now();
      var msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (msg.type === "snapshot") {
        Live.applySnapshot(msg);
        retries = 0;
        if (!Live.connected) setConnected(true);
      } else if (msg.type === "ping" && msg.server_time) {
        Live.offset = parseIso(msg.server_time) - Date.now();
      }
    };
    sock.onclose = function () {
      if (sock !== ws) return;
      setConnected(false);
      scheduleReconnect();
    };
    sock.onerror = function () { try { sock.close(); } catch (e) {} };
  }

  function scheduleReconnect() {
    clearTimeout(reconnectTimer);
    retries++;
    var delay = Math.min(5000, 500 * Math.pow(2, Math.min(retries, 4)));
    var txt = document.getElementById("conn-banner-text");
    if (txt) txt.textContent = "Ingen forbindelse til serveren – forsøger igen (forsøg " + retries + ") …";
    reconnectTimer = setTimeout(connect, delay);
  }

  // Vagthund: kommer der ingen beskeder (server sender ping hvert 10. s), er forbindelsen død.
  setInterval(function () {
    if (ws && ws.readyState === 1 && Date.now() - lastMsg > 25000) {
      try { ws.close(); } catch (e) {}
      setConnected(false);
      ws = null;
      scheduleReconnect();
    }
  }, 5000);

  window.addEventListener("online", function () { retries = 0; connect(); });
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden && (!ws || ws.readyState > 1)) { retries = 0; connect(); }
  });

  Live.start = function () {
    if (started) return;
    started = true;
    setConnected(false);
    var banner = document.getElementById("conn-banner");
    if (banner) banner.hidden = true; // ingen advarsel under første opkobling
    setTimeout(function () { if (!Live.connected && banner) banner.hidden = false; }, 2500);
    connect();
    // Opdatér løbende ure hvert sekund.
    setInterval(Live.tick, 1000);
  };

  Live.tick = function () {
    var els = document.querySelectorAll("[data-elapsed-from]");
    var now = Live.now();
    for (var i = 0; i < els.length; i++) {
      var from = parseIso(els[i].getAttribute("data-elapsed-from"));
      var secs = Math.max(0, (now - from) / 1000);
      els[i].textContent = fmtDur(secs);
      var exp = parseInt(els[i].getAttribute("data-expected") || "0", 10);
      els[i].classList.toggle("overtime", exp > 0 && secs > exp);
    }
  };

  // ------------------------------------------------------------ tema

  var THEMES = ["dark", "light", "auto"];
  var THEME_LABEL = { dark: "Tema: Mørk", light: "Tema: Lys", auto: "Tema: Auto" };

  function currentTheme() {
    var t = document.documentElement.getAttribute("data-theme");
    return THEMES.indexOf(t) >= 0 ? t : "dark";
  }
  function applyTheme(t) {
    document.documentElement.setAttribute("data-theme", t);
    try { localStorage.setItem("live-theme", t); } catch (e) {}
    var btns = document.querySelectorAll("[data-theme-toggle]");
    for (var i = 0; i < btns.length; i++) btns[i].textContent = THEME_LABEL[t];
  }
  Live.initTheme = function () {
    var btns = document.querySelectorAll("[data-theme-toggle]");
    for (var i = 0; i < btns.length; i++) {
      btns[i].textContent = THEME_LABEL[currentTheme()];
      btns[i].addEventListener("click", function () {
        var t = THEMES[(THEMES.indexOf(currentTheme()) + 1) % THEMES.length];
        applyTheme(t);
      });
    }
  };

  window.Live = Live;
})();
