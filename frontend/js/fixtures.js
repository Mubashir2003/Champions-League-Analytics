/* Fixtures: upcoming / completed / all, grouped by day (PKT). */
(function () {
  "use strict";
  var U = window.UCL;
  var VIEWS = ["upcoming", "completed", "all"];
  var state = { view: "upcoming", matches: null };

  function currentView() {
    var v = new URLSearchParams(location.search).get("view");
    return VIEWS.indexOf(v) >= 0 ? v : "upcoming";
  }

  function dayKey(m) {
    var k = m.kickoff || {};
    return (k.local && k.local.date) || (k.pkt && k.pkt.date) || (m.date ? U.formatDate(m.date) : "Date to be confirmed");
  }

  function filtered() {
    var list = state.matches || [];
    if (state.view === "upcoming") {
      return list.filter(function (m) { return m.status === "upcoming" || m.status === "postponed"; });
    }
    if (state.view === "completed") {
      return list.filter(function (m) { return m.status === "completed" || m.status === "awaiting_result"; })
        .slice().sort(function (a, b) { return (b.kickoff_utc || b.date || "").localeCompare(a.kickoff_utc || a.date || ""); });
    }
    return list;
  }

  function render() {
    var box = document.getElementById("fixtures");
    var count = document.getElementById("fixture-count");
    document.querySelectorAll(".tabs button").forEach(function (b) {
      b.setAttribute("aria-selected", String(b.getAttribute("data-view") === state.view));
    });
    if (state.matches === null) return;
    var list = filtered();
    count.textContent = list.length ? list.length + (list.length === 1 ? " match" : " matches") : "";
    if (!list.length) {
      box.innerHTML = state.view === "completed"
        ? U.emptyState("No completed matches yet", "Results from the 2026/27 Champions League will appear here after each match.")
        : state.view === "upcoming"
          ? U.emptyState("No upcoming fixtures", "There are no scheduled 2026/27 Champions League fixtures right now.")
          : U.emptyState("No fixtures yet", "2026/27 Champions League fixtures will appear here once they are published.");
      return;
    }
    var groups = [], index = {};
    list.forEach(function (m) {
      var k = dayKey(m);
      if (!(k in index)) { index[k] = groups.length; groups.push({ day: k, items: [] }); }
      groups[index[k]].items.push(m);
    });
    box.innerHTML = groups.map(function (g) {
      return '<section class="date-group"><h3>' + U.esc(g.day) + '</h3><div class="fixture-list">' +
        g.items.map(function (m) { return U.fixtureCard(m); }).join("") + "</div></section>";
    }).join("");
  }

  function setView(v, push) {
    state.view = v;
    if (push) {
      var url = new URL(location.href);
      url.searchParams.set("view", v);
      history.pushState({ view: v }, "", url);
    }
    render();
  }

  document.querySelectorAll(".tabs button").forEach(function (b) {
    b.addEventListener("click", function () { setView(b.getAttribute("data-view"), true); });
  });
  window.addEventListener("popstate", function () { setView(currentView(), false); });

  state.view = currentView();
  render();
  U.api("/api/matches").then(function (data) {
    state.matches = (data.matches || []).filter(U.inSeason);
    render();
  }).catch(function (err) {
    document.getElementById("fixtures").innerHTML = U.errorState(err);
  });
})();
