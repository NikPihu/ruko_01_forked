"""The sim_v2 generation report: charts + plain-text explanations of one built world.

    python -m sim_v2 report --data data/sim_v2_out/small
    -> DIR/report.html (one self-contained file) and DIR/report.docx (Word)

Written once, re-run after every build (`build` calls it automatically). Every section starts
with a short "what this is / what to look at" paragraph filled with the run's own numbers.
To add a chart: write a function that returns a Section and add it to SECTIONS at the bottom.
"""
from __future__ import annotations

import base64
import html
import io
import json
from dataclasses import dataclass, field
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

plt.rcParams.update({"figure.figsize": (8, 3.4), "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.alpha": 0.3, "font.size": 9})
COL = {"scam": "#d62728", "look-alike": "#ff7f0e", "everyday": "#1f77b4", "mule": "#9467bd", "other": "#7f7f7f"}
MAX_USERS_FOR_CALL_OVERLAP = 3000   # the "paid during an unknown call" check uses a sample of users at 20k


@dataclass
class Section:
    title: str
    intro: str
    items: list = field(default_factory=list)   # ("chart", png_bytes, caption) | ("table", df, caption) | ("pre", text, caption)

    def chart(self, fig, caption: str = "") -> None:
        buf = io.BytesIO()
        fig.tight_layout()
        fig.savefig(buf, format="png", dpi=110)
        plt.close(fig)
        self.items.append(("chart", buf.getvalue(), caption))

    def table(self, df: pd.DataFrame, caption: str = "") -> None:
        self.items.append(("table", df, caption))

    def pre(self, text: str, caption: str = "") -> None:
        self.items.append(("pre", text, caption))


class World:
    """Loaded tables plus a few derived columns every section needs."""

    def __init__(self, d: Path):
        self.d = d
        t = {n: pd.read_parquet(d / f"{n}.parquet") for n in
             ("ledger", "context_events", "accounts", "users", "journeys", "reports", "decisions", "crews")}
        self.led, self.ev, self.acc, self.users = t["ledger"], t["context_events"], t["accounts"], t["users"]
        self.jr, self.rep, self.dec, self.crews = t["journeys"], t["reports"], t["decisions"], t["crews"]
        self.man = json.loads((d / "manifest.json").read_text())
        self.cfg = self.man["config"]
        merch = set(self.acc.upi_id[self.acc.holder_type == "merchant"])
        self.user_upi = set(self.users.upi_id)
        u = self.led[self.led.from_upi.isin(self.user_upi)].copy()
        u["kind"] = np.where(u.to_upi.isin(merch), "P2M", "P2P")
        u["group"] = np.where(u.flow == "scam", "scam",
                              np.where(u.scenario.notna() & ~u.scenario.isin(["rent", "bill"]), "look-alike", "everyday"))
        u["user_id"] = u.from_upi.map(self.users.set_index("upi_id").user_id)
        self.upay = u
        self.real_j = self.jr[~self.jr.is_demo]


def _pct(x: float) -> str:
    return f"{x:.1%}"


def _inr(x: float) -> str:
    return f"₹{x:,.0f}"


# ---------------------------------------------------------------- sections

