# Blueprint data

ESI doesn't expose blueprint manufacturing data (materials/products/time) — only CCP's
Static Data Export (SDE) has it. A gzip-compressed JSON dump of every SDE table ships in
the repo at `app/data/sde/` (one `<table>.json.gz` per table, generated from
[Fuzzwork's SDE SQLite export](https://www.fuzzwork.co.uk/dump/latest-sqlite.db.gz)), so
no manual download or import step is needed.

On startup, `app/migrations/` imports it into MongoDB automatically:
- `0001_import_raw_sde_tables` loads every `app/data/sde/*.json.gz` file verbatim into a
  same-named Mongo collection (e.g. `invTypes`, `industryActivityMaterials`).
- `0002_build_sde_lookup_collections` builds `sde_types` (type_id → name) and
  `sde_blueprints` (blueprint type_id → manufacturing materials/products/time) from those
  raw collections — this is what `app/routes/blueprints.py` actually queries.

Applied migrations are tracked in a `_migrations` collection, so this only runs once —
later startups skip straight past it. First startup against an empty database takes a
while (millions of rows); subsequent ones are instant.

To refresh the SDE data (e.g. after a new EVE expansion), regenerate the dumps and
commit the result:

```bash
curl -L https://www.fuzzwork.co.uk/dump/latest-sqlite.db.gz | gunzip > sde.sqlite
python -m app.scripts.dump_sde_json sde.sqlite
```
