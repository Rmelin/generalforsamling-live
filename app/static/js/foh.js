/* FOH – administration og afvikling. */
(function () {
  "use strict";
  var L = window.Live, esc = L.esc;

  var selectedId = null;
  var editor = { id: null, version: null, dirty: false };
  var showArchive = false, showHistory = false;
  var seenRequests = {}; // id -> requested_at, til fremhævelse af nye anmodninger
  var placeFor = null;    // det valgte punkt, som "Indsæt"-vælgeren sidst blev sat efter
  var dragId = null;      // punkt, der trækkes
  var listFilter = "all"; // all | video | novideo

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
      var t = L.parseTypeValue($("qa-type").value);
      var payload = {
        title: title, item_type: t.item_type, has_video: t.has_video, duration_seconds: dur,
        optional: $("qa-optional").checked
      };
      var place = $("qa-place").value;
      if (place === "selected" && selectedId != null) payload.after_id = selectedId;
      else if (place === "after_live") payload.place = "after_live";
      return L.api("POST", "/api/items", payload).then(function (res) {
        $("qa-title").value = ""; $("qa-duration").value = ""; $("qa-optional").checked = false;
        // Vælg det nye punkt, så næste "Efter valgte punkt" kommer lige efter det.
        if (!editor.dirty) { selectedId = res.item.id; placeFor = null; render(); }
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
    renderPlaceSelect();
    if (dragId == null) renderList(); // genopbyg ikke listen midt i et træk
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

  function renderPlaceSelect() {
    var sel = $("qa-place");
    var item = selectedId != null ? L.byId(selectedId) : null;
    var active = item && ["pending", "requested", "ready", "live"].indexOf(item.status) >= 0;
    var optSel = sel.querySelector("[value=selected]");
    var optLive = sel.querySelector("[value=after_live]");
    optSel.disabled = !active;
    optSel.textContent = active ? "Efter: " + (item.title.length > 22 ? item.title.slice(0, 21) + "…" : item.title) : "Efter valgte punkt";
    optLive.disabled = !L.current();
    // Standard: efter det valgte punkt, når et er valgt – ellers sidst.
    if (placeFor !== selectedId) {
      placeFor = selectedId;
      sel.value = active ? "selected" : "bottom";
    }
    if (sel.selectedOptions[0] && sel.selectedOptions[0].disabled) sel.value = "bottom";
  }

  function renderVideoSummary(all) {
    var vids = all.filter(function (i) { return i.has_video; });
    var box = $("video-summary");
    if (!vids.length) { box.hidden = true; return; }
    var loaded = vids.filter(function (i) { return i.qlab_loaded; }).length;
    var missing = vids.length - loaded;
    box.hidden = false;
    box.className = "video-summary" + (missing ? " has-missing" : " all-ok");
    box.innerHTML = "🎬 <strong>" + vids.length + "</strong> punkt" + (vids.length === 1 ? "" : "er") + " med video · " +
      (missing ? '<span class="vs-missing">' + missing + " ikke indlæst i QLab</span>" : '<span class="vs-ok">alle indlæst i QLab ✓</span>') +
      (listFilter !== "video" ? ' <button type="button" class="btn btn-sm btn-ghost" data-filter="video">Vis dem</button>' : "");
  }

  function renderList() {
    var all = L.active();
    var filtered = listFilter !== "all";
    var list = all.filter(function (i) {
      return listFilter === "all" || (listFilter === "video" ? i.has_video : !i.has_video);
    });
    $("active-count").textContent = filtered ? "(" + list.length + " af " + all.length + " aktive)" : "(" + all.length + " aktive)";
    renderVideoSummary(all);
    var btns = document.querySelectorAll(".list-filter [data-filter]");
    for (var b = 0; b < btns.length; b++) btns[b].setAttribute("aria-pressed", String(btns[b].getAttribute("data-filter") === listFilter));
    $("item-list").classList.toggle("is-filtered", filtered);
    var html = list.map(function (item, idx) {
      var num = all.indexOf(item) + 1; // nummer i hele programmet, også når der er filtreret
      var cls = "item-row st-row-" + item.status + (item.id === selectedId ? " selected" : "") + (item.optional ? " is-optional" : "");
      if (item.status === "requested") cls += " attention";
      if (item.status === "live") cls += " live-hl";
      return '<li class="' + cls + '" data-id="' + item.id + '" tabindex="0">' +
        (filtered ? '<span class="row-grip"></span>'
          : '<span class="row-grip" draggable="true" title="Træk for at flytte" aria-hidden="true">⋮⋮</span>') +
        '<span class="row-num">' + num + "</span>" +
        '<span class="row-main"><span class="row-title">' + esc(item.title) + "</span>" +
        '<span class="row-meta">' + L.typeChip(item) + L.optChip(item) + L.qlabChip(item, true) +
        (item.technical_notes ? '<span class="row-note" title="' + esc(item.technical_notes) + '">✎ ' + esc(item.technical_notes) + "</span>" : "") +
        "</span></span>" +
        '<span class="row-status">' + L.statusBadge(item.status) + "</span>" +
        '<span class="row-dur"><span title="Forventet">' + L.fmtItemDur(item) + "</span>" + rowActual(item) + "</span>" +
        '<span class="row-move">' + (filtered ? "" :
        '<button type="button" class="btn btn-icon" data-move="up" aria-label="Flyt op"' + (idx === 0 ? " disabled" : "") + ">▲</button>" +
        '<button type="button" class="btn btn-icon" data-move="down" aria-label="Flyt ned"' + (idx === list.length - 1 ? " disabled" : "") + ">▼</button>") +
        "</span></li>";
    }).join("");
    var empty = filtered
      ? '<li class="empty">Ingen aktive punkter ' + (listFilter === "video" ? "med" : "uden") + ' video.</li>'
      : '<li class="empty">Ingen aktive punkter. Opret et ovenfor.</li>';
    $("item-list").innerHTML = html || empty;
  }

  function renderArchive() {
    $("archive").hidden = !showArchive;
    if (!showArchive) return;
    var list = L.finished();
    $("archive-list").innerHTML = list.map(function (item) {
      return '<li class="item-row st-row-' + item.status + (item.id === selectedId ? " selected" : "") + '" data-id="' + item.id + '" tabindex="0">' +
        '<span class="row-num">' + L.fmtClock(item.ended_at || item.updated_at) + "</span>" +
        '<span class="row-main"><span class="row-title">' + esc(item.title) + '</span><span class="row-meta">' + L.typeChip(item) + "</span></span>" +
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
        "<span><strong>Scenen ønsker klargjort:</strong> " + esc(r.title) + " " + L.typeChip(r) + " " + L.optChip(r) + "</span>" +
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
      '<div class="now-meta">' + L.typeChip(cur) + L.optChip(cur) + L.qlabChip(cur, true) +
      "<span>Start " + L.fmtClockSec(cur.started_at) + "</span>" + timing + "</div>" +
      '<div class="card-actions"><button type="button" class="btn btn-lg btn-finish" data-act="finish" data-id="' + cur.id + '">■ Afslut <kbd>.</kbd></button></div>';
  }

  function renderNext() {
    var el = $("next-card");
    var chosen = L.chosen();
    var target = keyTarget();
    var fallback = !chosen.length;
    var list = fallback ? (target ? [target] : []) : chosen;
    if (!list.length) {
      el.innerHTML = '<div class="card-label">Næste</div><div class="muted">Ingen flere punkter.</div>';
      return;
    }
    var key = function (n, k) { return target && n.id === target.id ? " <kbd>" + k + "</kbd>" : ""; };
    el.innerHTML = '<div class="card-label">' + (fallback ? "Næste i programmet <span class=\"muted\">(ikke valgt af scenen)</span>" : "Næste (ønsket af scenen)") + "</div>" + list.map(function (n) {
      return '<div class="next-row st-row-' + n.status + '">' +
        '<div class="next-info"><div class="next-title">' + esc(n.title) + "</div>" +
        '<div class="now-meta">' + L.typeChip(n) + L.optChip(n) + L.qlabChip(n, true) + L.statusBadge(n.status) + "<span>" + L.fmtItemDur(n) + "</span></div>" +
        (n.technical_notes ? '<div class="note">' + esc(n.technical_notes) + "</div>" : "") + "</div>" +
        '<div class="card-actions">' +
        (n.status === "requested" || n.status === "pending" ? '<button type="button" class="btn btn-ready" data-act="ready" data-id="' + n.id + '">✓ Klar' + key(n, "M") + "</button>" : "") +
        '<button type="button" class="btn btn-start" data-act="start" data-id="' + n.id + '">▶ Start' + key(n, ",") + "</button>" +
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
    var tv = L.typeValue(item);
    var typeOpts = L.TYPE_OPTIONS.map(function (o) {
      return '<option value="' + o[0] + '"' + (o[0] === tv ? " selected" : "") + ">" + o[1] + "</option>";
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
      '<fieldset class="span2 opt-field qlab-field" id="ed-qlab-field"' + (item.has_video ? "" : " hidden") + '><legend>🎬 Video i QLab</legend>' +
      '<label>QLab-cue <input name="qlab_cue" maxlength="40" placeholder="f.eks. 12" value="' + esc(item.qlab_cue) + '"></label>' +
      '<div id="ed-qlab" class="ed-qlab"></div></fieldset>' +
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
      '<div class="card-actions editor-actions" id="ed-actions">' + actionButtons(item) + "</div>" +
      '<div class="card-actions editor-place" id="ed-place">' + placeButtons(item) + "</div>";

    var form = $("ed-form");
    form.addEventListener("input", function () { editor.dirty = true; $("ed-save").disabled = false; });
    form.item_type.addEventListener("change", function () {
      $("ed-qlab-field").hidden = !L.parseTypeValue(form.item_type.value).has_video && form.item_type.value !== "video";
    });
    renderEditorQlab(item);
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var dur = L.parseDur(form.duration.value);
      if (dur === null) { L.toast("Varighed skal angives som mm:ss eller minutter.", "error"); return; }
      var payload = {
        expected_version: editor.version,
        title: form.title.value.trim(),
        item_type: L.parseTypeValue(form.item_type.value).item_type,
        has_video: L.parseTypeValue(form.item_type.value).has_video,
        qlab_cue: form.qlab_cue.value.trim(),
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
    $("ed-place").innerHTML = placeButtons(item);
    renderEditorQlab(item);
  }

  // "Indlæst i QLab" gemmes med det samme (uden "Gem ændringer") og opdateres live.
  function renderEditorQlab(item) {
    var el = $("ed-qlab");
    if (!el) return;
    if (!item.has_video) {
      el.innerHTML = '<span class="muted">Gem først, så kan videoen markeres som indlæst.</span>';
      return;
    }
    el.innerHTML = '<button type="button" class="btn ' + (item.qlab_loaded ? "btn-qlab-ok" : "btn-qlab") + '" data-qlab="' + item.id + '">' +
      (item.qlab_loaded ? "✓ Indlæst i QLab" : "Markér som indlæst i QLab") + "</button>" +
      (item.qlab_loaded ? ' <span class="muted">Klik for at fjerne markeringen</span>' : "");
  }

  function placeButtons(item) {
    if (["pending", "requested", "ready"].indexOf(item.status) < 0) return "";
    var cur = L.current();
    return '<span class="muted">Flyt:</span>' +
      '<button type="button" class="btn btn-sm" data-place="top" data-id="' + item.id + '">⤒ Øverst</button>' +
      '<button type="button" class="btn btn-sm" data-place="after_live" data-id="' + item.id + '"' + (cur ? "" : " disabled") +
      ">↧ Efter det, der afvikles</button>" +
      '<button type="button" class="btn btn-sm" data-place="bottom" data-id="' + item.id + '">⤓ Sidst</button>';
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
      if (action === "finish") { doFinish(item, actBtn); return; }
      L.run(actBtn, function () { return L.action(item, action); });
      return;
    }
    var qlabBtn = e.target.closest("[data-qlab]");
    if (qlabBtn) {
      var qi = L.byId(parseInt(qlabBtn.getAttribute("data-qlab"), 10));
      if (!qi) return;
      var loaded = !qi.qlab_loaded;
      L.run(qlabBtn, function () {
        return L.api("POST", "/api/items/" + qi.id + "/qlab", { loaded: loaded });
      }, loaded ? '🎬 "' + qi.title + '" indlæst i QLab' : '"' + qi.title + '" ikke længere markeret som indlæst');
      return;
    }
    var filterBtn = e.target.closest("[data-filter]");
    if (filterBtn) {
      listFilter = filterBtn.getAttribute("data-filter");
      renderList();
      return;
    }
    var placeBtn = e.target.closest("[data-place]");
    if (placeBtn) {
      var pid = parseInt(placeBtn.getAttribute("data-id"), 10);
      L.run(placeBtn, function () { return placeItem(pid, { where: placeBtn.getAttribute("data-place") }); });
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

  function placeItem(id, body) {
    return L.api("POST", "/api/items/" + id + "/place", body);
  }

  // ------------------------------------------------------------ afslut + fortryd

  function doFinish(item, btn) {
    return L.run(btn, function () {
      return L.action(item, "finish").then(function (res) {
        if (res && res.changed) showUndo(item);
      });
    });
  }

  var undoEl = null;
  function showUndo(item) {
    if (undoEl) undoEl.remove();
    var box = $("toasts");
    var el = document.createElement("div");
    el.className = "toast toast-undo";
    el.setAttribute("role", "status");
    var left = 5;
    el.innerHTML = '<span>■ "' + esc(item.title) + '" afsluttet</span>' +
      '<button type="button" class="btn btn-sm btn-primary">Fortryd (' + left + ")</button>";
    var btn = el.querySelector("button");
    var timer = setInterval(function () {
      left--;
      if (left <= 0) { clearInterval(timer); el.remove(); if (undoEl === el) undoEl = null; return; }
      btn.textContent = "Fortryd (" + left + ")";
    }, 1000);
    btn.addEventListener("click", function () {
      clearInterval(timer);
      L.run(btn, function () {
        return L.api("POST", "/api/items/" + item.id + "/actions/unfinish", { expected_status: "done" });
      }, "Afslutning fortrudt – punktet afvikles igen").finally(function () { el.remove(); });
    });
    box.appendChild(el);
    undoEl = el;
  }

  // ------------------------------------------------------------ tastaturgenveje
  // M = Klar, ',' = Start, '.' = Stop (afslut). Virker ikke, mens man skriver i et felt.

  function keyTarget() {
    var c = L.chosen();
    if (c.length) return c[0];
    var q = L.queue();
    return q.length ? q[0] : null;
  }

  function isTyping(el) {
    if (!el || !el.tagName) return false;
    if (el.isContentEditable) return true;
    var tag = el.tagName;
    if (tag === "TEXTAREA" || tag === "SELECT") return true;
    if (tag !== "INPUT") return false;
    return ["checkbox", "radio", "button", "submit", "reset", "file"].indexOf(el.type) < 0;
  }

  function flash(selector) {
    var b = document.querySelector(selector);
    if (!b) return null;
    b.classList.remove("key-flash"); void b.offsetWidth; b.classList.add("key-flash");
    return b;
  }

  function toggleKeyHelp(show) {
    var h = $("key-help");
    h.hidden = show === undefined ? !h.hidden : !show;
    if (!h.hidden && $("screens-panel")) { $("screens-panel").hidden = true; $("btn-screens").setAttribute("aria-expanded", "false"); }
  }
  $("btn-keys").addEventListener("click", function () { toggleKeyHelp(); });
  $("key-help-close").addEventListener("click", function () { toggleKeyHelp(false); });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && e.target.classList && e.target.classList.contains("item-row")) { e.target.click(); return; }
    if (e.key === "Escape") { toggleKeyHelp(false); return; }
    if (e.ctrlKey || e.metaKey || e.altKey || e.repeat || isTyping(e.target)) return;
    var k = e.key;
    if (k === "?") { e.preventDefault(); toggleKeyHelp(); return; }
    // Tegnet først; ellers den fysiske tast (samme plads på dansk og engelsk tastatur)
    if (k !== "m" && k !== "M" && k !== "," && k !== ".") {
      k = { KeyM: "m", Comma: ",", Period: "." }[e.code];
      if (!k) return;
    }
    e.preventDefault();
    if (!L.connected) { L.toast("Ingen forbindelse til serveren – handlingen er ikke udført.", "error"); return; }

    if (k === ".") {
      var cur = L.current();
      if (!cur) { L.toast("Intet punkt afvikles.", "info"); return; }
      var fb = flash('#now-card [data-act="finish"]');
      doFinish(cur, fb);
      return;
    }
    var t = keyTarget();
    if (!t) { L.toast("Der er ikke flere punkter.", "info"); return; }
    if (k === "m" || k === "M") {
      if (t.status === "ready") { L.toast('"' + t.title + '" er allerede klar.', "info"); return; }
      var rb = flash('#next-card [data-act="ready"][data-id="' + t.id + '"]');
      L.run(rb, function () { return L.action(t, "ready"); }, '✓ "' + t.title + '" er klar');
      return;
    }
    // Start
    var q = CONFIRM.start(t);
    if (q && !confirm(q)) return;
    var sb = flash('#next-card [data-act="start"][data-id="' + t.id + '"]');
    L.run(sb, function () { return L.action(t, "start"); }, '▶ "' + t.title + '" startet');
  });

  // ------------------------------------------------------------ træk og slip

  var listEl = $("item-list");
  function clearDrop() {
    var marks = listEl.querySelectorAll(".drop-before, .drop-after, .dragging");
    for (var i = 0; i < marks.length; i++) marks[i].classList.remove("drop-before", "drop-after", "dragging");
  }
  function dropTarget(e) {
    var row = e.target.closest && e.target.closest("#item-list .item-row");
    if (!row) {
      // Under sidste række: placér sidst
      var rows = listEl.querySelectorAll(".item-row");
      var last = rows[rows.length - 1];
      if (last && e.clientY > last.getBoundingClientRect().bottom) return { row: last, before: false };
      return null;
    }
    var r = row.getBoundingClientRect();
    return { row: row, before: e.clientY < r.top + r.height / 2 };
  }
  listEl.addEventListener("dragstart", function (e) {
    var grip = e.target.closest && e.target.closest(".row-grip");
    if (!grip) { e.preventDefault(); return; }
    var row = grip.closest(".item-row");
    dragId = parseInt(row.getAttribute("data-id"), 10);
    row.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", String(dragId));
    try { e.dataTransfer.setDragImage(row, 24, 20); } catch (err) {}
  });
  listEl.addEventListener("dragover", function (e) {
    if (dragId == null) return;
    var t = dropTarget(e);
    var marks = listEl.querySelectorAll(".drop-before, .drop-after");
    for (var i = 0; i < marks.length; i++) marks[i].classList.remove("drop-before", "drop-after");
    if (!t || parseInt(t.row.getAttribute("data-id"), 10) === dragId) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    t.row.classList.add(t.before ? "drop-before" : "drop-after");
  });
  listEl.addEventListener("drop", function (e) {
    if (dragId == null) return;
    e.preventDefault();
    var t = dropTarget(e);
    var id = dragId;
    clearDrop();
    dragId = null;
    if (!t) { render(); return; }
    var targetId = parseInt(t.row.getAttribute("data-id"), 10);
    if (targetId === id) { render(); return; }
    L.run(null, function () {
      return placeItem(id, t.before ? { before_id: targetId } : { after_id: targetId });
    });
  });
  listEl.addEventListener("dragend", function () {
    clearDrop();
    if (dragId != null) { dragId = null; render(); }
  });

  // ------------------------------------------------------------ historik

  var ACTION_NAMES = { create: "Oprettet", edit: "Redigeret", delete: "Slettet", move: "Flyttet",
    request: "Anmodet", withdraw: "Anmodning trukket", ready: "Klar", start: "Startet",
    finish: "Afsluttet", cancel: "Annulleret", reopen: "Genåbnet", unfinish: "Afslutning fortrudt",
    qlab: "QLab" };

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

  // ------------------------------------------------------------ tilsluttede skærme

  var KIND_LABELS = { stage: "Scene", monitor: "Monitor", foh: "FOH", unknown: "Ældre version – genindlæs siden" };
  var KIND_ORDER = ["stage", "monitor", "foh", "unknown"];
  var lastStages = null;   // antal scener ved sidste oversigt (null = ukendt)
  var stageLostAt = null;  // tidspunkt, hvor den sidste scene forsvandt

  function ageSeconds(idle) {
    return Math.max(0, idle + (Date.now() - L.presenceAt) / 1000);
  }
  function fmtAgo(sec) {
    sec = Math.floor(sec);
    if (sec < 5) return "lige nu";
    if (sec < 90) return sec + " s siden";
    if (sec < 5400) return Math.round(sec / 60) + " min siden";
    return Math.round(sec / 3600) + " t siden";
  }
  function fmtEpoch(epoch) {
    var d = new Date(epoch * 1000);
    return (d.getHours() < 10 ? "0" : "") + d.getHours() + ":" + (d.getMinutes() < 10 ? "0" : "") + d.getMinutes();
  }
  function setSeg(seg, state, text, title) {
    seg.classList.remove("ok", "warn", "bad", "unknown");
    seg.classList.add(state);
    seg.querySelector(".screens-text").textContent = text;
    seg.title = title || "";
  }

  function renderScreens(p) {
    var stageSeg = $("screens-stage"), prestoSeg = $("screens-presto");
    if (!p) {
      setSeg(stageSeg, "unknown", "Scene ?", "Ukendt – FOH har ikke forbindelse til serveren");
      prestoSeg.hidden = true;
      renderScreensPanel();
      return; // uden forbindelse ved vi intet om scenen; advarslen røres ikke
    }
    var stages = p.clients.filter(function (c) { return c.kind === "stage"; });
    var hidden = stages.filter(function (c) { return !c.visible; });
    if (!stages.length) {
      setSeg(stageSeg, "bad", "Ingen scene", "Ingen sceneskærm er tilsluttet");
    } else if (hidden.length) {
      setSeg(stageSeg, "warn", "Scene (" + stages.length + ") – skjult",
        hidden.length + " sceneskærm(e) er skjult eller minimeret");
    } else {
      setSeg(stageSeg, "ok", "Scene (" + stages.length + ")", stages.length + " sceneskærm(e) tilsluttet");
    }
    var dev = p.devices[0];
    prestoSeg.hidden = !dev;
    if (dev) setSeg(prestoSeg, dev.online ? "ok" : "bad", "Presto",
      dev.online ? "Presto er tilsluttet" : "Presto har ikke hentet data i " + fmtAgo(ageSeconds(dev.idle_seconds)));

    // Advarsel, når den sidste scene forsvinder – og besked, når den er tilbage.
    if (lastStages !== null && lastStages > 0 && stages.length === 0) {
      stageLostAt = Date.now();
    } else if (stages.length > 0 && stageLostAt !== null) {
      stageLostAt = null;
      L.toast("Scenen er tilsluttet igen.", "ok");
    }
    lastStages = stages.length;
    renderStageLost();
    renderScreensPanel();
  }

  function renderStageLost() {
    var el = $("stage-lost");
    if (stageLostAt === null) { el.hidden = true; return; }
    el.hidden = false;
    el.innerHTML = '<span class="stage-lost-icon" aria-hidden="true">⚠</span><div><strong>Scenen har mistet forbindelsen</strong>' +
      '<span>' + esc(fmtAgo((Date.now() - stageLostAt) / 1000)) +
      ' · Scenen ser ikke ændringer, før den er tilsluttet igen. Tjek skærm og netværk ved scenen.</span></div>';
  }

  function screenRow(c) {
    var age = ageSeconds(c.idle_seconds);
    var warn = !c.visible ? '<span class="screen-warn">Skjult / minimeret</span>' : "";
    var detail = [c.ip || "ukendt IP", c.screen, "tilsluttet kl. " + fmtEpoch(c.connected_at), "sidste svar " + fmtAgo(age)]
      .filter(Boolean).map(esc).join(" · ");
    return '<li class="screen-row' + (c.visible ? "" : " is-hidden") + '" title="' + esc(c.user_agent || "") + '">' +
      '<span class="screen-led ' + (c.visible ? "ok" : "warn") + '"></span>' +
      '<div><div class="screen-name">' + esc(c.name || "Unavngivet") + " " + warn +
      (c.id === L.connId ? ' <span class="muted screen-self">(denne skærm)</span>' : "") + '</div>' +
      '<div class="muted screen-detail">' + detail + "</div></div></li>";
  }

  function renderScreensPanel() {
    var panel = $("screens-panel");
    if (panel.hidden) return;
    var p = L.presence, body = $("screens-body");
    if (!p) { body.innerHTML = '<p class="muted">Ingen forbindelse til serveren – kan ikke se tilsluttede skærme.</p>'; return; }
    var html = "";
    KIND_ORDER.forEach(function (kind) {
      var list = p.clients.filter(function (c) { return c.kind === kind; });
      if (!list.length && kind !== "stage") return;
      html += '<h3 class="screens-group">' + esc(KIND_LABELS[kind]) + " (" + list.length + ")</h3>";
      html += list.length ? '<ul class="screen-list">' + list.map(screenRow).join("") + "</ul>"
        : '<p class="screen-none">Ingen sceneskærm er tilsluttet.</p>';
    });
    if (p.devices.length) {
      html += '<h3 class="screens-group">Presto</h3><ul class="screen-list">' + p.devices.map(function (d) {
        var age = ageSeconds(d.idle_seconds);
        return '<li class="screen-row"><span class="screen-led ' + (d.online ? "ok" : "bad") + '"></span><div>' +
          '<div class="screen-name">' + esc(d.name) + (d.online ? "" : ' <span class="screen-warn bad">Ikke tilsluttet</span>') + "</div>" +
          '<div class="muted screen-detail">' + esc([d.ip, "sidst set " + fmtAgo(age)].filter(Boolean).join(" · ")) + "</div></div></li>";
      }).join("") + "</ul>";
    }
    body.innerHTML = html;
  }

  function toggleScreens(show) {
    var panel = $("screens-panel");
    panel.hidden = show === undefined ? !panel.hidden : !show;
    $("btn-screens").setAttribute("aria-expanded", String(!panel.hidden));
    if (!panel.hidden) toggleKeyHelp(false);
    renderScreensPanel();
  }
  $("btn-screens").addEventListener("click", function () { toggleScreens(); });
  $("screens-close").addEventListener("click", function () { toggleScreens(false); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") toggleScreens(false); });
  // Opdatér "for x s siden" løbende.
  setInterval(function () { renderStageLost(); renderScreensPanel(); }, 2000);

  // ------------------------------------------------------------ start

  window.addEventListener("beforeunload", function (e) {
    if (editor.dirty) { e.preventDefault(); e.returnValue = ""; }
  });

  L.initTheme();
  L.onState(render);
  L.onPresence(renderScreens);
  renderScreens(null);
  L.start();
})();