def overview(w: World) -> Section:
    c, rows = w.cfg, w.man["rows"]
    users_lost = w.real_j[w.real_j.n_payments > 0].user_id.nunique()
    s = Section("1. Overview", (
        f"This world has {c.get('n_users', c.get('users')):,} app users over {c.get('n_days', c.get('days'))} days "
        f"(seed {c.get('seed')}, {c.get('world')} world, config fingerprint {w.man['config_fingerprint']}). "
        f"It holds {rows['ledger']:,} payments and {rows['context_events']:,} phone events. "
        f"{len(w.real_j):,} scam journeys approached {w.real_j.user_id.nunique() / len(w.users):.1%} of users and "
        f"{users_lost / len(w.users):.1%} lost money (plus 3 scripted demo journeys). Mule accounts are "
        f"{w.acc.is_mule.mean():.1%} of all accounts. Same seed and config = the same world; another seed = a new "
        "variation inside the same ranges."))
    s.table(pd.DataFrame({"table": list(rows), "rows": [f"{v:,}" for v in rows.values()]}), "Rows per table")
    up = w.upay
    key = {"users": len(w.users), "accounts": len(w.acc), "mule accounts": int(w.acc.is_mule.sum()),
           "mule share of accounts": _pct(w.acc.is_mule.mean()), "user payments": len(up),
           "scam payments": int((up.flow == "scam").sum()), "scam share of user payments": f"{(up.flow == 'scam').mean():.3%}",
           "journeys (incl. 3 demo)": len(w.jr), "users approached": _pct(w.real_j.user_id.nunique() / len(w.users)),
           "users who lost money": _pct(users_lost / len(w.users)), "total lost to scams": _inr(w.jr.total_paid.sum()),
           "look-alike payments": int((up.group == "look-alike").sum()), "reports": w.rep.report_id.nunique()}
    s.table(pd.DataFrame({"measure": list(key), "value": [str(v) for v in key.values()]}), "Key numbers")
    return s


def population(w: World) -> Section:
    u = w.users
    per_day = w.upay[w.upay.group == "everyday"].groupby("user_id").size() / max(1, w.cfg.get("n_days", 1))
    s = Section("2. Population: who lives in this world", (
        f"{len(u):,} users in {u.region.nunique()} cities. Personas set how often people pay and how much "
        f"(assumptions.yaml → population.personas). Activity is very unequal on purpose: the busiest 10% of users "
        f"pay {per_day.quantile(.9) / max(per_day.quantile(.1), 1e-9):.0f}× more often than the quietest 10% "
        f"(real Xente users: 58×). Consents decide what a phone may later report: SMS {u.sms_consent.mean():.0%}, "
        f"calls {u.call_consent.mean():.0%}, app checks {u.app_consent.mean():.0%}."))
    fig, ax = plt.subplots(1, 3, figsize=(11, 3.2))
    u.persona.value_counts().plot.bar(ax=ax[0], color=COL["everyday"], title="Personas")
    u.age_band.value_counts().sort_index().plot.bar(ax=ax[1], color=COL["everyday"], title="Age bands (audit only)")
    u.region.value_counts().plot.bar(ax=ax[2], color=COL["everyday"], title="Cities")
    s.chart(fig, "Who the users are")
    fig, ax = plt.subplots(1, 3, figsize=(11, 3.2))
    ax[0].hist(np.log10(u.income_month), bins=30, color=COL["everyday"]); ax[0].set_title("Monthly income (log10 ₹)")
    ax[1].hist(u.savings_months, bins=30, color=COL["everyday"]); ax[1].set_title("Savings reach (months of income)")
    ax[2].hist(np.log10(per_day.clip(lower=1e-3)), bins=40, color=COL["everyday"]); ax[2].set_title("Payments per day per user (log10)")
    s.chart(fig, "Money and activity: wide spreads make per-user features realistic")
    return s


