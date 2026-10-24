"""Red team dashboard: generate playbooks, run them against RUKO, see what got through.

    streamlit run red_team_blue_team/red_team/ui.py        (from the repo root)

Nothing is decided here: the UI starts the same two command-line tools you would run by hand
(`python -m red_team` to generate, `python -m interface_script` to evaluate) and shows their
output as it arrives. Every number on screen comes from the evaluator's own CSV.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
RED = ROOT / "red_team_blue_team" / "red_team"
GENERATED = RED / "playbook_v2"
CURATED = RED / "playbooks"
RESULTS = ROOT / "synthetic_playbook" / "interface_script_out"

# The evaluator needs the repo's packages; it is started from the repo root.
ENV = {**os.environ, "PYTHONPATH": "backend;ml;data;synthetic_playbook",
       "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
PROGRESS = re.compile(r"^PROGRESS (\d+) (\d+) (\d+)$")          # sent, total, scam judged
PLAYBOOK_OF = re.compile(r"^=== \[(\d+)/(\d+)\] (.+)$")          # run-all: which playbook started
CREATED = re.compile(r"^Created (.+)$")

st.set_page_config(page_title="RUKO red team", layout="wide", page_icon="🔴")


# ---------------------------------------------------------------- running tools

def stream_tool(cmd: list[str], on_line) -> int:
    """Run a command from the repo root, handing each output line to `on_line`. Returns the exit code."""
    proc = subprocess.Popen(cmd, cwd=ROOT, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", bufsize=1)
    st.session_state["proc"] = proc
    try:
        for line in proc.stdout:
            if st.session_state.get("stop"):
                proc.terminate()
                on_line("stopped by you")
                break
            on_line(line.rstrip())
    finally:
        proc.wait()
        st.session_state.pop("proc", None)
        st.session_state.pop("stop", None)
    return proc.returncode


def run_generator(count: int, log_box) -> list[str]:
    made: list[str] = []
    bar = st.progress(0.0, text="starting the generator…")
    lines: list[str] = []

    def on_line(line: str) -> None:
        lines.append(line)
        m = CREATED.match(line)
        if m:
            made.append(m.group(1))
            bar.progress(min(len(made) / count, 1.0), text=f"{len(made)} of {count} playbooks written")
        log_box.code("\n".join(lines[-14:]) or "…")

    code = stream_tool([sys.executable, "-m", "red_team", f"--target-count={count}"], on_line)
    bar.progress(1.0, text=f"{len(made)} playbooks written")
    if code != 0 and not made:
        st.error("The generator stopped with an error. The last lines are above.")
    return made


def run_evaluation(folder: Path, victims: int, users: int, days: int, honest: int,
                   normal_max: int, share: float, out: Path, log_box) -> Path | None:
    """Evaluate every playbook in `folder`. Shows one bar for the whole set and one for the
    playbook running now, both driven by the evaluator's own PROGRESS lines."""
    n_books = len(sorted({*folder.glob("*.yaml"), *folder.glob("*.yml")}))
    if not n_books:
        st.error(f"No playbooks in {folder}.")
        return None
    overall = st.progress(0.0, text=f"0 of {n_books} playbooks")
    current = st.progress(0.0, text="…")
    status = st.empty()
    lines: list[str] = []
    state = {"i": 0, "name": "", "t0": time.time()}

    def on_line(line: str) -> None:
        m = PLAYBOOK_OF.match(line)
        if m:
            state["i"], state["name"] = int(m.group(1)), m.group(3)
            overall.progress((state["i"] - 1) / n_books, text=f"{state['i'] - 1} of {n_books} playbooks done")
            current.progress(0.0, text=f"{state['name']}: building the world…")
            return
        p = PROGRESS.match(line)
        if p:
            sent, total, judged = (int(x) for x in p.groups())
            frac = sent / total if total else 1.0
            el = time.time() - state["t0"]
            left = el / max(frac, 1e-9) - el if state["i"] <= 1 else None
            eta = f", about {left / 60:.0f} min left for this one" if left and frac > 0.05 else ""
            current.progress(min(frac, 1.0),
                             text=f"{state['name']}: {sent:,}/{total:,} payments sent, {judged} scam judged{eta}")
            return
        lines.append(line)
        log_box.code("\n".join(lines[-14:]) or "…")
        if line.strip().startswith(("BREAKTHROUGH", "No breakthrough")):
            status.info(f"{state['name']}: {line.strip()}")

    cmd = [sys.executable, "-m", "interface_script", "run-all", f"--playbooks={folder}",
           f"--victims={victims}", f"--users={users}", f"--days={days}", f"--honest-users={honest}",
           f"--normal-max-score={normal_max}", f"--breakthrough-share={share}",
           "--server=local", f"--out={out}"]
    code = stream_tool(cmd, on_line)
    overall.progress(1.0, text=f"{n_books} of {n_books} playbooks done")
    csv = out / "all_playbooks.csv"
    if not csv.exists():
        st.error(f"The evaluator finished with code {code} but wrote no results. The last lines are above.")
        return None
    return csv


