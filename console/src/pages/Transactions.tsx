import { useState } from "react";
import { api, type Explanation, type Tier } from "../api";
import { inr, PAYMENT_STATUS, PLAYBOOKS, STAGES, TIERS, userLabel, when } from "../format";
import { reasonText } from "../reasons";
import { Card, Empty, Loading, Stat, TierChip, go, useLoad } from "../components/ui";

const FAMILY_SHORT: Record<string, string> = { C: "Context", L: "Lure", P: "Payee", B: "Behaviour" };
const SOURCE_NAME: Record<string, string> = {
  npci: "NPCI (who the payee is)", bank: "Payee's bank / MuleHunter", payee_registry: "I4C registry (payee)",
  caller_registry: "I4C registry (caller)", payee_fri: "DoT FRI (payee number)", caller_fri: "DoT FRI (caller)",
};
function policyStep(s: string): string {
  if (s === "corroboration_gate") return "Fewer than two independent families agreed, so RUKO did not interrupt";
  if (s.startsWith("amount_cap_")) return `Amount under ₹${s.slice("amount_cap_".length)}: capped at a tip`;
  if (s === "trusted_payee") return "The user had said they know this payee";
  if (s === "alert_budget") return "Too many recent alerts on a calm day: softened to a tip";
  return s;
}

