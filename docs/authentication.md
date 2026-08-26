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
without it those fall back to a raw `Location {id}` label) in `EVE_SSO_SCOPES`
— all four must also be enabled on the application itself at
developers.eveonline.com, or EVE SSO rejects the login with `invalid_scope`.
