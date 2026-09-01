# Authentication

Login uses [EVE Online SSO's Authorization Code + PKCE flow](https://developers.eveonline.com/docs/services/sso/#authorization-code-with-pkce):

1. Register an application at [developers.eveonline.com/applications](https://developers.eveonline.com/applications)
   with its callback URL matching `EVE_SSO_CALLBACK_URL` below.
2. Copy `.env.example` to `.env` and fill in:
   - `EVE_SSO_CLIENT_ID`, `EVE_SSO_CALLBACK_URL`, `EVE_SSO_SCOPES` (space-separated, may be empty)
   - `MONGODB_URI`, `MONGODB_DATABASE` — where character/token data is persisted
   - `SESSION_SECRET_KEY` — signs the session cookie; set to a long random value
   - `REDIS_ENABLED`, `REDIS_URL` — optional cache, see [Caching](caching.md)
3. `GET /auth/login` starts the flow, `GET /auth/callback` completes it and sets a signed,
   httponly session cookie. `GET /auth/me` returns the logged-in character's identity;
   `GET /auth/logout` clears the session.

The dashboard and blueprint library need `esi-characters.read_blueprints.v1`,
`esi-assets.read_assets.v1`, `esi-industry.read_character_jobs.v1`, and
`esi-universe.read_structures.v1` (resolves player-structure location names —
without it those fall back to a raw `Location {id}` label) in `EVE_SSO_SCOPES`.
The PI Setups page (`/pi`) additionally needs `esi-planets.manage_planets.v1` —
this is ESI's only PI scope; despite the name it only grants read access to
`/characters/{id}/planets/*`, there's no narrower read-only variant. All five
scopes must also be enabled on the application itself at
developers.eveonline.com, or EVE SSO rejects the login with `invalid_scope`.

Because EVE SSO refresh tokens carry the scope set they were originally issued
with, a character that logged in before `esi-planets.manage_planets.v1` was
added won't have it until they log out (`/auth/logout`) and log back in
(`/auth/login`) for a fresh consent grant. `/pi` detects a missing scope and
shows a message prompting for this instead of failing.

## Corporation data (optional)

A logged-in character can additionally connect their corporation's assets,
blueprints, and industry jobs via `GET /settings` → "Connect corporation data".
This is a **separate, incremental OAuth grant** from the base login above — it
requests only `EVE_SSO_CORP_SCOPES` (also configured in `.env`, and also needing
to be enabled on the application at developers.eveonline.com), so a character's
base login never prompts for corp permissions unless they explicitly opt in.

`GET /auth/connect-corp` starts this second PKCE flow. It completes on the
*same* `GET /auth/callback` route the base login uses — EVE SSO requires the
authorize request's `redirect_uri` to exactly match what's registered on the
application, so rather than registering a second callback URL, `/auth/callback`
tells the two flows apart by which pending session state (`pkce_state` vs
`corp_pkce_state`) the incoming `state` param matches, and completes the corp
connection by storing a second token pair (`corp_access_token`/
`corp_refresh_token`) on the already-logged-in character, rejecting it if it was
completed as a different character than the one who started it.
`GET /auth/disconnect-corp` clears the corp token pair — corp data is opt-in
both ways.

Corp assets and corp blueprints (`esi-assets.read_corporation_assets.v1`,
`esi-corporations.read_blueprints.v1`) require the character to hold the
**Director** role in their corporation; corp industry jobs
(`esi-industry.read_corporation_jobs.v1`) allows Director or Factory_Manager.
ESI enforces this per-call, independent of what scopes were granted, so a
connected character without the right role still gets a 403 from the
corresponding endpoint — the app treats that as "no permission" (shown per-source
on `/settings`) rather than an error, since roles can change over time.

When connected, corp assets/blueprints/jobs are merged into the same totals as
the character's personal data on `/assets`, `/blueprints`, `/jobs/{job_id}`, and
the dashboard (see `app/services/character_data.py`'s `get_merged_*` functions).
