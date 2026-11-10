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
        '<div class="stage-now-time"><span data-elapsed-from="' + esc(cur.started_at) + '" data-expected="' + cur.duration_seconds + '"></span> / ' + L.fmtDur(cur.duration_seconds) + "</div>"
      : '<div class="stage-now-label muted">Intet i gang</div>';

    var chosen = L.chosen();
    $("stage-status").innerHTML = chosen.length
      ? chosen.map(function (c) {
          var msg = c.status === "ready" ? "FOH: KLAR" : "Venter på FOH …";
          return '<div class="stage-status-row st-row-' + c.status + '">' + L.statusBadge(c.status, { big: true }) +
            '<span class="stage-status-title">' + esc(c.title) + '</span><span class="stage-status-msg">' + msg + "</span></div>";
        }).join("")
      : '<div class="stage-status-row muted">Intet punkt ønsket klargjort. Vælg et punkt nedenfor.</div>';

    var list = L.queue();
    if (selectedId != null && !list.some(function (i) { return i.id === selectedId; })) selectedId = null;

    $("stage-list").innerHTML = list.map(function (item) {
      var sel = item.id === selectedId;
      return '<li role="option" aria-selected="' + sel + '" class="stage-item st-row-' + item.status + (sel ? " selected" : "") + '" data-id="' + item.id + '">' +
        '<span class="stage-item-title">' + esc(item.title) + "</span>" +
        '<span class="stage-item-meta">' + L.typeChip(item.item_type) + '<span class="stage-dur">' + L.fmtDur(item.duration_seconds) + "</span></span>" +
        '<span class="stage-item-status">' + L.statusBadge(item.status) + "</span></li>";
    }).join("") || '<li class="empty">Ingen punkter tilbage.</li>';

    var sel = selectedId != null ? L.byId(selectedId) : null;
    var reqBtn = $("btn-request"), undoBtn = $("btn-undo");
    var offline = !L.connected;
    reqBtn.disabled = offline || !sel || sel.status !== "pending";
    undoBtn.disabled = offline || !sel || (sel.status !== "requested" && sel.status !== "ready");
    reqBtn.textContent = sel && sel.status === "pending" ? "Anmod om klargøring: " + truncate(sel.title, 28) : "Anmod om klargøring";
    L.tick();
  }

  function truncate(s, n) { return s.length > n ? s.slice(0, n - 1) + "…" : s; }

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
  L.onState(render);
  L.start();
})();
