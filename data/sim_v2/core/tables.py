"""Row buffers for the output tables, in the data/sim schema (plus sim_v2's own extra columns).

Rows are kept as Python tuples while a batch of users is simulated, then packed into Arrow tables,
so memory stays small at 20,000 users x 60 days.
"""
from __future__ import annotations

import json

import pyarrow as pa

TS = pa.timestamp("us", tz="+05:30")

# Same columns and order as data/sim (the contract the backend and ml/ read); sim_v2 extras last.
SCHEMAS = {
    "ledger": pa.schema([("ts", TS), ("from_upi", pa.string()), ("to_upi", pa.string()), ("amount", pa.float64()),
                         ("entry_method", pa.string()), ("flow", pa.string()), ("journey_id", pa.string()),
                         ("label_is_scam", pa.bool_()), ("label_stage", pa.string()),
                         ("scenario", pa.string()), ("cause_id", pa.string())]),
    "context_events": pa.schema([("ts", TS), ("user_id", pa.string()), ("event_type", pa.string()),
                                 ("attrs", pa.string()), ("journey_id", pa.string()), ("label_is_scam", pa.bool_()),
                                 ("label_stage", pa.string()), ("scenario", pa.string()), ("cause_id", pa.string())]),
    "decisions": pa.schema([("decision_id", pa.string()), ("ts", TS), ("agent", pa.string()), ("kind", pa.string()),
                            ("journey_id", pa.string()), ("step", pa.string()), ("step_no", pa.int32()), ("inputs", pa.string()),
                            ("p", pa.float64()), ("draw", pa.float64()), ("outcome", pa.string())]),
}


class Buffer:
    def __init__(self, name: str):
        self.name, self.schema = name, SCHEMAS[name]
        self.rows: list[tuple] = []
        self.parts: list[pa.Table] = []

    def add(self, *row) -> None:
        self.rows.append(row)

    def pack(self) -> None:
        if self.rows:
            cols = list(zip(*self.rows))
            self.parts.append(pa.table([pa.array(c, type=f.type) for c, f in zip(cols, self.schema)],
                                       schema=self.schema))
            self.rows = []

    def table(self) -> pa.Table:
        self.pack()
        return pa.concat_tables(self.parts) if self.parts else self.schema.empty_table()


def attrs(d: dict) -> str:
    """Same JSON form as data/sim (sorted keys, default separators): ml/ and eval/ string-match it."""
    return json.dumps(d, sort_keys=True)
