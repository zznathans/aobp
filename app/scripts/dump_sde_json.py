"""Dump every table in a CCP Static Data Export SQLite file
(e.g. https://www.fuzzwork.co.uk/dump/latest-sqlite.db.gz) to gzip-compressed
JSON files, one per table, for committing to the repo.

Usage:
    python -m app.scripts.dump_sde_json /path/to/sde.sqlite
"""

import argparse
import base64
import gzip
import json
import sqlite3
from pathlib import Path
from typing import Any

_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "sde"


def _row_to_json_safe(row: sqlite3.Row) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in row.keys():  # noqa: SIM118 (sqlite3.Row, not a dict)
        value = row[key]
        if isinstance(value, bytes):
            value = base64.b64encode(value).decode("ascii")
        result[key] = value
    return result


def list_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")
    return [row[0] for row in rows]


def dump_table(conn: sqlite3.Connection, table_name: str, output_dir: Path) -> int:
    rows = [_row_to_json_safe(row) for row in conn.execute(f"SELECT * FROM {table_name}")]
    output_path = output_dir / f"{table_name}.json.gz"
    with gzip.open(output_path, "wt", encoding="utf-8") as fh:
        json.dump(rows, fh)
    return len(rows)


def dump_sde(sqlite_path: str, output_dir: Path = _OUTPUT_DIR) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        tables = list_tables(conn)
        for table_name in tables:
            count = dump_table(conn, table_name, output_dir)
            print(f"{table_name}: {count} rows")
    finally:
        conn.close()

    print(f"Dumped {len(tables)} tables to {output_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sqlite_path", help="Path to the SDE SQLite dump")
    args = parser.parse_args()
    dump_sde(args.sqlite_path)


if __name__ == "__main__":
    main()
