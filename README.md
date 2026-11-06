# ⚽ UCL Analytics 🏆

A fan dashboard for the **UEFA Champions League 2026/2027** season: fixtures, results, a live-calculated league-phase table, match intelligence with Key Players, and compact Elo + Poisson win/draw/loss estimates.
- **Visit the Live Link here 🔗:** https://champions-league-analytics.onrender.com/

- **Frontend:** HTML5, CSS3, vanilla JavaScript (no frameworks)
- **Backend:** Python + FastAPI, REST endpoints, local JSON caching (no database)
- **Data:** PitchAPI (primary) and StrikerAPI (completed-result verification)
- **Model:** reproducible Elo + Poisson, written in Python

Only 2026/2027 data is ever requested, stored or shown. If the providers have no current-season data, the pages show a friendly empty state — there is no fallback to older seasons and no invented data.

---

## 1. Requirements 📝

- Python **3.10 or newer** (3.11+ recommended)
- A PitchAPI key — https://pitchapi.dev/
- A StrikerAPI key — https://strikerapi.com/docs (free accounts get 500 credits a month)
- Internet access from the machine running the backend

## 2. Project structure 📁

```text
ucl-analytics/
├── frontend/                 Static site served by FastAPI
│   ├── index.html            Overview
│   ├── fixtures.html         Upcoming / completed fixtures
│   ├── match-details.html    Match intelligence + Key Players
│   ├── standings.html        League-phase table
│   ├── css/style.css, responsive.css
│   ├── js/app.js             Theme, API helper, crests, fixture cards, prediction bar
│   ├── js/overview.js, fixtures.js, match-details.js, standings.js
│   └── assets/images, assets/logos
├── backend/
│   ├── main.py               FastAPI app (API + frontend on one server)
│   ├── config.py             Settings from environment / .env
│   ├── api/routes.py         REST endpoints
│   ├── services/
│   │   ├── providers.py      PitchAPI + StrikerAPI HTTP clients
│   │   ├── normalize.py      Provider → internal match shape, reconciliation
│   │   ├── match_service.py  Fixtures, results refresh, predictions
│   │   ├── player_service.py Match stats, manager/formation, Key Players
│   │   └── standings_service.py  League-phase table + UEFA tiebreakers
│   ├── predictions/
│   │   ├── elo_poisson.py    The model
│   │   ├── store.py          Frozen pre-match predictions (data/predictions.json)
│   │   └── evaluation.py     Brier score, log loss, calibration
│   └── utils/                cache, timezones (zoneinfo), team-name matching, clock
├── data/
│   ├── cache/                Provider response cache (safe to delete)
│   ├── team_timezones.json   Home-club timezones for venue-local kickoff times
│   └── predictions.json      Created at runtime; keep it to evaluate the model later
├── tests/                    pytest suite with mocked provider responses
├── requirements.txt
├── .env.example
└── README.md
```

## 3. Setup (Windows PowerShell) ⚙️

```powershell
cd ucl-analytics
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
notepad .env        # paste your two API keys
uvicorn backend.main:app --reload
```

If PowerShell refuses to run the activate script, run this once and try again:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