/** Every payment check RUKO recorded, newest first (the transaction database). */
export function Transactions() {
  const [minTier, setMinTier] = useState<Tier | "T0">("T0");
  const [status, setStatus] = useState("");
  const { data, error, loading } = useLoad(() => api.transactions({ min_tier: minTier, status, limit: 300 }), [minTier, status]);
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Transactions</h1>
          <p>Every payment check RUKO made, with its decision and what the user did. Open one to see exactly why.</p>
        </div>
        <div className="row">
          <select className="input" value={minTier} onChange={(e) => setMinTier(e.target.value as Tier)}>
            {["T0", "T1", "T2", "T3", "T4"].map((t) => <option key={t} value={t}>{t === "T0" ? "All tiers" : `${t} and above`}</option>)}
          </select>
          <select className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Any outcome</option>
            {Object.entries(PAYMENT_STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
      </div>
      {!data ? <Loading error={error} loading={loading} /> : data.count === 0 ? (
        <Empty title="No payments yet">Make a payment in the app or run the demo agents.</Empty>
      ) : (
        <Card pad={false}>
          <div className="table-wrap">
            <table className="list">
              <thead><tr><th>When</th><th>Decision</th><th>Paid to</th><th className="num">Amount</th><th>Main reason</th><th>Outcome</th></tr></thead>
              <tbody>
                {data.transactions.map((t) => (
                  <tr key={t.payment_id} className="click" onClick={() => go(`#/transactions/${encodeURIComponent(t.payment_id)}`)}>
                    <td>{when(t.ts)}</td>
                    <td><TierChip tier={t.tier} />{t.fail_open && <div className="muted">check unavailable</div>}</td>
                    <td><span className="mono">{t.payee_upi}</span><div className="muted">{userLabel(t.user_hash)}</div></td>
                    <td className="num">{inr(t.amount_inr)}</td>
                    <td>{t.reasons[0] ? reasonText(t.reasons[0]) : <span className="muted">—</span>}
                      {t.playbook && <div className="muted">{PLAYBOOKS[t.playbook] ?? t.playbook}</div>}</td>
                    <td>{PAYMENT_STATUS[t.status]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}

/** One payment, fully explained: what the user saw, and everything behind it. */
export function PaymentExplain({ id }: { id: string }) {
  const { data, error, loading } = useLoad(async () => {
    const [x, list] = await Promise.all([api.explain(id), api.transactions({ limit: 1000 })]);
    return { x, t: list.transactions.find((t) => t.payment_id === id) ?? null };
  }, [id]);
  if (!data) return <Loading error={error} loading={loading} />;
  const { x, t } = data;
  const u = x.user_view;
  return (
    <div className="stack">
      <a href="#/transactions">← Transactions</a>
      <div className="page-head">
        <div>
          <div className="row"><TierChip tier={u.tier} />{u.playbook && <span className="chip">{PLAYBOOKS[u.playbook] ?? u.playbook}</span>}</div>
          <h1 style={{ marginTop: 8 }}>{t ? <>{inr(t.amount_inr)} to <span className="mono">{t.payee_upi}</span></> : x.payment_id}</h1>
          {t && <p>{userLabel(t.user_hash)} · {when(t.ts)} · {PAYMENT_STATUS[t.status]} · scorer {x.scorer_version ?? "—"} · {t.latency_ms != null ? `${Math.round(t.latency_ms)} ms` : ""}</p>}
        </div>
      </div>

      <div className="grid grid-main">
        <Card title="What the user saw">
          {u.tier === "T0" ? <p className="ink2" style={{ margin: 0 }}>Nothing: the payment went straight to the PIN.</p> : (
            <>
              <div className="callout"><b>{TIERS[u.tier]?.name}.</b> {TIERS[u.tier]?.action}.</div>
              <ul className="reasons plain" style={{ marginTop: 12 }}>
                {u.reasons.map((r) => <li key={r}>• {reasonText(r)}</li>)}
              </ul>
            </>
          )}
          <p className="muted" style={{ margin: "12px 0 0" }}>Users see at most three reasons in words and never a score.</p>
        </Card>
        <Card title="Scores (analysts only)">
          <div className="grid" style={{ gridTemplateColumns: "repeat(2, minmax(0,1fr))" }}>
            <Stat label="Overall scam score" value={x.scores.p_scam != null ? x.scores.p_scam.toFixed(3) : "—"} sub={`${x.scores.lit_families.length} of 4 families lit`} />
            {Object.entries(x.scores.families).map(([k, v]) => (
              <Stat key={k} label={FAMILY_SHORT[k] ?? k} value={v.toFixed(2)}
                    sub={x.scores.lit_families.includes(k) ? "lit (≥ 0.5)" : "not lit"} />
            ))}
          </div>
        </Card>
      </div>

      <Card title="How the decision links together">
        <LinkGraph x={x} />
      </Card>

      <Card title="Every reason and the inputs behind it" pad={false}>
        <div className="table-wrap">
          <table className="list">
            <thead><tr><th>Reason</th><th>Family</th><th>Push</th><th>Inputs that caused it</th><th>Shown to user</th></tr></thead>
            <tbody>
              {x.reasons.map((r) => (
                <tr key={r.code}>
                  <td>{reasonText(r.code)}<div className="muted mono">{r.code}</div></td>
                  <td>{r.family ? FAMILY_SHORT[r.family] : "—"}</td>
                  <td>{r.band ?? "—"}{r.strength != null && <div className="muted">{r.strength.toFixed(2)} · {r.signals} signal{r.signals === 1 ? "" : "s"}</div>}</td>
                  <td className="mono" style={{ fontSize: 12 }}>{Object.entries(r.inputs).map(([k, v]) => <div key={k}>{k} = {String(v)}</div>)}</td>
                  <td>{r.shown_to_user ? "yes" : "no"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid grid-main">
        <Card title="Scam playbooks checked">
          <ul className="reasons plain">
            {x.playbooks.map((p, i) => (
              <li key={i} style={{ opacity: p.matched ? 1 : 0.55 }}>
                {p.chosen ? "✔ " : p.matched ? "• " : "✕ "}<b>{PLAYBOOKS[p.playbook] ?? p.playbook}</b>: {p.rule}
                {p.chosen && <span className="chip" style={{ marginLeft: 6 }}>chosen</span>}
              </li>
            ))}
          </ul>
        </Card>
        <div className="stack">
          <Card title="Policy steps">
            {x.policy_steps.length ? <ul className="reasons plain">{x.policy_steps.map((s) => <li key={s}>• {policyStep(s)}</li>)}</ul>
              : <p className="muted" style={{ margin: 0 }}>The tier came straight from the scores.</p>}
          </Card>
          <Card title="Outside sources">
            <ul className="reasons plain">
              {Object.entries(x.sources).map(([k, v]) => <li key={k}>{SOURCE_NAME[k] ?? k}: <b>{v}</b></li>)}
            </ul>
          </Card>
          <Card title="Scam journey">
            <p style={{ margin: 0 }}>{x.stage_path.map(([s]) => STAGES[s] ?? s).join(" → ") || "—"}</p>
          </Card>
        </div>
      </div>
    </div>
  );
}

/** payment → families (with scores) → reasons → inputs, and the chosen playbook. */
function LinkGraph({ x }: { x: Explanation }) {
  const fams = Object.keys(x.scores.families);
  const reasons = x.reasons.filter((r) => r.family);
  const inputs = Array.from(new Set(reasons.flatMap((r) => Object.keys(r.inputs))));
  const playbook = x.playbooks.find((p) => p.chosen)?.playbook ?? null;
  const cols = [1, fams.length, reasons.length, inputs.length, 1].map((n) => Math.max(n, 1));
  const rows = Math.max(...cols);
  const W = 1000, rowH = 34, H = Math.max(rows * rowH + 20, 120);
  const X = [20, 200, 400, 640, 860];
  const y = (i: number, n: number) => 10 + (H - 20) * (i + 0.5) / n;
  const pos: Record<string, [number, number]> = { pay: [X[0], H / 2] };
  fams.forEach((f, i) => { pos["f:" + f] = [X[1], y(i, fams.length)]; });
  reasons.forEach((r, i) => { pos["r:" + r.code] = [X[2], y(i, reasons.length)]; });
  inputs.forEach((k, i) => { pos["i:" + k] = [X[3], y(i, inputs.length)]; });
  pos.play = [X[4], H / 2];
  const edges: [string, string, boolean][] = [];
  fams.forEach((f) => edges.push(["pay", "f:" + f, x.scores.lit_families.includes(f)]));
  reasons.forEach((r) => {
    edges.push(["f:" + r.family, "r:" + r.code, true]);
    Object.keys(r.inputs).forEach((k) => edges.push(["r:" + r.code, "i:" + k, true]));
    if (playbook) edges.push(["r:" + r.code, "play", r.shown_to_user]);
  });
  const label = (text: string, [cx, cy]: [number, number], strong = false) => (
    <text x={cx + 8} y={cy + 4} fontSize={12} fill={strong ? "var(--ink)" : "var(--ink-2)"} fontWeight={strong ? 600 : 400}>{text}</text>
  );
  return (
    <>
      <div style={{ overflowX: "auto" }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ minWidth: 720 }} role="img" aria-label="Decision graph">
        {edges.map(([a, b, on], i) => {
          const [x1, y1] = pos[a], [x2, y2] = pos[b];
          return <path key={i} d={`M${x1},${y1} C${(x1 + x2) / 2},${y1} ${(x1 + x2) / 2},${y2} ${x2},${y2}`}
                       fill="none" stroke={on ? "var(--accent)" : "var(--line)"} strokeWidth={on ? 1.6 : 1} />;
        })}
        {Object.entries(pos).map(([k, p]) => <circle key={k} cx={p[0]} cy={p[1]} r={5} fill="var(--surface)" stroke="var(--accent)" />)}
        {label(`Payment · ${x.user_view.tier}`, pos.pay, true)}
        {fams.map((f) => label(`${FAMILY_SHORT[f]} ${x.scores.families[f].toFixed(2)}`, pos["f:" + f], x.scores.lit_families.includes(f)))}
        {reasons.map((r) => label(`${r.code.split("_")[0]} ${r.band ?? ""}`, pos["r:" + r.code], r.shown_to_user))}
        {inputs.map((k) => label(k, pos["i:" + k]))}
        {label(playbook ? (PLAYBOOKS[playbook] ?? playbook) : "No playbook", pos.play, !!playbook)}
      </svg>
      </div>
      <p className="muted" style={{ margin: "6px 0 0" }}>Columns: payment → signal families (score) → reasons (push) → inputs → scam playbook. Highlighted lines carry the decision.</p>
    </>
  );
}
