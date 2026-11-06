/* Match intelligence page: header, team intel, match stats and Key Players. */
(function () {
  "use strict";
  var U = window.UCL;
  var box = document.getElementById("match");

  var STATS = [
    ["minutes", "Minutes"], ["goals", "Goals"], ["assists", "Assists"], ["xg", "xG"], ["shots", "Shots"],
    ["key_passes", "Key passes"], ["dribbles", "Successful dribbles"], ["tackles", "Tackles"], ["recoveries", "Recoveries"]
  ];

  function fmt(key, v) {
    if (v === null || v === undefined) return null;
    return key === "xg" ? Number(v).toFixed(2) : String(Math.round(v));
  }

  function hero(m, round) {
    var k = m.kickoff || {};
    var when = [];
    var day = (k.local && k.local.date) || (k.pkt && k.pkt.date);
    if (day) when.push("<span>" + U.esc(day) + "</span>");
    else if (m.date) when.push("<span>" + U.esc(U.formatDate(m.date)) + "</span>");
    if (k.local) when.push("<span>Local <b>" + U.esc(k.local.time) + "</b> " + U.esc(k.local.abbreviation || "") + "</span>");
    if (k.pkt) {
      var pktDay = k.local && k.local.date !== k.pkt.date ? " (" + k.pkt.date.slice(0, 3) + ")" : "";
      when.push("<span>PKT <b>" + U.esc(k.pkt.time) + "</b>" + U.esc(pktDay) + "</span>");
    }
    if (round) when.push("<span>" + U.esc(round) + "</span>");

    var pred = "";
    if (m.prediction && m.prediction.percent) {
      pred = '<div class="mh-prob">' + U.probBar(m.prediction,
        m.status === "upcoming" ? "Model estimate (Elo + Poisson)" : "Pre-match model estimate — not the result") + "</div>";
    }
    return '<section class="match-hero" aria-label="Match summary"><div class="mh-stars">' + U.starRing(8, 140, 36, 380) + "</div>" +
      '<div class="mh-grid">' +
      '<div class="mh-team">' + U.crest(m.away) + '<div class="team-name">' + U.esc(m.away.name) + '</div><span class="side-tag">AWAY (A)</span></div>' +
      '<div class="mh-centre centre">' + U.centreBlock(m) + "</div>" +
      '<div class="mh-team">' + U.crest(m.home) + '<div class="team-name">' + U.esc(m.home.name) + '</div><span class="side-tag">HOME (H)</span></div>' +
      "</div>" + '<div class="mh-when">' + when.join("") + "</div>" + pred + "</section>";
  }

  function intelPanel(team, label) {
    var i = team.intel || {};
    var items = [];
    if (i.manager) items.push('<div class="intel-item"><div class="k">Manager</div><div class="v">' + U.esc(i.manager) + "</div></div>");
    if (i.formation) {
      items.push('<div class="intel-item"><div class="k">Latest formation</div><div class="v">' + U.esc(i.formation) + "</div>" +
        (i.formation_match ? '<div class="sub">' + U.esc(i.formation_match) + "</div>" : "") + "</div>");
    }
    var content = items.length ? '<div class="intel-row">' + items.join("") + "</div>"
      : '<p class="muted" style="margin:0">Manager and formation will appear after this club\'s first 2026/27 Champions League match with a confirmed lineup.</p>';
    return '<div class="panel"><h3 class="panel-title">' + U.crest(team) + U.esc(team.name) + ' <span class="side-tag">' + label + "</span></h3>" + content + "</div>";
  }

  function statsTable(rows) {
    if (!rows || !rows.length) return "";
    var body = rows.map(function (r) {
      return "<tr><td>" + U.esc(r.away) + '</td><td class="lbl">' + U.esc(r.label) + "</td><td>" + U.esc(r.home) + "</td></tr>";
    }).join("");
    return '<div class="section-head"><h2 class="section-title">Match Statistics</h2><span class="muted">Away · Home</span></div>' +
      '<div class="panel"><table class="team-stats"><tbody>' + body + "</tbody></table></div>";
  }

  function playerCard(p) {
    var totals = p.totals || {};
    var chips = STATS.filter(function (s) { return totals[s[0]] !== null && totals[s[0]] !== undefined; }).map(function (s) {
      return '<span class="chip">' + U.esc(s[1]) + " <b>" + U.esc(fmt(s[0], totals[s[0]])) + "</b></span>";
    }).join("");
    var apps = (p.appearances || []).map(function (a) {
      var res = a.result ? '<span class="res ' + U.esc(a.result.outcome) + '">' + U.esc(a.result.outcome) + " " + a.result.for + "–" + a.result.against + "</span>" : "";
      var stats = STATS.filter(function (s) { return a.stats && a.stats[s[0]] !== null && a.stats[s[0]] !== undefined; }).map(function (s) {
        return "<span>" + U.esc(s[1]) + " <b>" + U.esc(fmt(s[0], a.stats[s[0]])) + "</b></span>";
      }).join("");
      return '<div class="app-row"><div class="app-title"><span>' + U.esc(a.label) + " · vs " + U.esc(a.opponent) + " (" + U.esc(a.venue) + ")</span>" + res + "</div>" +
        '<div class="app-stats">' + stats + "</div></div>";
    }).join("");
    var n = (p.appearances || []).length;
    return '<article class="player"><div class="player-head">' + U.avatar(p) + "<div>" +
      '<div class="player-name">' + U.esc(p.name) + "</div>" +
      (p.position ? '<div class="player-pos">' + U.esc(p.position) + "</div>" : "") +
      '<div class="player-pos">Last ' + n + " Champions League appearance" + (n === 1 ? "" : "s") + "</div></div></div>" +
      '<div class="chips">' + chips + "</div>" +
      '<details class="apps"><summary>Appearance breakdown</summary>' + apps + "</details></article>";
  }

  function keyPlayersPanel(team, label) {
    var list = team.key_players || [];
    var content = list.length ? '<div class="players">' + list.map(playerCard).join("") + "</div>"
      : '<p class="muted" style="margin:0">Key players appear once this club has played 2026/27 Champions League matches with published player statistics.</p>';
    return '<div class="panel"><h3 class="panel-title">' + U.crest(team) + U.esc(team.name) + ' <span class="side-tag">' + label + "</span></h3>" + content + "</div>";
  }

  function render(data) {
    var m = data.match;
    if (!U.inSeason(m)) {
      box.innerHTML = U.emptyState("Match not found", "This fixture isn't part of the 2026/27 Champions League.");
      return;
    }
    document.title = m.away.name + " vs " + m.home.name + " · UCL Analytics";
    var t = data.teams || {};
    box.innerHTML = hero(m, data.round) +
      '<div class="section-head"><h2 class="section-title">Team Intelligence</h2></div>' +
      '<div class="two-col">' + intelPanel(t.away || m.away, "(A)") + intelPanel(t.home || m.home, "(H)") + "</div>" +
      statsTable(data.team_stats) +
      '<div class="section-head"><h2 class="section-title">Key Players</h2><span class="muted">Last three Champions League appearances</span></div>' +
      '<div class="two-col">' + keyPlayersPanel(t.away || m.away, "(A)") + keyPlayersPanel(t.home || m.home, "(H)") + "</div>";
  }

  var key = new URLSearchParams(location.search).get("key");
  if (!key) {
    box.innerHTML = U.emptyState("Choose a match", "Pick a fixture from the Fixtures page to see its match intelligence.");
    return;
  }
  U.api("/api/matches/" + encodeURIComponent(key)).then(render).catch(function (err) {
    box.innerHTML = U.errorState(err);
  });
})();