def everyday(w: World) -> Section:
    up = w.upay[w.upay.group != "scam"]
    m, p = up[up.kind == "P2M"].amount, up[up.kind == "P2P"].amount
    anchors = json.loads((Path(__file__).resolve().parents[1] / "eval/realism/npci_anchors.json").read_text())["targets"]
    got = {"p2m_share_of_volume": len(m) / (len(m) + len(p)), "p2m_share_of_value": m.sum() / (m.sum() + p.sum()),
           "avg_ticket_p2p_inr": p.mean(), "avg_ticket_p2m_inr": m.mean(),
           "p2m_share_below_500": (m < 500).mean(), "p2p_share_below_500": (p < 500).mean()}
    s = Section("3. Everyday payments", (
        f"{len(up):,} honest payments by users. Amounts are drawn from distributions fitted to NPCI's published "
        f"numbers: {got['p2m_share_of_volume']:.0%} go to merchants (NPCI 63%), {got['p2m_share_below_500']:.0%} of "
        f"merchant payments are under ₹500 (NPCI 86%), average P2P {_inr(got['avg_ticket_p2p_inr'])} (NPCI ₹2,320). "
        "The hour curve copies real Xente behaviour. Rent, bills and look-alikes add large, typed or round payments."))
    t = pd.DataFrame({"NPCI target": {k: anchors[k]["value"] for k in got}, "this world": got}).round(3)
    s.table(t.reset_index(names="measure"), "NPCI anchors (real) vs this world")
    fig, ax = plt.subplots()
    bins = np.logspace(0, 5.2, 70)
    ax.hist(m, bins, histtype="step", lw=2, label="merchant (P2M)", density=True)
    ax.hist(p, bins, histtype="step", lw=2, label="person (P2P)", density=True)
    ax.axvline(500, color="red", ls="--", label="₹500"); ax.set_xscale("log"); ax.set_xlabel("₹ (log)"); ax.legend()
    ax.set_title("Amount distribution")
    s.chart(fig, "Most payments are small; a long tail of large ones")
    fig, ax = plt.subplots(1, 2, figsize=(11, 3.2))
    (up.ts.dt.hour.value_counts(normalize=True).sort_index()).plot(ax=ax[0], marker=".", title="Share of payments by hour")
    up.ts.dt.day_name().str[:3].value_counts().reindex(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]).plot.bar(
        ax=ax[1], color=COL["everyday"], title="Payments by weekday")
    s.chart(fig, "When people pay")
    fig, ax = plt.subplots()
    pd.crosstab(up.kind, up.entry_method, normalize="index").plot.barh(stacked=True, ax=ax, title="How the payee was chosen")
    s.chart(fig, "QR dominates merchant payments; saved contacts dominate person payments")
    f = w.led.assign(scenario=w.led.scenario.fillna("")).groupby(["flow", "scenario"]).agg(
        payments=("amount", "size"), median_inr=("amount", "median"),
        typed=("entry_method", lambda x: round((x == "typed").mean(), 2))).reset_index()
    s.table(f, "All payments by flow (scenario = look-alike / rent / bill)")
    return s


def phone(w: World) -> Section:
    ev = w.ev
    calls = ev[ev.event_type == "call_started"]
    a = calls["attrs"].map(json.loads)
    kind = np.where(a.map(lambda x: x["in_contacts"]), np.where(a.map(lambda x: x["call_kind"]) == "voip", "known (VoIP)", "known"),
                    np.where(a.map(lambda x: x["call_kind"]) == "voip", "unknown VoIP", "unknown SIM"))
    is_scam = calls.journey_id.notna().to_numpy()
    lures = ev[ev.event_type.isin(["sms_lure", "notification_lure"])]
    tags = lures["attrs"].map(lambda x: json.loads(x)["tag"])
    days = max(1, w.cfg.get("n_days", 1))
    s = Section("4. Phone activity: the background scam signals must stand out from", (
        f"{len(calls):,} calls ({len(calls) / len(w.users) / days:.2f} per user per day). "
        f"{(kind[~is_scam] != 'known').mean():.0%} of ordinary calls are from unknown numbers (delivery, banks, spam), "
        f"so 'on a call with an unknown number' is common in honest life. {len(lures):,} scam-looking messages arrived; "
        f"only {lures.journey_id.notna().mean():.0%} belong to a real scam journey; the rest are spam nobody acted on."))
    fig, ax = plt.subplots(1, 2, figsize=(11, 3.2))
    pd.crosstab(kind, np.where(is_scam, "scam call", "ordinary call"), normalize="columns").plot.bar(ax=ax[0], title="Who is calling")
    pd.crosstab(tags, np.where(lures.journey_id.notna(), "scam journey", "spam / noise")).plot.bar(ax=ax[1], title="Scam-looking messages by tag")
    s.chart(fig, "Calls and lure messages: scam vs everyday")
    inst = ev[ev.event_type == "app_installed"]
    ia = inst["attrs"].map(json.loads)
    t = pd.DataFrame({"remote-access app": ia.map(lambda x: x["is_remote_access"]), "sideloaded": ia.map(lambda x: x["sideloaded"]),
                      "source": np.where(inst.journey_id.notna(), "scam", np.where(inst.scenario.notna(), "look-alike", "everyday"))})
    s.table(t.groupby("source")[["remote-access app", "sideloaded"]].sum().astype(int).reset_index(),
            "App installs: remote-access and sideloaded apps also appear in honest life")
    return s


