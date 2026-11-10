/* Scene – touchskærm til dirigenter. Kan kun anmode om klargøring og fortryde. */
(function () {
  "use strict";
  var L = window.Live, esc = L.esc;
  var $ = function (id) { return document.getElementById(id); };
  var selectedId = null;

  function render() {
    var cur = L.current();
    $("stage-now").className = "stage-now" + (cur ? " live-hl" : "");
    $("stage-now").innerHTML = cur
      ? '<div class="stage-now-label">' + L.statusBadge("live") + "</div>" +
        (L.isTimed(cur) && cur.duration_seconds ? '<div class="stage-now-time">' + L.countdown(cur) + "</div>" : "") +
        '<div class="stage-now-title">' + esc(cur.title) + "</div>"
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
    updatePager();
  }

  // ------------------------------------------------------------ bladring
  // Mange touchskærme på Raspberry Pi sender tryk som musehændelser, så man
  // ikke kan swipe. Derfor: store Forrige/Næste-knapper + træk-for-at-rulle.

  var listEl = $("stage-list");

  function itemTops() {
    var pad = parseFloat(getComputedStyle(listEl).paddingTop) || 0;
    return Array.prototype.map.call(listEl.querySelectorAll(".stage-item"), function (li) {
      return li.offsetTop - pad;
    });
  }

  function page(dir) {
    var step = Math.max(60, listEl.clientHeight - 24);
    var cur = listEl.scrollTop, target = cur + dir * step, tops = itemTops(), best = target, i;
    if (dir > 0) {
      // Det punkt, der er delvist synligt nederst, kommer øverst på næste side.
      for (i = 0; i < tops.length; i++) if (tops[i] <= target && tops[i] > cur + 4) best = tops[i];
    } else {
      for (i = tops.length - 1; i >= 0; i--) if (tops[i] >= target && tops[i] < cur - 4) best = tops[i];
    }
    listEl.scrollTo({ top: Math.max(0, best), behavior: "smooth" });
  }

  var pagerRaf = 0;
  function updatePager() {
    cancelAnimationFrame(pagerRaf);
    pagerRaf = requestAnimationFrame(function () {
      var pager = $("stage-pager");
      var max = listEl.scrollHeight - listEl.clientHeight;
      var overflow = max > 2;
      if (pager.hidden === overflow) { pager.hidden = !overflow; return updatePager(); }
      if (!overflow) return;
      var step = Math.max(60, listEl.clientHeight - 24);
      var pages = Math.max(2, Math.ceil(max / step) + 1);
      var atEnd = listEl.scrollTop >= max - 2;
      var current = atEnd ? pages : Math.min(pages - 1, Math.round(listEl.scrollTop / step) + 1);
      $("pager-info").textContent = current + "/" + pages;
      $("btn-page-up").disabled = listEl.scrollTop <= 2;
      $("btn-page-down").disabled = atEnd;
    });
  }

  $("btn-page-up").addEventListener("click", function () { page(-1); });
  $("btn-page-down").addEventListener("click", function () { page(1); });
  listEl.addEventListener("scroll", updatePager, { passive: true });
  window.addEventListener("resize", updatePager);

  // Træk-for-at-rulle, når touch kommer ind som mus.
  var drag = null, suppressClick = false;
  listEl.addEventListener("pointerdown", function (e) {
    if (e.pointerType === "touch") return; // ægte touch ruller selv
    drag = { y: e.clientY, top: listEl.scrollTop, moved: false, id: e.pointerId };
  });
  listEl.addEventListener("pointermove", function (e) {
    if (!drag) return;
    var dy = e.clientY - drag.y;
    if (!drag.moved && Math.abs(dy) > 10) {
      drag.moved = true;
      try { listEl.setPointerCapture(drag.id); } catch (err) {}
    }
    if (drag.moved) listEl.scrollTop = drag.top - dy;
  });
  function endDrag() { if (drag && drag.moved) suppressClick = true; drag = null; }
  listEl.addEventListener("pointerup", endDrag);
  listEl.addEventListener("pointercancel", endDrag);


  $("stage-list").addEventListener("click", function (e) {
    if (suppressClick) { suppressClick = false; return; }
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

  // Justerbar kant til skærme, der skjuler pixels i kanten:  /stage?kant=16
  // Gemmes i browseren. /stage?kant=0 nulstiller.
  (function () {
    var v = new URLSearchParams(location.search).get("kant");
    try {
      if (v !== null) localStorage.setItem("live-stage-inset", String(Math.max(0, Math.min(80, parseInt(v, 10) || 0))));
      v = localStorage.getItem("live-stage-inset");
    } catch (e) {}
    if (v) document.documentElement.style.setProperty("--stage-inset", parseInt(v, 10) + "px");
  })();

  L.initTheme();
  L.initFullscreen();
  L.onState(render);
  L.start();
})();