# ---------------------------------------------------------------- charts

def results_charts(df: pd.DataFrame) -> None:
    d = df.copy()
    d["miss_pct"] = d.miss_rate * 100
    d["false_alarm_pct"] = d.false_alarm_rate * 100
    d["result"] = d.breakthrough.map({True: "got through", False: "caught"})

    a, b, c, e = st.columns(4)
    a.metric("Playbooks run", len(d))
    b.metric("Got through", int(d.breakthrough.sum()))
    c.metric("Scam payments called normal", f"{d.scam_called_normal.sum():,} of {d.scam_payments_judged.sum():,}")
    e.metric("False alarms on honest payments", f"{d.false_alarm_rate.mean():.2%}")

    st.subheader("How much of each playbook the server called normal")
    st.caption(f"The red line is the breakthrough bar ({d.breakthrough_share.iloc[0]:.0%}). "
               "A bar past it means the server treated most of that playbook as ordinary payments.")
    order = d.sort_values("miss_pct", ascending=False).playbook.tolist()
    bars = alt.Chart(d).mark_bar().encode(
        x=alt.X("miss_pct:Q", title="scam payments called normal (%)", scale=alt.Scale(domain=[0, 100])),
        y=alt.Y("playbook:N", sort=order, title=None),
        color=alt.Color("result:N", scale=alt.Scale(domain=["got through", "caught"],
                                                    range=["#d62728", "#2ca02c"]), title=None),
        tooltip=["playbook", "scam_payments_judged", "scam_called_normal",
                 alt.Tooltip("miss_pct:Q", format=".0f", title="called normal %"),
                 alt.Tooltip("false_alarm_pct:Q", format=".2f", title="false alarms %")])
    rule = alt.Chart(pd.DataFrame({"x": [d.breakthrough_share.iloc[0] * 100]})).mark_rule(
        color="red", strokeDash=[6, 4]).encode(x="x:Q")
    st.altair_chart(bars + rule, use_container_width=True)

    left, right = st.columns(2)
    with left:
        st.subheader("Evidence behind each number")
        st.caption("Few scam payments judged means the result is noisy, whatever the percentage says.")
        st.altair_chart(alt.Chart(d).mark_circle(size=120).encode(
            x=alt.X("scam_payments_judged:Q", title="scam payments judged"),
            y=alt.Y("miss_pct:Q", title="called normal (%)"),
            color=alt.Color("result:N", scale=alt.Scale(domain=["got through", "caught"],
                                                        range=["#d62728", "#2ca02c"]), title=None),
            tooltip=["playbook", "scam_payments_judged", alt.Tooltip("miss_pct:Q", format=".0f")]),
            use_container_width=True)
    with right:
        st.subheader("Cost to ordinary users")
        st.caption("Honest payments the server flagged while each playbook ran. High bars mean alert fatigue.")
        st.altair_chart(alt.Chart(d).mark_bar(color="#ff7f0e").encode(
            x=alt.X("false_alarm_pct:Q", title="honest payments flagged (%)"),
            y=alt.Y("playbook:N", sort=order, title=None),
            tooltip=["playbook", "normal_payments_judged", "normal_flagged",
                     alt.Tooltip("false_alarm_pct:Q", format=".2f")]), use_container_width=True)

    st.subheader("Every playbook")
    show = d[["playbook", "scam_payments_judged", "scam_called_normal", "miss_pct", "journeys",
              "journeys_fully_missed", "normal_payments_judged", "normal_flagged", "false_alarm_pct",
              "fail_open", "breakthrough", "scorer"]].sort_values("miss_pct", ascending=False)
    st.dataframe(show, use_container_width=True, hide_index=True, column_config={
        "miss_pct": st.column_config.ProgressColumn("called normal %", min_value=0, max_value=100, format="%.0f%%"),
        "false_alarm_pct": st.column_config.NumberColumn("false alarms %", format="%.2f%%")})
    st.download_button("Download these results (CSV)", d.to_csv(index=False).encode(),
                       "red_team_results.csv", "text/csv")


