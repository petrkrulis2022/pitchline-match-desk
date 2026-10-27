(function () {
  var root = document.documentElement;
  var LANGS = ["en", "es", "cs"];
  var VIEWS = ["front", "live", "report", "how"];
  function safeGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function safeSet(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }

  function setLang(lang) {
    root.setAttribute("lang", lang);
    document.querySelectorAll(".lang button").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.dataset.setLang === lang));
    });
  }
  var saved = safeGet("pitchline-lang");
  setLang(LANGS.indexOf(saved) >= 0 ? saved : "en");
  document.querySelectorAll(".lang button").forEach(function (b) {
    b.addEventListener("click", function () { safeSet("pitchline-lang", b.dataset.setLang); setLang(b.dataset.setLang); });
  });

  function show(v) {
    if (VIEWS.indexOf(v) < 0) v = "front";
    VIEWS.forEach(function (n) { document.getElementById("view-" + n).hidden = n !== v; });
    document.querySelectorAll(".nav a[data-view]").forEach(function (a) {
      if (a.dataset.view === v) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    window.scrollTo(0, 0);
  }
  document.addEventListener("click", function (e) {
    var a = e.target.closest ? e.target.closest('a[href^="#"]') : null;
    if (!a) return;
    var v = a.getAttribute("href").slice(1);
    if (VIEWS.indexOf(v) < 0) return;
    e.preventDefault();
    try { history.replaceState(null, "", "#" + v); } catch (x) {}
    show(v);
  });
  window.addEventListener("hashchange", function () { show(location.hash.slice(1)); });
  show(location.hash.slice(1));

  var ticker = document.getElementById("ticker");
  if (!ticker) return;
  var SPEED = 90;
  var entries = Array.prototype.slice.call(ticker.querySelectorAll("[data-sec]"));
  var scoreEl = document.getElementById("score");
  var clockEl = document.getElementById("clock");
  var statusEl = document.getElementById("status-label");
  var liveEl = document.getElementById("live-label");
  var finalScore = scoreEl.textContent;
  var endSec = Math.max.apply(null, entries.map(function (e) { return +e.dataset.sec; }));
  var timer = null;
  var p1end = +ticker.dataset.p1end, gap = +ticker.dataset.gap;
  function fmt(sec) { var m = Math.floor(sec / 60), s = Math.floor(sec % 60); return m + ":" + (s < 10 ? "0" : "") + s; }
  function clockFor(t) {
    if (t <= p1end) return fmt(t);
    if (t < p1end + gap) return "HT";
    return fmt(2700 + t - p1end - gap);
  }
  function showAll() {
    clearInterval(timer); timer = null;
    entries.forEach(function (e) { e.classList.remove("hidden", "fresh"); });
    scoreEl.textContent = finalScore; clockEl.textContent = clockFor(endSec);
    statusEl.hidden = false; liveEl.hidden = true;
  }
  function replay() {
    clearInterval(timer);
    entries.forEach(function (e) { e.classList.add("hidden"); e.classList.remove("fresh"); });
    scoreEl.textContent = "0:0"; statusEl.hidden = true; liveEl.hidden = false;
    var matchSec = 0, last = Date.now();
    timer = setInterval(function () {
      var now = Date.now();
      matchSec += ((now - last) / 1000) * SPEED; last = now;
      clockEl.textContent = clockFor(Math.min(matchSec, endSec));
      entries.forEach(function (e) {
        if (e.classList.contains("hidden") && +e.dataset.sec <= matchSec) {
          e.classList.remove("hidden"); e.classList.add("fresh");
          if (e.dataset.score) scoreEl.textContent = e.dataset.score;
        }
      });
      if (matchSec >= endSec) showAll();
    }, 100);
  }
  document.getElementById("replay").addEventListener("click", replay);
  document.getElementById("showall").addEventListener("click", showAll);
})();
