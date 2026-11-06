/* Standings: 2026/27 league-phase table from /api/standings. */
(function () {
  "use strict";
  var U = window.UCL;

  function signed(n) { return n > 0 ? "+" + n : String(n); }

  function render(data) {
    var box = document.getElementById("standings");
    var rows = data.rows || [];
    if (!rows.length) {
      box.innerHTML = U.emptyState("The table starts with the first results",
        "The 2026/27 league-phase table will appear here once league-phase matches have been played.");
      return;
    }
    var note = data.complete
      ? "Final league-phase table · <b>" + data.matches_played + "</b> of " + data.matches_total + " matches played"
      : "Table after <b>" + data.matches_played + "</b> of " + data.matches_total + " league-phase matches";
    var anyTie = rows.some(function (r) { return r.tie_unresolved; });
    var body = rows.map(function (r) {
      return '<tr class="z-' + U.esc(r.zone || "") + '">' +
        '<td class="pos">' + r.position + "</td>" +
        '<td class="club"><div class="cell">' + U.crest({ name: r.club, logo: r.logo }) + '<span class="name">' + U.esc(r.club) + "</span>" +
        (r.tie_unresolved ? '<span class="tie-mark" title="Level on every tiebreaker the data supports">*</span>' : "") + "</div></td>" +
        "<td>" + r.played + "</td><td>" + r.won + "</td><td>" + r.drawn + "</td><td>" + r.lost + "</td>" +
        "<td>" + r.gf + "</td><td>" + r.ga + "</td><td>" + signed(r.gd) + '</td><td class="pts">' + r.points + "</td></tr>";
    }).join("");
    box.innerHTML = '<p class="table-note">' + note + "</p>" +
      '<div class="table-wrap"><table class="standings"><caption class="sr-only">Champions League 2026/27 league phase standings</caption>' +
      '<thead><tr><th scope="col" title="Position">Pos</th><th scope="col" class="club">Club</th>' +
      '<th scope="col" title="Played">P</th><th scope="col" title="Won">W</th><th scope="col" title="Drawn">D</th><th scope="col" title="Lost">L</th>' +
      '<th scope="col" title="Goals for">GF</th><th scope="col" title="Goals against">GA</th><th scope="col" title="Goal difference">GD</th><th scope="col" title="Points">Pts</th></tr></thead>' +
      "<tbody>" + body + "</tbody></table></div>" +
      '<div class="legend"><span><i style="background:var(--zone-r16)"></i>1–8 · Round of 16</span>' +
      '<span><i style="background:var(--zone-po)"></i>9–24 · Knockout play-offs</span>' +
      '<span><i style="background:var(--zone-out)"></i>25–36 · Eliminated</span>' +
      (anyTie ? "<span>* Level on all available tiebreakers</span>" : "") + "</div>";
  }

  U.api("/api/standings").then(function (data) {
    if (data.season && data.season !== U.SEASON) data.rows = [];
    render(data);
  }).catch(function (err) {
    document.getElementById("standings").innerHTML = U.errorState(err);
  });
})();