def playbook_detail(out: Path, name: str) -> None:
    """One playbook: where in the journey the server lost it."""
    f = out / name / "results.csv"
    if not f.exists():
        st.info("No per-payment results for this playbook.")
        return
    r = pd.read_csv(f)
    # called_normal is empty on fail-open rows, so pandas reads the column as text.
    for col in ("judged", "is_scam", "called_normal"):
        r[col] = r[col].map({True: True, False: False, "True": True, "False": False}).fillna(False).astype(bool)
    scam = r[r.judged & r.is_scam]
    if scam.empty:
        st.info("No scam payments were judged for this playbook.")
        return
    c1, c2 = st.columns(2)
    with c1:
        st.caption("Threat score the server gave each scam payment. Everything on the left of the "
                   "red line was treated as an ordinary payment.")
        hist = alt.Chart(scam).mark_bar().encode(
            x=alt.X("threat_score:Q", bin=alt.Bin(step=5), title="threat score"),
            y=alt.Y("count()", title="scam payments"), color=alt.value("#d62728"))
        line = alt.Chart(pd.DataFrame({"x": [70]})).mark_rule(color="red", strokeDash=[6, 4]).encode(x="x:Q")
        st.altair_chart(hist + line, use_container_width=True)
    with c2:
        st.caption("By step of the scam. Early steps are usually small payments the server lets through.")
        by_step = (scam.assign(step=scam.journey_pay_index.fillna(-1).astype(int))
                   .groupby("step").agg(n=("threat_score", "size"),
                                        called_normal=("called_normal", "sum")).reset_index())
        by_step["caught"] = by_step.n - by_step.called_normal
        melted = by_step.melt(id_vars="step", value_vars=["called_normal", "caught"],
                              var_name="result", value_name="payments")
        melted["result"] = melted["result"].map({"called_normal": "called normal", "caught": "caught"})
        st.altair_chart(alt.Chart(melted).mark_bar().encode(
            x=alt.X("step:O", title="step of the scam (0 = first payment)"),
            y=alt.Y("payments:Q", title="payments"),
            color=alt.Color("result:N", scale=alt.Scale(domain=["called normal", "caught"],
                                                        range=["#d62728", "#2ca02c"]), title=None)),
            use_container_width=True)
    st.caption("Why the server flagged the ones it caught:")
    reasons = scam[~scam.called_normal.fillna(False)].reasons.dropna()
    if len(reasons):
        counts = pd.Series([x for line in reasons for x in str(line).split("|") if x]).value_counts()
        st.bar_chart(counts)
    else:
        st.info("It flagged none of them.")


# ---------------------------------------------------------------- page

st.title("🔴 RUKO red team")
st.caption("Run scam playbooks against the real RUKO server and see which ones it treats as ordinary payments.")

