/* Scene – touchskærm til dirigenter. Kan kun anmode om klargøring og fortryde. */
(function () {
  "use strict";
  var L = window.Live, esc = L.esc;
  var $ = function (id) { return document.getElementById(id); };
  var selectedId = null;

  function render() {
    var cur = L.current();
    $("stage-now").innerHTML = cur
      ? '<div class="stage-now-label">' + L.statusBadge("live") + "</div>" +
        '<div class="stage-now-title">' + esc(cur.title) + "</div>" +
        (L.isTimed(cur) && cur.duration_seconds ? '<div class="stage-now-time">' + L.countdown(cur) + "</div>" : "")
      : '<div class="stage-now-label muted">Intet i gang</div>';

    var chosen = L.chosen();
    $("stage-status").innerHTML = chosen.length
      ? chosen.map(function (c) {
          var msg = c.status === "ready" ? "FOH: KLAR" : "Venter på FOH …";
          return '<div class="stage-status-row st-row-' + c.status + '">' + L.statusBadge(c.status, { big: true }) +
            '<span class="stage-status-title">' + esc(c.title) + " " + L.optChip(c) + '</span><span class="stage-status-msg">' + msg + "</span></div>";
        }).join("")
      : '<div class="stage-status-row muted">Intet punkt ønsket klargjort. Vælg et punkt nedenfor.</div>';

    var list = L.queue();
    var nReq = list.filter(function (i) { return !i.optional; }).length;
    var nOpt = list.length - nReq;
    $("stage-summary").innerHTML = '<span class="chip chip-required">Skal</span> ' + nReq + " tilbage" +
      (nOpt ? ' &nbsp; <span class="chip chip-optional">Mulighed</span> ' + nOpt + " tilbage" : "");
    if (selectedId != null && !list.some(function (i) { return i.id === selectedId; })) selectedId = null;

    $("stage-list").innerHTML = list.map(function (item) {
      var sel = item.id === selectedId;
      return '<li role="option" aria-selected="' + sel + '" class="stage-item st-row-' + item.status + (sel ? " selected" : "") + (item.optional ? " is-optional" : "") + '" data-id="' + item.id + '">' +
        '<span class="stage-item-title">' + esc(item.title) + "</span>" +
        '<span class="stage-item-meta">' + L.optChip(item, true) + L.typeChip(item.item_type) +
        '<span class="stage-dur">' + L.fmtItemDur(item) + "</span>" +
        // "Afventer" er standard og vises ikke – kun Ønsket/Klar fremhæves.
        (item.status !== "pending" ? L.statusBadge(item.status) : "") + "</span></li>";
    }).join("") || '<li class="empty">Ingen punkter tilbage.</li>';

    var sel = selectedId != null ? L.byId(selectedId) : null;
    var reqBtn = $("btn-request"), undoBtn = $("btn-undo");
    var offline = !L.connected;
    reqBtn.disabled = offline || !sel || sel.status !== "pending";
    undoBtn.disabled = offline || !sel || (sel.status !== "requested" && sel.status !== "ready");
    reqBtn.innerHTML = '<span>Anmod om klargøring</span>' +
      (sel && sel.status === "pending" ? '<span class="btn-sub">' + esc(sel.title) + "</span>" : "");
    L.tick();
  }


  $("stage-list").addEventListener("click", function (e) {
    var row = e.target.closest(".stage-item");
    if (!row) return;
    var id = parseInt(row.getAttribute("data-id"), 10);
    selectedId = selectedId === id ? null : id;
    render();
  });

  $("btn-request").addEventListener("click", function () {
    var item = L.byId(selectedId);
    if (!item) return;
    L.run(this, function () { return L.action(item, "request"); }, "Anmodning sendt til FOH");
  });

  $("btn-undo").addEventListener("click", function () {
    var item = L.byId(selectedId);
    if (!item) return;
    L.run(this, function () { return L.action(item, "withdraw"); }, "Anmodning trukket tilbage");
  });

  // Forhindr dobbelttryk-zoom og kontekstmenu på touchskærm.
  document.addEventListener("contextmenu", function (e) { e.preventDefault(); });

  L.initTheme();
  L.initFullscreen();
  L.onState(render);
  L.start();
})();
