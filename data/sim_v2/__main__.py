"""Commands (run from the repo root with PYTHONPATH=backend;ml;data):

    python -m sim_v2 build [--users 500] [--days 14] [--seed 7] [--world train|eval] [--out DIR]
    python -m sim_v2 summary   [--data DIR]          what is in a world
    python -m sim_v2 csv       [--data DIR] [--all]  CSV copies to open in Excel (DIR/csv/)
    python -m sim_v2 show USER_ID [--data DIR]       one person's payments and phone events in time order
    python -m sim_v2 trace JOURNEY_ID [--data DIR]   one scam as a story: decisions and the rows they caused
    python -m sim_v2 playbooks                       the scam state machines and their steps
    python -m sim_v2 scenarios                       look-alikes (hard negatives) and scripted demo actors
    python -m sim_v2 assumptions [--guesses]         every number in assumptions.yaml with source
    python -m sim_v2 validate  [--data DIR]          schema vs data/sim, labels, determinism, subset stability
    python -m sim_v2 report    [--data DIR]          report.html + report.docx: charts and explanations
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

DEFAULT_OUT = Path("data/sim_v2_out/small")
pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 20)
pd.set_option("display.max_colwidth", 60)


def _load(d: Path, *names):
    if not (d / "manifest.json").exists():
        sys.exit(f"No world in {d}. Build one first: python -m sim_v2 build --out {d}")
    return [pd.read_parquet(d / f"{n}.parquet") for n in names]


def cmd_build(a):
    from sim_v2.core.config import load
    from sim_v2.export import write
    from sim_v2.run import build
    cfg = load(users=a.users, days=a.days, seed=a.seed, world=a.world,
               exclude_emerging=True if a.exclude_emerging else None)
    print(f"building {cfg.world} world: {cfg.users:,} users x {cfg.days} days, seed {cfg.seed} -> {a.out}")
    write(build(cfg), cfg, a.out)
    a.data, a.all = a.out, False
    # Every build leaves its results next to the data, so they can be checked without re-running:
    #   summary.txt (what is in the world), csv/ (open in Excel), validate.txt (checks)
    import contextlib, io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cmd_summary(a)
    (a.out / "summary.txt").write_text(buf.getvalue(), encoding="utf-8")
    print(buf.getvalue())
    cmd_csv(a)
    if not a.no_validate:
        from sim_v2 import validate
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            validate.run(a.out)
        (a.out / "validate.txt").write_text(buf.getvalue(), encoding="utf-8")
        print(buf.getvalue().strip().splitlines()[-1])
    files = "summary.txt, validate.txt, csv/*.csv"
    if not a.no_report:
        from sim_v2 import report
        report.run(a.out)
        files += ", report.html, report.docx"
    print(f"\nresults saved in {a.out}: {files}")


def cmd_summary(a):
    led, ev, jr, acc, dec, rep = _load(a.data, "ledger", "context_events", "journeys", "accounts", "decisions", "reports")
    man = json.loads((a.data / "manifest.json").read_text())
    print(f"\n== {a.data}  ({man['config'].get('world')} world, {man['config'].get('users')} users x "
          f"{man['config'].get('days')} days, seed {man['config'].get('seed')}, config {man['config_fingerprint']})")
    print("\nrows:", ", ".join(f"{k} {v:,}" for k, v in man["rows"].items()))
    print("\npayments by flow (scenario = look-alike / routine tag):")
    t = led.assign(scenario=led.scenario.fillna(led.flow.map(lambda f: "everyday" if f == "normal" else ""))).groupby(["flow", "scenario"]).agg(
        n=("amount", "size"), median_inr=("amount", "median"), typed=("entry_method", lambda s: round((s == "typed").mean(), 2)))
    print(t.to_string())
    print("\nphone events:", ev.event_type.value_counts().to_dict())
    if len(jr):
        print("\njourneys:")
        print(jr.assign(paid=jr.n_payments > 0).groupby("playbook").agg(
            journeys=("journey_id", "size"), paid_any=("paid", "sum"), payments=("n_payments", "sum"),
            total_inr=("total_paid", "sum"), reported=("reported", "sum")).to_string())
        print("\noutcomes:", jr.outcome.value_counts().to_dict())
    print("\nmules by kind:", acc[acc.is_mule].mule_kind.value_counts().to_dict())
    print(f"mule share of accounts: {acc.is_mule.mean():.2%} ({int(acc.is_mule.sum()):,} of {len(acc):,})")
    users = pd.read_parquet(a.data / "users.parquet")
    real = jr[~jr.is_demo]
    print(f"users approached by a scam: {real.user_id.nunique() / len(users):.2%}   "
          f"users who lost money: {real[real.n_payments > 0].user_id.nunique() / len(users):.2%}")
    u_pay = led[led.from_upi.isin(set(users.upi_id))]
    print(f"\nscam share of user payments: {u_pay.label_is_scam.mean():.4%} "
          f"({int(u_pay.label_is_scam.sum())} of {len(u_pay):,})")
    listed = rep[~rep.is_false & (rep.identifier_type == "upi_id")]
    scam = led[led.flow == "scam"]
    if len(scam):
        first_listed = listed.groupby("identifier").listed_at.min()
        known = scam.to_upi.map(first_listed)
        print(f"scam payments to a payee already listed at payment time: {(known < scam.ts).mean():.0%}")
    print(f"decisions logged: {len(dec):,}   reports: {rep.report_id.nunique():,} ({int(rep.is_false.sum())} false rows)")


def cmd_csv(a):
    names = ["users", "accounts", "ledger", "context_events", "journeys", "reports", "decisions", "crews"]
    out = a.data / "csv"
    out.mkdir(exist_ok=True)
    for n in names:
        (df,) = _load(a.data, n)
        if not a.all and len(df) > 1000:
            keep = df.head(1000)
            if "journey_id" in df:   # always keep every scam-linked and look-alike row
                extra = df[df.journey_id.notna()]
                if "scenario" in df:
                    extra = pd.concat([extra, df[df.scenario.notna() & ~df.scenario.isin(["rent", "bill"])]])
                keep = pd.concat([keep, extra]).drop_duplicates()
            df = keep
        df.to_csv(out / f"{n}.csv", index=False)
        print(f"  {out / (n + '.csv')}  ({len(df):,} rows)")
    print("(sample: first 1,000 rows + every scam and look-alike row; --all for everything)" if not a.all else "")


def cmd_show(a):
    led, ev, users = _load(a.data, "ledger", "context_events", "users")
    u = users[users.user_id == a.id]
    if u.empty:
        sys.exit(f"no user {a.id}")
    u = u.iloc[0]
    print(u.to_string(), "\n")
    p = led[(led.from_upi == u.upi_id) | (led.to_upi == u.upi_id)].assign(kind="payment")
    p["what"] = p.apply(lambda x: f"{'PAY ' if x.from_upi == u.upi_id else 'GET '}₹{x.amount:,.0f} "
                        f"{'to ' + x.to_upi if x.from_upi == u.upi_id else 'from ' + x.from_upi} [{x.entry_method}, {x.flow}"
                        f"{', ' + x.scenario if isinstance(x.scenario, str) else ''}]", axis=1)
    e = ev[(ev.user_id == a.id) & (ev.event_type != "pay_session")].assign(kind="event")
    e["what"] = [f"{t} {at}" for t, at in zip(e.event_type, e["attrs"])]
    rows = pd.concat([p[["ts", "what", "journey_id"]], e[["ts", "what", "journey_id"]]]).sort_values("ts")
    for _, x in rows.head(a.limit).iterrows():
        print(f"{x.ts:%m-%d %H:%M}  {x.what}" + (f"   <- {x.journey_id}" if isinstance(x.journey_id, str) else ""))
    if len(rows) > a.limit:
        print(f"... {len(rows) - a.limit} more rows (--limit)")


def cmd_trace(a):
    led, ev, jr, dec = _load(a.data, "ledger", "context_events", "journeys", "decisions")
    j = jr[jr.journey_id == a.id]
    if j.empty:
        sys.exit(f"no journey {a.id}. Some: {', '.join(jr.journey_id.head(10))}")
    j = j.iloc[0]
    print(f"{j.journey_id}: {j.playbook}{' (' + j.variant + ')' if isinstance(j.variant, str) else ''}, victim {j.user_id}, "
          f"crew {j.crew_id}, started {j.started_at:%Y-%m-%d %H:%M}\noutcome: {j.outcome}, paid ₹{j.total_paid:,.0f} in "
          f"{j.n_payments} payments, reported: {j.reported}, mules: {j.mule_upi_ids or '-'}\n")
    d = dec[dec.journey_id == a.id].assign(src="DECISION")
    from sim_v2.core.config import load
    n_steps = len(load().playbooks.get(j.playbook, {"steps": []})["steps"])
    at = lambda x: f"step {int(x.step_no)}/{n_steps} {x.step}" if pd.notna(x.step_no) else str(x.step)
    d["what"] = d.apply(lambda x: f"{x.kind} @ {at(x)}: p={x.p:.2f} draw={x.draw:.2f} -> {x.outcome.upper()}   inputs {x.inputs}"
                        if pd.notna(x.draw) else f"{x.kind} @ {at(x)}: scripted -> {x.outcome.upper()}", axis=1)
    p = led[led.journey_id == a.id].assign(src="PAYMENT")
    p["what"] = p.apply(lambda x: f"₹{x.amount:,.0f} {x.from_upi} -> {x.to_upi} [{x.entry_method}, {x.flow}, {x.label_stage}]"
                        + (f"  caused by {x.cause_id}" if isinstance(x.cause_id, str) else ""), axis=1)
    e = ev[(ev.journey_id == a.id) & (ev.event_type != "pay_session")].assign(src="EVENT")
    e["what"] = [f"{t} [{st if isinstance(st, str) else ''}] {at}" for t, st, at in zip(e.event_type, e.label_stage, e["attrs"])]
    for _, x in pd.concat([d[["ts", "src", "what"]], p[["ts", "src", "what"]], e[["ts", "src", "what"]]]).sort_values(["ts", "src"]).iterrows():
        print(f"{x.ts:%m-%d %H:%M}  {x.src:<8}  {x.what}")


def cmd_playbooks(a):
    from sim_v2.core.config import load
    for name, pb in load().playbooks.items():
        print(f"\n{name}  (weight {pb['weight']}, confidence {pb['confidence']}{', EMERGING' if pb.get('emerging') else ''})\n  {pb['title']}")
        for i, s in enumerate(pb["steps"], start=1):
            parts = [k for k in ("events", "crew_pays", "ask", "decide") if k in s]
            extra = f" p={s['p']}" if "p" in s else ""
            extra += f" when={s['when']}" if "when" in s else ""
            print(f"   {i}. {s['id']:<20} {', '.join(parts)}{extra}")


def cmd_scenarios(a):
    from sim_v2.core.config import load
    cfg = load()
    print("look-alikes (hard negatives, flow 'normal'):")
    for name, s in cfg.lookalikes.items():
        print(f"  - {name:<22} rate {s['rate']} per user per 30 days\n      {s['why']}")
    print("\nscripted demo actors (exact on purpose):")
    for k, v in cfg.demo.items():
        print(f"  - {k}: {v}")


def cmd_assumptions(a):
    from sim_v2.core.config import load
    cfg = load()
    rows = [{"key": f"{sec}.{k}", "conf": e.get("conf"), "value": json.dumps(e["v"])[:60], "range": e.get("range"),
             "source": e.get("src")} for sec, items in cfg.a_meta.items() for k, e in items.items()]
    df = pd.DataFrame(rows)
    if a.guesses:
        df = df[df.conf == "guess"]
    print(df.to_string(index=False))
    print(f"\n{(df.conf == 'guess').sum()} of {len(df)} shown are guesses. Playbooks: "
          + ", ".join(f"{n}={pb['confidence']}" for n, pb in cfg.playbooks.items()))


def cmd_report(a):
    from sim_v2 import report
    if not (a.data / "manifest.json").exists():
        sys.exit(f"No world in {a.data}. Build one first.")
    report.run(a.data)


def cmd_validate(a):
    from sim_v2 import validate
    ok = validate.run(a.data)
    sys.exit(0 if ok else 1)


def main():
    ap = argparse.ArgumentParser(prog="python -m sim_v2", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--users", type=int)
    b.add_argument("--days", type=int)
    b.add_argument("--seed", type=int)
    b.add_argument("--world", choices=["train", "eval"])
    b.add_argument("--out", type=Path, default=DEFAULT_OUT)
    b.add_argument("--no-validate", action="store_true", help="skip the checks (they take about 20 s)")
    b.add_argument("--no-report", action="store_true", help="skip report.html / report.docx")
    b.add_argument("--exclude-emerging", action="store_true", help="leave out playbooks marked emerging")
    for name in ("summary", "csv", "validate", "report"):
        p = sub.add_parser(name)
        p.add_argument("--data", type=Path, default=DEFAULT_OUT)
        if name == "csv":
            p.add_argument("--all", action="store_true")
    for name in ("show", "trace"):
        p = sub.add_parser(name)
        p.add_argument("id")
        p.add_argument("--data", type=Path, default=DEFAULT_OUT)
        p.add_argument("--limit", type=int, default=80)
    sub.add_parser("playbooks")
    sub.add_parser("scenarios")
    s = sub.add_parser("assumptions")
    s.add_argument("--guesses", action="store_true")
    a = ap.parse_args()
    globals()[f"cmd_{a.cmd}"](a)


if __name__ == "__main__":
    main()