def lookalikes(w: World) -> Section:
    la = w.upay[w.upay.group == "look-alike"]
    g = la.groupby("scenario").agg(payments=("amount", "size"), median_inr=("amount", "median"),
                                   typed=("entry_method", lambda x: (x == "typed").mean()),
                                   round_100=("amount", lambda a: ((a % 100 == 0) & (a >= 500)).mean())).round(2)
    s = Section("5. Look-alikes: honest payments that look like scams", (
        f"{len(la):,} honest payments in {len(g)} situations (config/lookalikes.yaml), e.g. a landlord deposit typed "
        "to a brand-new payee while on a call with an unknown number. They carry flow 'normal' and are never labelled "
        "scam. Without them a model could learn 'large + typed + new payee = scam'; with them it has to combine signals."))
    fig, ax = plt.subplots(1, 2, figsize=(11, 3.4))
    g.payments.sort_values().plot.barh(ax=ax[0], color=COL["look-alike"], title="Payments per look-alike")
    g.median_inr.sort_values().plot.barh(ax=ax[1], color=COL["look-alike"], title="Median amount (₹)", logx=True)
    s.chart(fig, "Look-alike types")
    s.table(g.reset_index(), "Look-alike payments")
    return s


def scams(w: World) -> Section:
    j = w.real_j.copy()
    scam = w.led[w.led.flow == "scam"]
    j["engaged"] = j.complied_steps > 0
    j["paid"] = j.n_payments > 0
    f = j.groupby("playbook").agg(approached=("journey_id", "size"), engaged=("engaged", "sum"), paid=("paid", "sum"),
                                  reported=("reported", "sum"), lost=("total_paid", "sum")).sort_values("approached", ascending=False)
    s = Section("6. Scams: what the crews did and what happened", (
        f"{len(j):,} journeys across {j.playbook.nunique()} playbooks (config/playbooks/*.yaml). Each journey runs its "
        f"playbook step by step; at every ask the victim decides. {j.paid.mean():.0%} of approached victims paid "
        f"something, {j.reported.mean():.0%} reported. Total lost: {_inr(j.total_paid.sum())}. The funnel shows where "
        "each scam type loses its victims; the box plot shows how much paying victims lost."))
    fig, ax = plt.subplots(figsize=(9, 3.8))
    f[["approached", "engaged", "paid", "reported"]].plot.bar(ax=ax, title="Funnel per playbook")
    s.chart(fig, "approached → engaged (complied at least once) → paid → reported")
    s.table(f.reset_index().assign(lost=lambda x: x.lost.map(_inr)), "Journeys per playbook")
    paid = j[j.paid]
    if len(paid):
        fig, ax = plt.subplots(1, 2, figsize=(11, 3.6))
        order = paid.groupby("playbook").total_paid.median().sort_values().index
        ax[0].boxplot([paid[paid.playbook == p].total_paid for p in order], vert=False, tick_labels=list(order))
        ax[0].set_xscale("log"); ax[0].set_title("Lost per paying victim (₹, log)")
        last = scam.groupby("journey_id").ts.max()
        dur = ((paid.journey_id.map(last) - paid.started_at).dt.total_seconds() / 3600).clip(lower=0.01)
        ax[1].boxplot([dur[paid.playbook == p] for p in order], vert=False, tick_labels=list(order))
        ax[1].set_xscale("log"); ax[1].set_title("Hours from first contact to last payment (log)")
        s.chart(fig, "Fast scams (digital arrest, refund QR) vs slow ladders (task job, trading)")
        fig, ax = plt.subplots()
        paid.n_payments.value_counts().sort_index().plot.bar(ax=ax, color=COL["scam"], title="Payments per paying victim")
        s.chart(fig)
    fig, ax = plt.subplots(figsize=(9, 3.6))
    for pb in ("task_job", "trading_group", "digital_arrest", "lottery_prize"):
        cand = paid[(paid.playbook == pb) & (paid.n_payments >= 2)]
        if len(cand):
            jid = cand.journey_id.iloc[0]
            r = scam[scam.journey_id == jid].sort_values("ts")
            ax.plot((r.ts - r.ts.min()).dt.total_seconds() / 86400, r.amount, marker="o", label=f"{pb} ({jid})")
    ax.set_yscale("log"); ax.set_xlabel("days since first scam payment"); ax.set_ylabel("₹"); ax.legend(fontsize=7)
    ax.set_title("Example journeys: each dot is one scam payment")
    s.chart(fig, "Ladders climb over days; coached scams pay big within hours")
    return s


