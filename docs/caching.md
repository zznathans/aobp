# Caching

MongoDB is queried on every blueprint list/detail page load for reference data that
rarely changes — `sde_types` (name lookups), `sde_blueprints` (materials/products), and
resolved location names. Set `REDIS_ENABLED=true` (and `REDIS_URL`) to put a Redis
read-through cache in front of those lookups (`app/services/cache.py`), cutting repeat
Mongo reads down to whatever `REDIS_CACHE_TTL_SECONDS` allows (default 24h — this data
only changes when the SDE migrations rerun or a location is looked up for the first
time). It's entirely optional: if `REDIS_ENABLED` is false, or Redis is unreachable, the
app just queries MongoDB directly — there's no hard dependency, and cache errors are
swallowed rather than surfaced as request failures.
