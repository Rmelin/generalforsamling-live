/* FOH – administration og afvikling. */
(function () {
  "use strict";
  var L = window.Live, esc = L.esc;

  var selectedId = null;
  var editor = { id: null, version: null, dirty: false };
  var showArchive = false, showHistory = false;
  var seenRequests = {}; // id -> requested_at, til fremhævelse af nye anmodninger

  var $ = function (id) { return document.getElementById(id); };

  // ------------------------------------------------------------ hurtig oprettelse

  $("quick-add").addEventListener("submit", function (e) {
    e.preventDefault();
    var title = $("qa-title").value.trim();
    var dur = L.parseDur($("qa-duration").value);
    if (!title) return;
    if (dur === null) { L.toast("Varighed skal angives som mm:ss eller minutter.", "error"); return; }
    var btn = e.target.querySelector("button[type=submit]");
    L.run(btn, function () {
      return L.api("POST", "/api/items", {
        title: title, item_type: $("qa-type").value, duration_seconds: dur, optional: $("qa-optional").checked
      }).then(function (res) {
        $("qa-title").value = ""; $("qa-duration").value = ""; $("qa-optional").checked = false;
        $("qa-title").focus();
        return res;
      });
    }, "Punkt oprettet");
  });

  // ------------------------------------------------------------ CSV-import

  $("import-form").addEventListener("submit", function (e) {
    e.preventDefault();
    var file = $("import-file").files[0];
    if (!file) return;
    var mode = e.target.querySelector("[name=mode]:checked").value;
    if (mode === "replace" && !confirm(
      "Erstat programmet med indholdet af \"" + file.name + "\"?\n\n" +
      "Alle punkter, der hverken afvikles eller er afsluttet, fjernes fra listen. " +
      "De bevares i historikken. Det punkt, der afvikles nu, berøres ikke.")) return;
    var box = $("import-result");
    var fd = new FormData();
    fd.append("file", file);
    fd.append("mode", mode);
    L.run($("import-btn"), function () {
      return fetch("/api/import", {
        method: "POST", body: fd, credentials: "same-origin",
        headers: { "X-Live-Client": "1", "Accept": "application/json" }
      }).catch(function () {
        throw { message: "Kunne ikke kontakte serveren. Intet er importeret." };
      }).then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (data) {
          if (data.state) L.applySnapshot(data.state);
          if (res.status === 401) location.href = "/login?next=/foh";
          if (!res.ok) {
            box.hidden = false;
            box.className = "import-result error";
            box.innerHTML = "<strong>" + esc(data.detail || ("Fejl " + res.status)) + "</strong>" +
              (data.errors && data.errors.length ? "<ul>" + data.errors.map(function (m) { return "<li>" + esc(m) + "</li>"; }).join("") + "</ul>" : "");
            throw { message: data.detail || "Importen mislykkedes." };
          }
          box.hidden = false;
          box.className = "import-result ok";
          box.textContent = data.imported + " punkt(er) importeret" +
            (data.removed ? ", " + data.removed + " erstattet" : "") + ".";
          $("import-file").value = "";
          L.toast(data.imported + " punkter importeret", "ok");
        });
      });
    });
  });

  $("toggle-archive").addEventListener("change", function (e) { showArchive = e.target.checked; render(); });
  $("toggle-history").addEventListener("change", function (e) {
    showHistory = e.target.checked; $("history-card").hidden = !showHistory;
    if (showHistory) loadHistory();
  });
  $("history-refresh").addEventListener("click", loadHistory);

  // ------------------------------------------------------------ rendering

  function render() {
    renderList();
    renderArchive();
    renderAlert();
    renderNow();
    renderNext();
    renderEditor();
    L.tick();
    if (showHistory) loadHistoryDebounced();
  }

  function rowActual(item) {
    if (item.status === "live") return L.countdown(item, "elapsed");
    var el = L.elapsed(item);
    if (el != null && item.ended_at) {
      var over = item.duration_seconds && el > item.duration_seconds ? " overtime" : "";
      return '<span class="actual' + over + '" title="Faktisk varighed">' + L.fmtDur(el) + "</span>";
    }
    return "";
  }

  function renderList() {
    var list = L.active();
    $("active-count").textContent = "(" + list.length + " aktive)";
    var html = list.map(function (item, idx) {
      var cls = "item-row st-row-" + item.status + (item.id === selectedId ? " selected" : "") + (item.optional ? " is-optional" : "");
      if (item.status === "requested") cls += " attention";
      if (item.status === "live") cls += " live-hl";
      return '<li class="' + cls + '" data-id="' + item.id + '" tabindex="0">' +
        '<span class="row-num">' + (idx + 1) + "</span>" +
        '<span class="row-main"><span class="row-title">' + esc(item.title) + "</span>" +
        '<span class="row-meta">' + L.typeChip(item.item_type) + L.optChip(item) +
        (item.technical_notes ? '<span class="row-note" title="' + esc(item.technical_notes) + '">✎ ' + esc(item.technical_notes) + "</span>" : "") +
        "</span></span>" +
        '<span class="row-status">' + L.statusBadge(item.status) + "</span>" +
        '<span class="row-dur"><span title="Forventet">' + L.fmtItemDur(item) + "</span>" + rowActual(item) + "</span>" +
        '<span class="row-move">' +
        '<button type="button" class="btn btn-icon" data-move="up" aria-label="Flyt op"' + (idx === 0 ? " disabled" : "") + ">▲</button>" +
        '<button type="button" class="btn btn-icon" data-move="down" aria-label="Flyt ned"' + (idx === list.length - 1 ? " disabled" : "") + ">▼</button>" +
        "</span></li>";
    }).join("");
    $("item-list").innerHTML = html || '<li class="empty">Ingen aktive punkter. Opret et ovenfor.</li>';
  }

  function renderArchive() {
    $("archive").hidden = !showArchive;
    if (!showArchive) return;
    var list = L.finished();
    $("archive-list").innerHTML = list.map(function (item) {
      return '<li class="item-row st-row-' + item.status + (item.id === selectedId ? " selected" : "") + '" data-id="' + item.id + '" tabindex="0">' +
        '<span class="row-num">' + L.fmtClock(item.ended_at || item.updated_at) + "</span>" +
        '<span class="row-main"><span class="row-title">' + esc(item.title) + '</span><span class="row-meta">' + L.typeChip(item.item_type) + "</span></span>" +
        '<span class="row-status">' + L.statusBadge(item.status) + "</span>" +
        '<span class="row-dur"><span title="Forventet">' + L.fmtItemDur(item) + "</span>" + rowActual(item) + "</span>" +
        '<span class="row-move"><button type="button" class="btn btn-sm" data-reopen="1">Genåbn</button></span></li>';
    }).join("") || '<li class="empty">Ingen afsluttede punkter endnu.</li>';
  }

  function renderAlert() {
    var reqs = L.items.filter(function (i) { return i.status === "requested"; });
    var box = $("request-alert");
    if (!reqs.length) { box.hidden = true; box.innerHTML = ""; return; }
    var fresh = false;
    reqs.forEach(function (r) { if (seenRequests[r.id] !== r.requested_at) { fresh = true; seenRequests[r.id] = r.requested_at; } });
    box.hidden = false;
    box.innerHTML = reqs.map(function (r) {
      return '<div class="request-alert-row"><span class="badge-icon" aria-hidden="true">⚑</span>' +
        "<span><strong>Scenen ønsker klargjort:</strong> " + esc(r.title) + " " + L.typeChip(r.item_type) + " " + L.optChip(r) + "</span>" +
        '<button type="button" class="btn btn-ready" data-act="ready" data-id="' + r.id + '">✓ Markér klar</button></div>';
    }).join("");
    if (fresh) { box.classList.remove("flash"); void box.offsetWidth; box.classList.add("flash"); }
  }

  function renderNow() {
    var cur = L.current();
    var el = $("now-card");
    if (!cur) {
      el.className = "card now-card idle";
      el.innerHTML = '<div class="card-label">Afvikles nu</div><div class="now-empty">Intet punkt afvikles</div>';
      return;
    }
    el.className = "card now-card live live-hl";
    var timing = L.isTimed(cur) && cur.duration_seconds
      ? '<span class="now-time">Tilbage ' + L.countdown(cur) + ' <span class="muted">af ' + L.fmtDur(cur.duration_seconds) + "</span></span>"
      : '<span class="muted">' + L.fmtItemDur(cur) + "</span>";
    el.innerHTML = '<div class="card-label">Afvikles nu ' + L.statusBadge("live") + "</div>" +
      '<div class="now-title">' + esc(cur.title) + "</div>" +
      '<div class="now-meta">' + L.typeChip(cur.item_type) + L.optChip(cur) +
      "<span>Start " + L.fmtClockSec(cur.started_at) + "</span>" + timing + "</div>" +
      '<div class="card-actions"><button type="button" class="btn btn-lg btn-finish" data-act="finish" data-id="' + cur.id + '">■ Afslut</button></div>';
  }

  function renderNext() {
    var el = $("next-card");
    var chosen = L.chosen();
    if (!chosen.length) {
      el.innerHTML = '<div class="card-label">Næste (ønsket af scenen)</div><div class="muted">Ingen anmodning fra scenen.</div>';
      return;
    }
    el.innerHTML = '<div class="card-label">Næste (ønsket af scenen)</div>' + chosen.map(function (n) {
      return '<div class="next-row st-row-' + n.status + '">' +
        '<div class="next-info"><div class="next-title">' + esc(n.title) + "</div>" +
        '<div class="now-meta">' + L.typeChip(n.item_type) + L.optChip(n) + L.statusBadge(n.status) + "<span>" + L.fmtItemDur(n) + "</span></div>" +
        (n.technical_notes ? '<div class="note">' + esc(n.technical_notes) + "</div>" : "") + "</div>" +
        '<div class="card-actions">' +
        (n.status === "requested" ? '<button type="button" class="btn btn-ready" data-act="ready" data-id="' + n.id + '">✓ Klar</button>' : "") +
        '<button type="button" class="btn btn-start" data-act="start" data-id="' + n.id + '">▶ Start</button>' +
        "</div></div>";
    }).join("");
  }

  // ------------------------------------------------------------ editor

  function actionButtons(item) {
    var b = [];
    var s = item.status;
    if (s === "pending" || s === "requested") b.push(["ready", "✓ Klar", "btn-ready"]);
    if (s === "pending" || s === "requested" || s === "ready") b.push(["start", "▶ Start", "btn-start"]);
    if (s === "live") b.push(["finish", "■ Afslut", "btn-finish"]);
    if (s === "requested" || s === "ready") b.push(["withdraw", "↺ Nulstil til Afventer", ""]);
    if (s === "done" || s === "cancelled") b.push(["reopen", "↺ Genåbn", ""]);
    if (s !== "done" && s !== "cancelled") b.push(["cancel", "✕ Annullér", "btn-danger-ghost"]);
    return b.map(function (x) {
      return '<button type="button" class="btn ' + x[2] + '" data-act="' + x[0] + '" data-id="' + item.id + '">' + x[1] + "</button>";
    }).join("");
  }

  function fillEditor(item) {
    var el = $("editor-card");
    editor = { id: item.id, version: item.version, dirty: false };
    var typeOpts = Object.keys(L.TYPES).map(function (k) {
      return '<option value="' + k + '"' + (k === item.item_type ? " selected" : "") + ">" + L.TYPES[k] + "</option>";
    }).join("");
    var actual = L.elapsed(item);
    el.innerHTML =
      '<div class="card-head"><div class="card-label">Valgt punkt #' + item.id + "</div>" + '<span id="ed-status">' + L.statusBadge(item.status) + "</span></div>" +
      '<div id="ed-stale" class="stale-note" hidden>Punktet er ændret af en anden. <button type="button" class="btn btn-sm" id="ed-reload">Hent nyeste</button></div>' +
      '<form id="ed-form" class="editor-form" autocomplete="off">' +
      '<label class="span2">Titel<input name="title" maxlength="200" required value="' + esc(item.title) + '"></label>' +
      "<label>Type<select name=\"item_type\">" + typeOpts + "</select></label>" +
      '<label>Varighed (mm:ss) <small class="muted">– tælles kun ned for video</small><input name="duration" class="input-duration" value="' + L.fmtDur(item.duration_seconds) + '"></label>' +
      '<fieldset class="span2 opt-field"><legend>Afvikling</legend>' +
      '<label class="radio"><input type="radio" name="optional" value="0"' + (item.optional ? "" : " checked") + '> <span class="chip chip-required">Skal</span> Skal afvikles</label>' +
      '<label class="radio"><input type="radio" name="optional" value="1"' + (item.optional ? " checked" : "") + '> <span class="chip chip-optional">Mulighed</span> Kan springes over</label></fieldset>' +
      '<label class="span2">Beskrivelse<textarea name="description" rows="2" maxlength="5000">' + esc(item.description) + "</textarea></label>" +
      '<label class="span2">Tekniske noter <small class="muted">(vises på teknikermonitoren)</small><textarea name="technical_notes" rows="2" maxlength="5000">' + esc(item.technical_notes) + "</textarea></label>" +
      '<div class="editor-times span2 muted">' +
      "Oprettet " + L.fmtClock(item.created_at) +
      (item.started_at ? " · Start " + L.fmtClockSec(item.started_at) : "") +
      (item.ended_at ? " · Slut " + L.fmtClockSec(item.ended_at) : "") +
      " · Forventet " + L.fmtItemDur(item) +
      (actual != null && item.ended_at ? " · Faktisk " + L.fmtDur(actual) : "") + "</div>" +
      '<div class="editor-save span2"><button type="submit" class="btn btn-primary" id="ed-save" disabled>Gem ændringer</button>' +
      '<button type="button" class="btn btn-ghost" id="ed-delete">Slet</button></div>' +
      "</form>" +
      '<div class="card-actions editor-actions" id="ed-actions">' + actionButtons(item) + "</div>";

    var form = $("ed-form");
    form.addEventListener("input", function () { editor.dirty = true; $("ed-save").disabled = false; });
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var dur = L.parseDur(form.duration.value);
      if (dur === null) { L.toast("Varighed skal angives som mm:ss eller minutter.", "error"); return; }
      var payload = {
        expected_version: editor.version,
        title: form.title.value.trim(),
        item_type: form.item_type.value,
        duration_seconds: dur,
        description: form.description.value,
        technical_notes: form.technical_notes.value,
        optional: form.querySelector("[name=optional]:checked").value === "1"
      };
      L.run($("ed-save"), function () {
        return L.api("PATCH", "/api/items/" + editor.id, payload).then(function (res) {
          editor.dirty = false;
          fillEditor(res.item);
        }).catch(function (err) {
          if (err.status === 409) { $("ed-stale").hidden = false; }
          throw err;
        });
      }, "Gemt");
    });
    $("ed-delete").addEventListener("click", function () {
      if (!confirm("Slet \"" + item.title + "\"?\n\nPunktet skjules fra alle lister, men bevares i historikken.")) return;
      L.run(this, function () {
        return L.api("DELETE", "/api/items/" + item.id).then(function () { selectedId = null; });
      }, "Punkt slettet");
    });
    $("ed-reload").addEventListener("click", function () {
      var fresh = L.byId(editor.id);
      if (fresh) fillEditor(fresh);
    });
  }

  function renderEditor() {
    var el = $("editor-card");
    var item = selectedId != null ? L.byId(selectedId) : null;
    if (!item) {
      selectedId = null; editor = { id: null, version: null, dirty: false };
      el.innerHTML = '<div class="card-label">Valgt punkt</div><p class="muted">Vælg et punkt i listen for at redigere det.</p>';
      return;
    }
    if (editor.id !== item.id) { fillEditor(item); return; }
    if (item.version !== editor.version) {
      if (!editor.dirty) { fillEditor(item); return; }
      $("ed-stale").hidden = false; // brugeren redigerer – overskriv ikke deres input
    }
    // Status og handlinger opdateres altid fra serveren.
    $("ed-status").innerHTML = L.statusBadge(item.status);
    $("ed-actions").innerHTML = actionButtons(item);
  }

  // ------------------------------------------------------------ handlinger

  var CONFIRM = {
    cancel: function (it) { return "Annullér \"" + it.title + "\"?\n\nPunktet fjernes fra programmet, men kan genåbnes."; },
    start: function (it) {
      var cur = L.current();
      return cur && cur.id !== it.id ? "\"" + cur.title + "\" afvikles stadig og vil blive afsluttet.\n\nStart \"" + it.title + "\"?" : null;
    }
  };

  document.addEventListener("click", function (e) {
    var actBtn = e.target.closest("[data-act]");
    if (actBtn) {
      var item = L.byId(parseInt(actBtn.getAttribute("data-id"), 10));
      var action = actBtn.getAttribute("data-act");
      if (!item) return;
      var q = CONFIRM[action] && CONFIRM[action](item);
      if (q && !confirm(q)) return;
      L.run(actBtn, function () { return L.action(item, action); });
      return;
    }
    var row = e.target.closest(".item-row");
    if (!row) return;
    var id = parseInt(row.getAttribute("data-id"), 10);
    var moveBtn = e.target.closest("[data-move]");
    if (moveBtn) {
      L.run(moveBtn, function () { return L.api("POST", "/api/items/" + id + "/move", { direction: moveBtn.getAttribute("data-move") }); });
      return;
    }
    if (e.target.closest("[data-reopen]")) {
      var it = L.byId(id);
      if (it) L.run(e.target.closest("button"), function () { return L.action(it, "reopen"); }, "Punkt genåbnet");
      return;
    }
    if (editor.dirty && editor.id !== id && !confirm("Du har ikke-gemte ændringer. Kassér dem?")) return;
    selectedId = id;
    editor.dirty = false;
    render();
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && e.target.classList && e.target.classList.contains("item-row")) e.target.click();
  });

  // ------------------------------------------------------------ historik

  var ACTION_NAMES = { create: "Oprettet", edit: "Redigeret", delete: "Slettet", move: "Flyttet",
    request: "Anmodet", withdraw: "Anmodning trukket", ready: "Klar", start: "Startet",
    finish: "Afsluttet", cancel: "Annulleret", reopen: "Genåbnet" };

  function loadHistory() {
    L.api("GET", "/api/events?limit=300").then(function (data) {
      $("history-body").innerHTML = data.events.map(function (ev) {
        var from = ev.from_status ? (L.STATUS[ev.from_status] || {}).short || ev.from_status : "–";
        var to = ev.to_status ? (L.STATUS[ev.to_status] || {}).short || ev.to_status : "–";
        return "<tr><td>" + L.fmtClockSec(ev.created_at) + "</td><td>" + esc(ev.item_title) +
          ' <span class="muted">#' + (ev.item_id || "") + "</span></td><td>" + esc(ACTION_NAMES[ev.action] || ev.action) +
          "</td><td>" + esc(from) + " → " + esc(to) + "</td><td>" + esc(ev.actor) + "</td><td>" + esc(ev.details) + "</td></tr>";
      }).join("");
    }).catch(function (err) { L.toast(err.message, "error"); });
  }
  var histTimer = null;
  function loadHistoryDebounced() { clearTimeout(histTimer); histTimer = setTimeout(loadHistory, 300); }

  // ------------------------------------------------------------ start

  window.addEventListener("beforeunload", function (e) {
    if (editor.dirty) { e.preventDefault(); e.returnValue = ""; }
  });

  L.initTheme();
  L.onState(render);
  L.start();
})();
