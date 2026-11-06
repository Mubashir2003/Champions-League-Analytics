# Club logos

Club crests are loaded at runtime from the `image_url` that PitchAPI returns for each team.
Nothing is bundled here, so no club or UEFA artwork is redistributed with this project.

If a crest URL is missing or fails to load, the frontend draws a neutral shield with the
club's initials (see `fallbackCrestSVG` in `frontend/js/app.js`).

To use your own licensed crest files instead, drop them in this folder and point the
`logo` field at `/assets/logos/<file>` in `backend/services/normalize.py::_team`.