def decisions(w: World) -> Section:
    v = w.dec[w.dec.kind == "victim"].copy()
    if v.empty:
        return Section("7. Victim decisions", "No victim decisions in this world.")
    inp = pd.json_normalize(v["inputs"].map(json.loads))
    v = pd.concat([v.reset_index(drop=True), inp], axis=1)
    s = Section("7. Victim decisions: why people paid or refused", (
        f"{len(v):,} victim decisions. Each one is p_comply = logistic(base + pressure + sunk cost − doubt − big ask), "
        f"with every term logged (decisions.parquet, `inputs`). Outcomes: {v.outcome.value_counts().to_dict()}. "
        "The scatter shows the key brake: the bigger an ask is compared with what the victim can reach "
        "(income × savings months), the less likely they comply."))
    fig, ax = plt.subplots(1, 2, figsize=(11, 3.4))
    for o, g in v.groupby("outcome"):
        ax[0].hist(g.p, bins=20, range=(0, 1), alpha=0.6, label=o)
    ax[0].legend(); ax[0].set_xlabel("p_comply"); ax[0].set_title("p at each decision, by outcome")
    asks = v[v.ask_inr > 0]
    ax[1].scatter((asks.ask_inr / asks.capacity_inr).clip(upper=3), asks.p, c=(asks.outcome == "comply"), cmap="coolwarm", s=10)
    ax[1].set_xlabel("ask ÷ what the victim can reach (capped at 3)"); ax[1].set_ylabel("p_comply"); ax[1].set_title("Bigger asks, less compliance")
    s.chart(fig)
    ref = v[v.outcome != "comply"]
    if len(ref):
        fig, ax = plt.subplots()
        ref.step_no.value_counts().sort_index().plot.bar(ax=ax, color=COL["scam"], title="Refusals and delays by step number")
        ax.set_xlabel("step number in the playbook")
        s.chart(fig, "Most people drop out at the first contact or at the first big ask")
    return s


