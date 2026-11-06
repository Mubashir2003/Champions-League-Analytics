/* Overview: season strip + the five most recently completed 2026/27 matches. */
(function () {
  "use strict";
  var U = window.UCL;
  var MAX_RECENT = 5;

  function renderStrip(all) {
    var strip = document.getElementById("season-strip");
    var done = all.filter(function (m) { return m.status === "completed" && m.score; });
    if (!done.length) return;
    var goals = done.reduce(function (s, m) { return s + m.score.home + m.score.away; }, 0);
    var upcoming = all.filter(function (m) { return m.status === "upcoming"; }).length;
    var tiles = [
      [done.length, "Matches played"],
      [goals, "Goals scored"],
      [(goals / done.length).toFixed(2), "Goals per match"],
      [upcoming, "Fixtures to come"]
    ];
    strip.innerHTML = '<div class="stat-strip">' + tiles.map(function (t) {
      return '<div class="stat-tile"><div class="num">' + U.esc(t[0]) + '</div><div class="lbl">' + U.esc(t[1]) + "</div></div>";
    }).join("") + "</div>";
    strip.hidden = false;
  }

  function load() {
    var box = document.getElementById("recent-results");
    U.api("/api/matches").then(function (data) {
      var all = (data.matches || []).filter(U.inSeason);
      renderStrip(all);
      var recent = all
        .filter(function (m) { return m.status === "completed" && m.score; })
        .sort(function (a, b) { return (b.kickoff_utc || b.date || "").localeCompare(a.kickoff_utc || a.date || ""); })
        .slice(0, MAX_RECENT);
      box.innerHTML = recent.length
        ? recent.map(function (m) { return U.fixtureCard(m, { withDate: true }); }).join("")
        : U.emptyState("No results yet", "Completed 2026/27 Champions League matches will appear here after the final whistle.");
    }).catch(function (err) {
      box.innerHTML = U.errorState(err);
    });
  }
  load();
})();
