"""Write the transaction database as one flat table, for training data or analysis later.

    PYTHONPATH=backend:ml:data python -m store.export --db logs/ruko.db --out logs/exports/transactions.parquet

The engine keeps its database in memory by default; run it with `--db logs/ruko.db` to keep a run
that this script can read. Rows hold every input (`f_*`), the family scores (`family_*`) and `p_scam`,
so the output stays on the analyst / ML side and is never shown to users (rule 4).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from store.db import TxnStore


def export(db: str | Path, out: str | Path) -> int:
    rows = TxnStore(db).rows_for_export()
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    if out.suffix == ".csv":
        df.to_csv(out, index=False)
    else:
        df.to_parquet(out, index=False)
    return len(df)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--db", required=True, help="the database file the engine wrote with --db")
    p.add_argument("--out", default="logs/exports/transactions.parquet")
    a = p.parse_args()
    print(f"wrote {export(a.db, a.out)} rows to {a.out}")


if __name__ == "__main__":
    main()