def mules(w: World) -> Section:
    acc, led, rep, cr = w.acc, w.led, w.rep, w.crews.copy()
    created = acc.set_index("upi_id").created_at
    cr["age_days"] = (cr.active_from - cr.mule_upi_id.map(created)).dt.days.clip(lower=1)
    cr["active_days"] = (cr.active_to - cr.active_from).dt.total_seconds() / 86400
    listed = rep[~rep.is_false & (rep.identifier_type == "upi_id")].groupby("identifier").listed_at.min()
    scam = led[led.flow == "scam"]
    unlisted = 1 - (scam.to_upi.map(listed) < scam.ts).mean() if len(scam) else float("nan")
    mule_ids = set(acc.upi_id[acc.is_mule & (acc.mule_kind != "cash_out")])
    payers = led.groupby("to_upi").from_upi.nunique()
    s = Section("8. Mules: short-lived, mixed ages, mostly unknown to the lists", (
        f"{int(acc.is_mule.sum()):,} mule accounts ({acc.is_mule.mean():.1%} of accounts) in {cr.crew_id.nunique()} crews. "
        f"A mule works a median {cr.active_days.median():.0f} days, then the crew replaces it. Ages mix fresh accounts "
        "with old rented ones, so account age alone cannot give the label away. "
        f"{unlisted:.0%} of scam payments reach a mule that no list knows yet at that moment: the gap RUKO exists for."))
    fig, ax = plt.subplots(1, 3, figsize=(12, 3.3))
    cr.mule_kind.value_counts().plot.bar(ax=ax[0], color=COL["mule"], title="Mule kinds")
    kinds = list(cr.mule_kind.value_counts().index)
    ax[1].boxplot([cr[cr.mule_kind == k].age_days for k in kinds], tick_labels=kinds); ax[1].set_yscale("log")
    ax[1].set_title("Account age when put to work (days, log)"); ax[1].tick_params(axis="x", rotation=45)
    ax[2].hist(cr.active_days, bins=20, color=COL["mule"]); ax[2].set_title("Days active")
    s.chart(fig)
    fig, ax = plt.subplots(1, 2, figsize=(11, 3.3))
    mp = payers[payers.index.isin(mule_ids)]
    np_ = payers[~payers.index.isin(mule_ids | set(acc.upi_id[acc.is_mule]))]
    bins = np.arange(1, 40)
    ax[0].hist(np_.clip(upper=39), bins=bins, density=True, alpha=0.6, label="honest payees")
    ax[0].hist(mp.clip(upper=39), bins=bins, density=True, alpha=0.6, label="mules", color=COL["mule"])
    ax[0].set_yscale("log"); ax[0].legend(); ax[0].set_title("Distinct payers per account")
    fwd = led[led.flow == "mule_forward"]
    inflow = led[led.to_upi.isin(mule_ids)].groupby("to_upi").amount.sum()
    pt = (fwd.groupby("from_upi").amount.sum() / inflow).dropna().clip(upper=1.5)
    ax[1].hist(pt, bins=30, color=COL["mule"]); ax[1].set_title("Pass-through per mule (out ÷ in)")
    s.chart(fig, "Mules collect from several strangers and pass most money on; kiranas also have many payers, but repeat ones")
    return s


def reports(w: World) -> Section:
    rep = w.rep.drop_duplicates("report_id")
    s = Section("9. Reports and lists", (
        f"{len(rep):,} reports. Lists (I4C registry, DoT FRI) only learn from these, after a lag, never from the true "
        f"mule labels. {rep.is_false.mean():.0%} are false reports against honest accounts. Median filing lag "
        f"{((rep.listed_at - rep.filed_at).dt.total_seconds() / 86400).median():.1f} days from filing to listing."))
    fig, ax = plt.subplots(1, 2, figsize=(11, 3.2))
    pd.crosstab(rep.source, rep.is_false.map({True: "false", False: "true"})).plot.bar(ax=ax[0], stacked=True, title="Reports by source")
    ax[1].hist((rep.listed_at - rep.filed_at).dt.total_seconds() / 86400, bins=30, color=COL["other"])
    ax[1].set_title("Days from filing to listing")
    s.chart(fig)
    return s


