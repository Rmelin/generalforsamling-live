/* Monitor – read-only informationsskærm til teknikere. */
(function () {
  "use strict";
  var L = window.Live, esc = L.esc;
  var $ = function (id) { return document.getElementById(id); };

  function notes(item) {
    return item.technical_notes ? '<div class="mon-notes"><span class="mon-notes-label">Teknik:</span> ' + esc(item.technical_notes) + "</div>" : "";
  }

  function render() {
    var cur = L.current();
    var queue = L.queue();
    var next = L.next();
    var nextChosen = !!next;
    if (!next && queue.length) next = queue[0];

    $("remaining").textContent = queue.length + (queue.length === 1 ? " punkt tilbage" : " punkter tilbage");

    $("mon-now").className = "mon-card mon-now" + (cur ? " live" : "");
    $("mon-now").innerHTML = '<h2 class="mon-label">Nu</h2>' + (cur
      ? '<div class="mon-now-title">' + esc(cur.title) + "</div>" +
        '<div class="mon-row">' + L.typeChip(cur.item_type) + L.optChip(cur) + L.statusBadge("live", { big: true }) + "</div>" +
        (L.isTimed(cur) && cur.duration_seconds
          ? '<div class="mon-times">' +
            '<div><span class="mon-k">Start</span><span class="mon-v">' + L.fmtClock(cur.started_at) + "</span></div>" +
            '<div><span class="mon-k">Tilbage</span><span class="mon-v">' + L.countdown(cur) + "</span></div>" +
            '<div><span class="mon-k">Længde</span><span class="mon-v">' + L.fmtDur(cur.duration_seconds) + "</span></div></div>"
          : '<div class="mon-times mon-times-2">' +
            '<div><span class="mon-k">Start</span><span class="mon-v">' + L.fmtClock(cur.started_at) + "</span></div>" +
            '<div><span class="mon-k">Forventet</span><span class="mon-v">' + L.fmtItemDur(cur) + "</span></div></div>") +
        notes(cur)
      : '<div class="mon-empty">Intet indslag i gang</div>');

    $("mon-next").className = "mon-card mon-next" + (next ? " st-row-" + next.status : "");
    $("mon-next").innerHTML = '<h2 class="mon-label">Næste' + (next && !nextChosen ? ' <small>(i programmet – ikke valgt af scenen)</small>' : "") + "</h2>" + (next
      ? '<div class="mon-next-title">' + esc(next.title) + "</div>" +
        '<div class="mon-row">' + L.typeChip(next.item_type) + L.optChip(next, true) + L.statusBadge(next.status, { big: true }) +
        '<span class="mon-dur">' + L.fmtItemDur(next) + "</span></div>" + notes(next)
      : '<div class="mon-empty">Intet næste indslag</div>');

    $("mon-list").innerHTML = queue.filter(function (i) { return !next || i.id !== next.id; }).map(function (item) {
      var hl = item.status === "requested" || item.status === "ready";
      return '<li class="mon-item st-row-' + item.status + (hl ? " highlight" : "") + (item.optional ? " is-optional" : "") + '">' +
        '<span class="mon-item-title">' + esc(item.title) + "</span>" +
        '<span class="mon-item-meta">' + L.optChip(item) + L.typeChip(item.item_type) + L.statusBadge(item.status) +
        '<span class="mon-dur">' + L.fmtItemDur(item) + "</span></span>" +
        (item.technical_notes ? '<span class="mon-item-notes">' + esc(item.technical_notes) + "</span>" : "") + "</li>";
    }).join("") || '<li class="empty">Ingen yderligere punkter</li>';
    L.tick();
  }

  // Fuldskærm
  Live.initFullscreen();
  document.addEventListener("keydown", function (e) { if (e.key === "f" || e.key === "F") Live.toggleFullscreen(); });

  // Skjul markør og værktøjer efter inaktivitet.
  var idleTimer = null;
  function wake() {
    document.body.classList.remove("idle");
    clearTimeout(idleTimer);
    idleTimer = setTimeout(function () { document.body.classList.add("idle"); }, 4000);
  }
  document.addEventListener("mousemove", wake);
  document.addEventListener("touchstart", wake);
  wake();

  L.initTheme();
  L.onState(render);
  L.start();
})();