macOS / Linux:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then add your keys
uvicorn backend.main:app --reload
```

Always start uvicorn from the **project root** (the folder containing `backend/`).

- Dashboard: http://127.0.0.1:8000
- API docs (Swagger): http://127.0.0.1:8000/docs

## 4. API key configuration 🔑

`.env` (never commit it — it is in `.gitignore`):

```env
PITCHAPI_API_KEY=pk_live_...
STRIKERAPI_API_KEY=...
PITCHAPI_BASE_URL=https://api.pitchapi.dev
STRIKERAPI_BASE_URL=https://mcp.strikerapi.com/v1
```

Keys are read only by the backend. The browser talks exclusively to this server's `/api/*` routes, and no endpoint returns a key.

## 5. Endpoints 🌐

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Server status and whether each provider is configured |
| GET | `/api/matches?status=upcoming\|completed\|all&limit=N` | 2026/27 fixtures and results (completed are newest first) |
| GET | `/api/matches/{match_key}` | Match intelligence: teams, stats, manager, formation, Key Players |
| GET | `/api/standings` | League-phase table |
| GET | `/api/providers` | Provider configuration, last errors, StrikerAPI credits remaining |
| GET | `/api/model/evaluation` | Brier score, log loss, accuracy and calibration of frozen predictions |
| POST | `/api/refresh` | Re-fetch fixtures from PitchAPI now (bypasses the 15-minute cache) |
| POST | `/api/refresh/results` | Ask StrikerAPI for final scores now (see credit rules below) |

Status codes: `200` success, `404` unknown match, `422` bad query, `502` provider failure, `503` provider not configured.

## 6. Refreshing fixtures and updating results 🔄

**Fixtures** are cached for 15 minutes and refreshed automatically on the next page load. To force it:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/refresh
```

**Results.** PitchAPI is a post-match source; when it already carries a score, that score is used. StrikerAPI is asked for **final** results (`list_games`, `league=ucl`, `season=2026`, `status=final`) only when:

1. a match kicked off more than 150 minutes ago and has no StrikerAPI-confirmed result yet, **and**
2. at least 60 minutes have passed since the last StrikerAPI call (a manual refresh still waits at least 5 minutes).

Each check asks only for the date range that still needs results, so a normal check costs **2 credits**. Standings are fetched at most every 3 hours (2 credits). StrikerAPI does not provide live scores and the dashboard never presents it as such.

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/refresh/results
```

## 7. How the data is put together 🧩

**PitchAPI** (verified against the official `pitchapi` SDK, which mirrors the service's OpenAPI spec): `GET /v1/leagues` to find the Champions League, `GET /v1/leagues/{id}/matches?season=2026/2027&status=all` for fixtures, then per completed match `/v1/matches/{id}`, `/players`, `/advanced/players`, `/shots`, `/lineups`, `/stats`. Auth header `X-API-KEY`.

**StrikerAPI** (verified against https://strikerapi.com/docs and the `strikerapi` SDK): `POST /v1/list_games` and `POST /v1/get_standings` with header `x-api-key`.

**Reconciliation.** The two providers use different match ids, so matches are paired on normalised club identity (accents, "FC", aliases like PSG / Paris Saint-Germain, Bayern München / Munich) **and** kickoff date (±1 day), with home and away sides both required to match.

**Kickoff times** are converted with Python `zoneinfo` into the home club's local time (from `data/team_timezones.json`) and Pakistan Standard Time. Clubs missing from that file show PKT only; add an entry to get local time.

**Key Players.** For each team the backend looks at its most recent completed 2026/27 matches, collects every player who actually played, keeps each player's last three appearances, and ranks them on goals, assists, xG, key passes, shots, dribbles, tackles, recoveries and minutes. The top five are shown. Appearances are labelled *Appearance 1–3* with opponent and result — no dates. Stats come from: shots feed (xG, shots), advanced feed (minutes, assists, key passes, successful dribbles = take-ons won, tackles), and the player stat lines (goals, recoveries). A stat the provider does not return is simply not displayed.

**Manager and formation** come from the confirmed lineup of the team's latest completed fixture.

**Standings.** StrikerAPI's league-phase table is used when it passes integrity checks (P = W+D+L, GD = GF−GA, single league-phase group, at most 36 clubs) and is at least as current as our verified results. Otherwise the table is **calculated** from completed league-phase matches with the UEFA ranking order: points, goal difference, goals scored, away goals scored, wins, away wins, opponents' points, opponents' goal difference, opponents' goals scored. The page always says how many of the 144 league-phase matches are included.

## 8. Prediction model 📊

`backend/predictions/elo_poisson.py`:

1. Every club starts the season at Elo 1500. Ratings update after each completed 2026/27 match (K = 24, home advantage 50 points, goal-difference multiplier).
2. The rating gap scales the competition's average home/away goals (priors of 1.55 / 1.25 until 20 matches exist) into λ_home and λ_away.
3. Independent Poisson distributions (0–10 goals) give home/draw/away probabilities, converted to whole percentages that always total 100.

A prediction is stored in `data/predictions.json` while the match is upcoming. At kickoff it is **frozen** and never recomputed; the final score is attached next to it. `/api/model/evaluation` reports Brier score, log loss, accuracy and calibration bins. Fixture cards label the bar as a model estimate, and the match page labels a finished match's bar as the pre-match estimate, so it is never confused with the result.

## 9. Tests 🧪

```powershell
python -m pytest -q
```

The suite (43 tests) uses mocked HTTP responses shaped like the official SDK models, so it needs no keys or network. It covers: season filtering and rejection of other seasons, de-duplication, StrikerAPI reconciliation and credit rate-limiting, out-of-credits handling, predictions totalling 100 and freezing at kickoff, zoneinfo DST handling, Key Players (5 per team, ≤3 appearances, no dates), standings calculation and tiebreakers, provider-table validation, empty states, 502/503/404/422 handling, no keys in API responses or frontend files, forbidden UI text, navigation, theme persistence wiring and JavaScript syntax (`node --check`, skipped if Node.js is not installed).

## 10. Troubleshooting 🛠️

| Symptom | Cause / fix |
|---|---|
| Pages say "Match data is on its way" | `GET /api/health` → if `pitchapi: false`, the key is missing from `.env`. Restart uvicorn after editing `.env`. |
| `/api/matches` returns 502 | PitchAPI rejected or failed the call. Check `GET /api/providers` → `pitchapi.last_error`. A 401 means a wrong key; 429 means slow down (the client already honours `Retry-After`). |
| Fixtures list is empty but no error | PitchAPI does not (yet) list a 2026/2027 season for the Champions League. Older seasons are deliberately not used. If auto-discovery picks the wrong league, set `PITCHAPI_UCL_LEAGUE_ID` in `.env`. |
| A played match shows "Result to follow" | Neither provider has a final score yet. StrikerAPI is checked 150 min after kickoff, at most hourly. |
| `/api/refresh/results` returns 502 "out of StrikerAPI credits" | HTTP 402 from StrikerAPI. Top up or wait for the monthly reset; fixtures and PitchAPI scores keep working. |
| Results never get verified by StrikerAPI | StrikerAPI's docs do not publish the field names inside a `list_games` game. Call `POST https://mcp.strikerapi.com/v1/list_games` once yourself and, if names differ, add them to `STRIKER_GAME_FIELDS` in `backend/services/normalize.py`. |
| `ModuleNotFoundError: backend` | Run uvicorn from the project root, not from inside `backend/`. |
| `ZoneInfoNotFoundError` on Windows | `pip install tzdata` (it is in `requirements.txt`). |
| Old data after fixing something | Delete the contents of `data/cache/` (keep `predictions.json`). |

## 11. Known limitations ⚠️

- **Player positions.** PitchAPI returns a numeric `position_id` without a published label mapping, so positions are only shown where they are certain (goalkeepers, identified from goalkeeping data).
- **Final two UEFA tiebreakers** (disciplinary points, club coefficient) are not provided by either source. Clubs still level after the other criteria are marked with `*`.
- **League-phase detection** uses PitchAPI's round name when available and otherwise the September 2026 – January 2027 date window.
- **Early-season predictions** are less differentiated because only 2026/27 results are used to rate clubs (by design, no previous-season data).
- **Club crests** come from the URLs PitchAPI provides; when missing or broken, a neutral initials shield is drawn. No UEFA artwork is bundled; the star motif is original.
- **Fonts** load from Google Fonts; offline, the system fonts are used.

## 12. Licensed By 📄

<p align="left">Mubashir Hussain <span style="float: right;">All Rights Reserved</span></p>