def scam_vs(w: World) -> Section:
    up = w.upay.copy()
    users = list(w.users.user_id[: MAX_USERS_FOR_CALL_OVERLAP])
    en = w.ev[(w.ev.event_type == "call_ended") & w.ev.user_id.isin(users)]
    a = en["attrs"].map(json.loads)
    calls = pd.DataFrame({"user_id": en.user_id.to_numpy(), "end": en.ts.to_numpy(),
                          "start": (en.ts - pd.to_timedelta(a.map(lambda x: x["duration_min"]), unit="m")).to_numpy(),
                          "unknown": a.map(lambda x: not x["in_contacts"]).to_numpy()})
    calls = calls[calls.unknown]
    sub = up[up.user_id.isin(users)][["user_id", "ts"]].reset_index()
    m = sub.merge(calls, on="user_id")
    oncall = set(m[(m.ts >= m.start) & (m.ts <= m.end)]["index"])
    up["on_unknown_call"] = np.where(up.user_id.isin(users), up.index.isin(oncall), np.nan)
    up["new_payee"] = ~up.sort_values("ts").duplicated(["from_upi", "to_upi"])
    t = up.groupby("group").agg(payments=("amount", "size"), median_inr=("amount", "median"),
                                typed=("entry_method", lambda x: (x == "typed").mean()),
                                round_100=("amount", lambda x: ((x % 100 == 0) & (x >= 500)).mean()),
                                new_payee=("new_payee", "mean"), on_unknown_call=("on_unknown_call", "mean")).round(3)
    s = Section("10. Why scams are hard to spot: no single clue separates them", (
        "For payments made by app users: how often each group is typed by hand, a round amount, to a never-paid "
        "payee, or made while on a call with an unknown number. Scams lead on some clues, but look-alikes share every "
        "one of them, so RUKO must combine families (CLAUDE.md rule 5). "
        f"(Call overlap measured on the first {len(users):,} users.)"))
    fig, ax = plt.subplots(figsize=(9, 3.4))
    t[["typed", "round_100", "new_payee", "on_unknown_call"]].T.plot.bar(
        ax=ax, color=[COL.get(c, COL["other"]) for c in t.index], title="Share of payments with each clue")
    ax.tick_params(axis="x", rotation=0)
    s.chart(fig)
    s.table(t.reset_index(), "Clues by group")
    return s


def assumptions(w: World) -> Section:
    from sim_v2.core.config import load
    cfg = load()
    rows = [{"key": f"{sec}.{k}", "confidence": e.get("conf"), "source": e.get("src")}
            for sec, items in cfg.a_meta.items() for k, e in items.items()]
    df = pd.DataFrame(rows)
    pbs = pd.DataFrame([{"playbook": n, "weight": p["weight"], "steps": len(p["steps"]), "confidence": p["confidence"],
                         "emerging": bool(p.get("emerging")), "title": p["title"]} for n, p in cfg.playbooks.items()])
    s = Section("11. Assumptions: how much is real and how much is guessed", (
        f"{len(df)} numbers drive this world (config/assumptions.yaml). {(df.confidence == 'official').sum()} come "
        f"from official data (NPCI), {(df.confidence == 'data').sum()} from measured datasets, "
        f"{(df.confidence == 'guess').sum()} are guesses to be replaced as real evidence arrives "
        "(config/cases.csv for playbooks). `python -m sim_v2 assumptions --guesses` lists them."))
    fig, ax = plt.subplots(figsize=(6, 2.8))
    df.confidence.value_counts().plot.barh(ax=ax, color=[COL["everyday"], COL["look-alike"], COL["scam"]][: df.confidence.nunique()],
                                           title="Assumptions by confidence")
    s.chart(fig)
    s.table(pbs, "Playbooks (steps are numbered 1..n in decisions.step_no)")
    return s


def checks(w: World) -> Section:
    v = w.d / "validate.txt"
    s = Section("12. Checks", "Result of `python -m sim_v2 validate` for this world (schema vs data/sim, labels, "
                "determinism, subset stability, mule share).")
    s.pre(v.read_text(encoding="utf-8") if v.exists() else "validate.txt not found: run `python -m sim_v2 validate --data DIR`.")
    return s