with st.sidebar:
    st.header("Settings")
    folder_choice = st.radio("Playbooks to run", ["Curated (playbooks/)", "Generated (playbook_v2/)"])
    folder = CURATED if folder_choice.startswith("Curated") else GENERATED
    n_books = len(sorted({*folder.glob("*.yaml"), *folder.glob("*.yml")})) if folder.is_dir() else 0
    st.caption(f"`{folder.relative_to(ROOT)}` — {n_books} playbooks")

    st.subheader("World")
    users = st.number_input("Users in the world", 100, 5000, 300, 50)
    days = st.number_input("Days", 7, 60, 14, 1)
    victims = st.number_input("Users attacked", 1, int(users), min(20, int(users)), 1,
                              help="Each one gives a few scam payments to judge. 20 or more is steady.")
    honest = st.number_input("Honest users alongside", 0, 500, 40, 10,
                             help="They give the false-alarm rate. This is the main speed knob.")

    st.subheader("What counts as a breakthrough")
    normal_max = st.slider("The server 'called it normal' at a threat score of", 0, 100, 70)
    share = st.slider("…for at least this share of a playbook's scam payments", 0.5, 1.0, 0.75, 0.05)

    st.caption(f"Roughly {max(1, round(n_books * (victims + honest) * 0.04)):,} minutes for all "
               f"{n_books} playbooks on this machine.")
    if st.session_state.get("proc") and st.button("Stop", type="primary"):
        st.session_state["stop"] = True

tab_run, tab_results, tab_one, tab_gen = st.tabs(
    ["▶ Run", "📊 Results", "🔍 One playbook", "✨ Generate"])

with tab_gen:
    st.subheader("Generate playbooks")
    st.caption(f"Writes to `{GENERATED.relative_to(ROOT)}`. Needs BEDROCK_MODEL_ID and "
               "AWS_DEFAULT_REGION; without them the generator falls back to its built-in rules.")
    count = st.number_input("How many", 1, 200, 30, 1)
    if st.button("Generate"):
        made = run_generator(int(count), st.empty())
        st.success(f"{len(made)} playbooks written.") if made else None

with tab_run:
    st.subheader(f"Run {n_books} playbooks against RUKO")
    st.caption("Each playbook gets its own small world; the real engine (LightGBM scorer) judges "
               "every payment in it.")
    out_name = st.text_input("Save results as", "ui_run")
    if st.button("Run evaluation", type="primary", disabled=not n_books):
        out = RESULTS / out_name
        csv = run_evaluation(folder, int(victims), int(users), int(days), int(honest),
                             int(normal_max), float(share), out, st.empty())
        if csv:
            st.session_state["csv"] = str(csv)
            st.success("Finished. Open the Results tab.")

with tab_results:
    known = sorted(p.parent.name for p in RESULTS.glob("*/all_playbooks.csv")) if RESULTS.is_dir() else []
    if not known:
        st.info("No results yet. Run an evaluation first.")
    else:
        default = Path(st.session_state.get("csv", "")).parent.name
        pick = st.selectbox("Results from", known, index=known.index(default) if default in known else 0)
        path = RESULTS / pick / "all_playbooks.csv"
        st.caption(f"`{path.relative_to(ROOT)}`")
        results_charts(pd.read_csv(path))

with tab_one:
    known = sorted(p.parent.name for p in RESULTS.glob("*/all_playbooks.csv")) if RESULTS.is_dir() else []
    if not known:
        st.info("No results yet.")
    else:
        pick = st.selectbox("Results from", known, key="one_run")
        out = RESULTS / pick
        df = pd.read_csv(out / "all_playbooks.csv").sort_values("miss_rate", ascending=False)
        name = st.selectbox("Playbook", df.playbook.tolist())
        row = df[df.playbook == name].iloc[0]
        m1, m2, m3 = st.columns(3)
        m1.metric("Called normal", f"{row.miss_rate:.0%}",
                  "got through" if row.breakthrough else "caught")
        m2.metric("Scam payments judged", int(row.scam_payments_judged))
        m3.metric("Journeys missed at every step", f"{int(row.journeys_fully_missed)} of {int(row.journeys)}")
        playbook_detail(out, name)
        yml = out / name / "playbook.yaml"
        if yml.exists():
            with st.expander("The playbook that was run"):
                st.code(yml.read_text(encoding="utf-8"), language="yaml")
