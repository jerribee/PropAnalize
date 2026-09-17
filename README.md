# Property Intelligence — monthly data pipeline

Two independent scripts, run on the same monthly schedule but trusted very differently.

## Track A — `track_a_gis_refresh.py`
Re-queries Rhode Island's statewide GIS layers (parcels, FEMA flood zones, wetland
jurisdiction) for every tracked property and overwrites the stored result automatically.
Safe to fully automate — the source is the state's own authoritative GIS.

**Before running for real:**
- Fill in real `lat`/`lng` for each property in `config.py` (verified via a geocoder,
  not guessed — this pipeline shouldn't do the thing the product itself refuses to do).
- Confirm the parcel layer's index and field names by visiting
  `https://risegis.ri.gov/hosting/rest/services/RIDEM/Tax_Parcels/MapServer?f=pjson`
  and checking the `layers` array — I set `layer_id: 0` as a starting guess, not a
  confirmed value.

## Track B — `track_b_ordinance_watch.py`
Hashes the visible text of each town's zoning code page and flags a change for human
review — it never updates the live dimensional-standards table by itself. A changed
hash means "something on this page changed," not "the setback changed" — that
distinction gets confirmed by a person (or an LLM reading the diff) before it affects
what the product tells anyone.

**Before running for real:**
- Add each town's actual eCode360 or Municode code URL to `config.py` (the two
  placeholder entries are structurally correct but the URLs need swapping for real
  ones — I haven't browsed every town's live page to confirm exact URLs).
- For towns with no Municode/eCode360 presence (a static PDF only), add them with
  `"platform": "pdf"` — the script hashes the PDF's raw bytes instead of rendered text.

## Running locally
```
pip install -r requirements.txt
python3 track_a_gis_refresh.py
python3 track_b_ordinance_watch.py
```
Both write their state to `pipeline_state/` as JSON — swap this for a real database
once there's more than one property or town being tracked; the JSON files are there
so this is runnable and inspectable without standing up infrastructure first.

## Live API — `api/main.py`
A small FastAPI service with one real endpoint: `GET /api/property?address=...`.
Geocodes the address (U.S. Census geocoder, free, no key) and runs the same
point-in-polygon queries as Track A, on demand, for whatever address a visitor
types in — this is what a real dashboard calls instead of reading static state
files.

Run it:
```
pip install -r requirements.txt
uvicorn api.main:app --reload
```
Then open `http://127.0.0.1:8000/docs` for interactive API docs (free from
FastAPI), or call it directly:
```
curl "http://127.0.0.1:8000/api/property?address=2+Dwight+St,+Cranston,+RI+02921"
```

Tested end-to-end with mocked network responses (geocoder + a RIGIS layer hit,
plus the "address didn't geocode" error path) — all three passed. Not yet
tested against the live Census/RIGIS services from this environment, for the
same sandboxing reason as the rest of this pipeline; verify with a real
request before pointing production traffic at it.

Notes before deploying:
- `allow_origins=["*"]` in the CORS setup is fine for local development only —
  lock it to your actual dashboard's domain before this goes live.
- The in-memory cache disappears on every restart and isn't shared across
  serverless instances — fine for a demo, worth moving to Redis or the
  database once there's real traffic.
- This endpoint doesn't yet return the zoning district or dimensional
  standards — only the layers with confirmed, queryable RIGIS endpoints
  (flood, wetlands, parcel). Wiring in the actual Cranston zoning boundary
  layer is the next piece, once its FeatureServer URL is confirmed the same
  way the other three were.

## Running on a schedule
`.github/workflows/monthly-refresh.yml` runs both scripts on the 1st of each month via
GitHub Actions (free for public repos, generous free minutes for private ones) and
commits the updated state back to the repo. No separate server needed for this stage.

## What this pipeline does NOT do
- It does not touch the dashboard/website directly. It updates state files (or,
  eventually, database rows) that the website reads from.
- It does not auto-publish ordinance changes. A human confirms anything Track B flags.
- It has not been run against the live services from this environment — the sandbox
  this was written in can't make outbound calls to risegis.ri.gov, municode.com, or
  ecode360.com. Test it in your own environment before relying on it.
