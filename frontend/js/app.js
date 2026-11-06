/* UCL Analytics — shared frontend helpers. Talks only to this site's /api routes. */
(function () {
  "use strict";

  var THEME_KEY = "ucl-theme";
  var SEASON = "2026/2027";

  /* ── Theme ─────────────────────────────────────────── */
  function readTheme() {
    try { return localStorage.getItem(THEME_KEY); } catch (e) { return null; }
  }
  function applyTheme(theme) {
    var t = theme === "day" ? "day" : "night";
    document.documentElement.setAttribute("data-theme", t);
    var btn = document.querySelector(".theme-toggle");
    if (btn) {
      btn.setAttribute("aria-label", t === "day" ? "Switch to night mode" : "Switch to day mode");
      btn.setAttribute("title", t === "day" ? "Night mode" : "Day mode");
    }
    return t;
  }
  function toggleTheme() {
    var next = document.documentElement.getAttribute("data-theme") === "day" ? "night" : "day";
    applyTheme(next);
    try { localStorage.setItem(THEME_KEY, next); } catch (e) { /* storage blocked: theme still switches */ }
  }
  applyTheme(readTheme());
  // Keep several open tabs in sync.
  window.addEventListener("storage", function (e) { if (e.key === THEME_KEY) applyTheme(e.newValue); });

  /* ── Utilities ─────────────────────────────────────── */
  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function api(path) {
    return fetch(path, { headers: { Accept: "application/json" } }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (body) {
        if (!res.ok) {
          var err = new Error((body && (body.message || body.detail)) || ("Request failed (" + res.status + ")"));
          err.status = res.status;
          throw err;
        }
        return body;
      });
    });
  }

  function hashHue(text) {
    var h = 0;
    for (var i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) >>> 0;
    return h % 360;
  }
  function initials(name) {
    var words = String(name || "?").replace(/[^\p{L}\p{N} ]/gu, " ").split(/\s+/).filter(function (w) {
      return w && !/^(fc|cf|ac|sc|afc|sk|fk|club|de|the)$/i.test(w);
    });
    if (!words.length) return "?";
    return (words.length === 1 ? words[0].slice(0, 3) : words[0][0] + words[1][0]).toUpperCase();
  }
  function fallbackCrestSVG(name, cls) {
    var hue = hashHue(String(name || ""));
    return '<svg class="' + esc(cls || "crest-fallback") + '" viewBox="0 0 40 40" role="img" aria-label="' + esc(name) + ' crest">' +
      '<path d="M20 2 L35 7 V19 C35 28 28.5 34.5 20 38 C11.5 34.5 5 28 5 19 V7 Z" fill="hsl(' + hue + ',55%,38%)" stroke="hsl(' + hue + ',60%,70%)" stroke-width="1.5"/>' +
      '<text x="20" y="23.5" text-anchor="middle" font-family="Barlow Condensed, Arial Narrow, sans-serif" font-weight="800" font-size="12" fill="#fff">' + esc(initials(name)) + "</text></svg>";
  }
  function crest(team, cls) {
    var name = (team && team.name) || "Club";
    if (team && team.logo) {
      return '<img class="' + esc(cls || "crest") + '" src="' + esc(team.logo) + '" alt="' + esc(name) + ' crest" loading="lazy" decoding="async" referrerpolicy="no-referrer" data-fallback-name="' + esc(name) + '">';
    }
    return fallbackCrestSVG(name, cls === "crest" || !cls ? "crest-fallback" : cls);
  }
  function avatar(player) {
    if (player && player.image) {
      return '<img class="avatar" src="' + esc(player.image) + '" alt="' + esc(player.name) + '" loading="lazy" referrerpolicy="no-referrer" data-avatar-initials="' + esc(initials(player.name)) + '">';
    }
    return '<div class="avatar-fallback" aria-hidden="true">' + esc(initials(player && player.name)) + "</div>";
  }
  // Replace any broken crest or player photo with a generated fallback.
  document.addEventListener("error", function (e) {
    var img = e.target;
    if (!img || img.tagName !== "IMG") return;
    if (img.hasAttribute("data-fallback-name")) {
      var wrap = document.createElement("span");
      wrap.innerHTML = fallbackCrestSVG(img.getAttribute("data-fallback-name"), "crest-fallback");
      var svg = wrap.firstChild;
      if (img.style.width) svg.style.width = img.style.width;
      img.replaceWith(svg);
    } else if (img.hasAttribute("data-avatar-initials")) {
      var div = document.createElement("div");
      div.className = "avatar-fallback";
      div.textContent = img.getAttribute("data-avatar-initials");
      img.replaceWith(div);
    }
  }, true);

  /* ── Decorative star ring (original artwork, Starball-inspired) ── */
  function starPath(cx, cy, r) {
    var pts = [];
    for (var i = 0; i < 10; i++) {
      var ang = -Math.PI / 2 + i * Math.PI / 5;
      var rad = i % 2 === 0 ? r : r * 0.42;
      pts.push((cx + rad * Math.cos(ang)).toFixed(2) + "," + (cy + rad * Math.sin(ang)).toFixed(2));
    }
    return "M" + pts.join("L") + "Z";
  }
  function starRing(count, ringR, starR, size) {
    var c = size / 2, d = "";
    for (var i = 0; i < count; i++) {
      var a = -Math.PI / 2 + i * 2 * Math.PI / count;
      d += starPath(c + ringR * Math.cos(a), c + ringR * Math.sin(a), starR);
    }
    return '<svg viewBox="0 0 ' + size + " " + size + '" aria-hidden="true" focusable="false"><path fill="currentColor" d="' + d + '"/>' +
      '<circle cx="' + c + '" cy="' + c + '" r="' + (ringR - starR * 1.6).toFixed(1) + '" fill="none" stroke="currentColor" stroke-width="' + (size / 160).toFixed(2) + '" opacity=".55"/></svg>';
  }
  function decorate() {
    document.querySelectorAll("[data-stars]").forEach(function (el) {
      var kind = el.getAttribute("data-stars");
      el.innerHTML = kind === "mark" ? starRing(8, 12, 4.4, 34) : starRing(8, 190, 52, 520);
    });
  }

  /* ── Kickoff & countdown ───────────────────────────── */
  function kickoffText(m, opts) {
    var k = m.kickoff || {};
    var parts = [];
    if (k.local) parts.push('<span><b>' + esc(k.local.time) + "</b> " + esc(k.local.abbreviation || "local") + " (local)</span>");
    if (k.pkt) {
      var pktDay = "";
      if (k.local && k.local.date !== k.pkt.date) pktDay = " · " + esc(k.pkt.date.slice(0, 3));
      parts.push("<span><b>" + esc(k.pkt.time) + "</b> PKT" + pktDay + "</span>");
    }
    if (!parts.length && m.date) parts.push("<span>" + esc(formatDate(m.date)) + "</span>");
    // The calendar date follows the venue when known, otherwise PKT (the PKT weekday is added above when it differs).
    var dayText = (k.local && k.local.date) || (k.pkt && k.pkt.date);
    if (opts && opts.withDate && dayText) parts.unshift("<span>" + esc(dayText) + "</span>");
    return parts.join("");
  }
  function formatDate(iso) {
    var d = new Date(iso + (iso.length === 10 ? "T12:00:00Z" : ""));
    if (isNaN(d)) return iso;
    return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" });
  }
  function countdownText(utc) {
    var diff = new Date(utc).getTime() - Date.now();
    if (isNaN(diff)) return "";
    if (diff <= 0) return "Kick-off";
    var s = Math.floor(diff / 1000), d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600),
      m = Math.floor((s % 3600) / 60), sec = s % 60;
    if (d > 0) return "in " + d + "d " + h + "h " + m + "m";
    return "in " + (h ? h + "h " : "") + String(m).padStart(2, "0") + "m " + String(sec).padStart(2, "0") + "s";
  }
  function tickCountdowns() {
    document.querySelectorAll("[data-countdown]").forEach(function (el) {
      el.textContent = countdownText(el.getAttribute("data-countdown"));
    });
  }
  setInterval(tickCountdowns, 1000);

  /* ── Prediction bar (Away | Draw | Home, matching card order) ── */
  function probBar(pred, caption) {
    if (!pred || !pred.percent) return "";
    var p = pred.percent, h = Number(p.home) || 0, d = Number(p.draw) || 0, a = Number(p.away) || 0;
    return '<div class="prob" role="img" aria-label="Model estimate: away win ' + a + "%, draw " + d + "%, home win " + h + '%">' +
      '<div class="prob-bar"><span class="s-away" style="width:' + a + '%"></span><span class="s-draw" style="width:' + d + '%"></span><span class="s-home" style="width:' + h + '%"></span></div>' +
      '<div class="prob-labels"><span class="l-away">Away win <b>' + a + '%</b></span><span class="l-draw">Draw <b>' + d + '%</b></span><span class="l-home">Home win <b>' + h + "%</b></span></div>" +
      (caption ? '<div class="prob-caption">' + esc(caption) + "</div>" : "") + "</div>";
  }

  /* ── Fixture card: away LEFT, home RIGHT ───────────── */
  function centreBlock(m) {
    if (m.status === "completed" && m.score) {
      return '<div class="score" aria-label="Final score">' + esc(m.score.away) + '<span class="sep">–</span>' + esc(m.score.home) + '</div><div class="ft">Full time</div>';
    }
    if (m.status === "awaiting_result") return '<div class="vs">vs</div><div class="pending">Result to follow</div>';
    if (m.status === "postponed") return '<div class="vs">vs</div><div class="pending">Postponed</div>';
    if (m.status === "cancelled") return '<div class="vs">vs</div><div class="pending">Cancelled</div>';
    var cd = m.kickoff_utc ? '<div class="countdown" data-countdown="' + esc(m.kickoff_utc) + '">' + esc(countdownText(m.kickoff_utc)) + "</div>" : "";
    return '<div class="vs">vs</div>' + cd;
  }
  function fixtureCard(m, opts) {
    opts = opts || {};
    var showPred = m.status === "upcoming" && m.prediction && m.prediction.type === "model_estimate";
    return '<a class="fixture-card" href="/match-details.html?key=' + encodeURIComponent(m.key) + '" aria-label="' +
      esc(m.away.name + " (away) at " + m.home.name + " (home)") + '">' +
      '<div class="fc-meta"><div class="when">' + kickoffText(m, { withDate: opts.withDate }) + "</div>" +
      (m.status === "completed" ? '<span class="pill">Result</span>' : m.status === "upcoming" ? '<span class="pill">Upcoming</span>' : "") + "</div>" +
      '<div class="fc-main">' +
      '<div class="team away">' + crest(m.away) + '<div class="team-name">' + esc(m.away.name) + '<span class="side-tag">(A)</span></div></div>' +
      '<div class="centre">' + centreBlock(m) + "</div>" +
      '<div class="team home"><div class="team-name"><span class="side-tag">(H)</span>' + esc(m.home.name) + "</div>" + crest(m.home) + "</div>" +
      "</div>" + (showPred ? probBar(m.prediction) : "") + "</a>";
  }

  /* ── States ────────────────────────────────────────── */
  var ICON_BALL = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7.5l3.8 2.8-1.5 4.4H9.7L8.2 10.3z"/><path d="M12 3v4.5M20.6 9.3l-4.8 1M17.3 19.4l-3-4.7M6.7 19.4l3-4.7M3.4 9.3l4.8 1"/></svg>';
  function emptyState(title, text) {
    return '<div class="empty-state">' + ICON_BALL + "<h3>" + esc(title) + "</h3><p>" + esc(text) + "</p></div>";
  }
  function errorState(err) {
    if (err && (err.status === 503 || err.status === 502)) {
      return emptyState("Match data is on its way", "We couldn't load the latest Champions League information right now. Please check back shortly.");
    }
    if (err && err.status === 404) return emptyState("Match not found", "This fixture isn't part of the 2026/27 Champions League.");
    return emptyState("Something went wrong", "Please refresh the page to try again.");
  }
  function skeletons(n) {
    var out = "";
    for (var i = 0; i < n; i++) out += '<div class="skeleton"></div>';
    return out;
  }

  /* ── Page boot ─────────────────────────────────────── */
  function markNav() {
    var page = document.body.getAttribute("data-page");
    document.querySelectorAll(".main-nav a").forEach(function (a) {
      if (a.getAttribute("data-nav") === page) a.setAttribute("aria-current", "page");
    });
  }
  function boot() {
    applyTheme(readTheme());
    var btn = document.querySelector(".theme-toggle");
    if (btn) btn.addEventListener("click", toggleTheme);
    decorate();
    markNav();
    var yr = document.querySelector("[data-year]");
    if (yr) yr.textContent = String(new Date().getFullYear());
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();

  // Season guard used by every page (the backend already filters; this is belt and braces).
  function inSeason(m) { return m && m.season === SEASON; }

  window.UCL = {
    api: api, esc: esc, crest: crest, avatar: avatar, fixtureCard: fixtureCard, probBar: probBar,
    kickoffText: kickoffText, countdownText: countdownText, emptyState: emptyState, errorState: errorState,
    skeletons: skeletons, formatDate: formatDate, inSeason: inSeason, starRing: starRing, SEASON: SEASON,
    centreBlock: centreBlock
  };
})();