SECTIONS = [overview, population, everyday, phone, lookalikes, scams, decisions, mules, reports, scam_vs, assumptions, checks]


# ---------------------------------------------------------------- writers

def to_html(sections: list[Section], title: str) -> str:
    out = [f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title><style>"
           "body{font-family:Segoe UI,Arial,sans-serif;max-width:1100px;margin:24px auto;padding:0 16px;color:#222}"
           "h1{border-bottom:2px solid #333}h2{margin-top:36px;border-bottom:1px solid #ccc}"
           "p.intro{background:#f5f7fa;padding:10px 14px;border-left:4px solid #1f77b4;line-height:1.5}"
           "table{border-collapse:collapse;font-size:12px;margin:8px 0}td,th{border:1px solid #ddd;padding:3px 8px;text-align:right}"
           "th{background:#eee}img{max-width:100%}.cap{color:#555;font-size:12px;margin-bottom:14px}pre{background:#f5f5f5;padding:10px;font-size:12px}"
           "nav a{margin-right:10px;font-size:13px}</style></head><body>", f"<h1>{html.escape(title)}</h1><nav>"]
    out += [f"<a href='#s{i}'>{html.escape(s.title)}</a>" for i, s in enumerate(sections)]
    out.append("</nav>")
    for i, s in enumerate(sections):
        out.append(f"<h2 id='s{i}'>{html.escape(s.title)}</h2><p class='intro'>{html.escape(s.intro)}</p>")
        for kind, obj, cap in s.items:
            if kind == "chart":
                out.append(f"<img src='data:image/png;base64,{base64.b64encode(obj).decode()}'>")
            elif kind == "table":
                out.append(obj.to_html(index=False, border=0))
            else:
                out.append(f"<pre>{html.escape(obj)}</pre>")
            if cap:
                out.append(f"<div class='cap'>{html.escape(cap)}</div>")
    out.append("</body></html>")
    return "\n".join(out)


def to_docx(sections: list[Section], title: str, path: Path) -> None:
    from docx import Document
    from docx.shared import Inches, Pt
    doc = Document()
    doc.add_heading(title, 0)
    for s in sections:
        doc.add_heading(s.title, 1)
        doc.add_paragraph(s.intro)
        for kind, obj, cap in s.items:
            if kind == "chart":
                doc.add_picture(io.BytesIO(obj), width=Inches(6.5))
            elif kind == "table":
                df = obj.head(40)
                t = doc.add_table(rows=1, cols=len(df.columns))
                t.style = "Light Grid Accent 1"
                for c, name in enumerate(df.columns):
                    t.rows[0].cells[c].text = str(name)
                for _, row in df.iterrows():
                    cells = t.add_row().cells
                    for c, val in enumerate(row):
                        cells[c].text = f"{val:,.3g}" if isinstance(val, float) else str(val)
                for row in t.rows:
                    for cell in row.cells:
                        for par in cell.paragraphs:
                            for run in par.runs:
                                run.font.size = Pt(8)
            else:
                par = doc.add_paragraph()
                run = par.add_run(obj)
                run.font.name, run.font.size = "Consolas", Pt(8)
            if cap:
                doc.add_paragraph(cap).italic = True
    doc.save(path)


def run(d: Path, log=print) -> tuple[Path, Path]:
    w = World(d)
    sections = [f(w) for f in SECTIONS]
    c = w.cfg
    title = f"sim_v2 generation report: {c.get('n_users'):,} users × {c.get('n_days')} days, seed {c.get('seed')} ({d.name})"
    html_path, docx_path = d / "report.html", d / "report.docx"
    html_path.write_text(to_html(sections, title), encoding="utf-8")
    to_docx(sections, title, docx_path)
    n = sum(1 for s in sections for k, *_ in s.items if k == "chart")
    log(f"report: {len(sections)} sections, {n} charts -> {html_path} and {docx_path}")
    return html_path, docx_path
