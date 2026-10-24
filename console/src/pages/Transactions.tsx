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

/** Every payment check RUKO recorded, or the money users received, newest first (the transaction database). */
export function Transactions() {
  const [direction, setDirection] = useState<"sent" | "received">("sent");
  const [minTier, setMinTier] = useState<Tier | "T0">("T0");
  const [status, setStatus] = useState("");
  const { data, error, loading } = useLoad(() => api.transactions({ min_tier: minTier, status, limit: 300 }), [minTier, status]);
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Transactions</h1>
          <p>{direction === "sent"
            ? "Every payment check RUKO made, with its decision and what the user did. Open one to see exactly why."
            : "Money users received, as their phone read it from a bank SMS (only with “Share money I receive” on in the app)."}</p>
        </div>
        <div className="row">
          <select className="input" value={direction} onChange={(e) => setDirection(e.target.value as "sent" | "received")}>
            <option value="sent">Sent (payment checks)</option>
            <option value="received">Received</option>
          </select>
          {direction === "sent" && <>
          <select className="input" value={minTier} onChange={(e) => setMinTier(e.target.value as Tier)}>
            {["T0", "T1", "T2", "T3", "T4"].map((t) => <option key={t} value={t}>{t === "T0" ? "All tiers" : `${t} and above`}</option>)}
          </select>
          <select className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Any outcome</option>
            {Object.entries(PAYMENT_STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          </>}
        </div>
      </div>
      {direction === "received" ? <ReceivedList /> : !data ? <Loading error={error} loading={loading} /> : data.count === 0 ? (
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

/** Money users received (c2-0.11): who sent it, to whom, how much. Not a payment check: no decision. */
function ReceivedList() {
  const { data, error, loading } = useLoad(() => api.received({ limit: 300 }), []);
  if (!data) return <Loading error={error} loading={loading} />;
  if (data.count === 0) {
    return <Empty title="No money received yet">Turn on “Watch my money alerts” and “Share money I receive” in the app, then receive money (a bank SMS alert).</Empty>;
  }
  return (
    <Card pad={false}>
      <div className="table-wrap">
        <table className="list">
          <thead><tr><th>When</th><th>From</th><th>Received by</th><th className="num">Amount</th><th>Source</th></tr></thead>
          <tbody>
            {data.received.map((r) => (
              <tr key={r.event_id}>
                <td>{when(r.ts)}</td>
                <td>{r.sender_name && <div>{r.sender_name}</div>}
                  {r.sender_upi ? <span className="mono">{r.sender_upi}</span> : <span className="muted">no UPI ID in the SMS</span>}</td>
                <td>{userLabel(r.user_hash)}</td>
                <td className="num">{inr(r.amount_inr)}</td>
                <td className="muted">{r.source === "bank_sms" ? "Bank SMS on the phone" : r.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
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

      <WhySummary x={x} />

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

/** The decision in words: lit evidence first, each with its real values, then how the tier was set. */
function WhySummary({ x }: { x: Explanation }) {
  const sm = x.summary;
  const type = sm.scam_type ? (PLAYBOOKS[sm.scam_type] ?? sm.scam_type) : null;
  return (
    <Card title={`Why ${x.user_view.tier}`}>
      <p style={{ margin: "0 0 14px", fontSize: 16 }}><b>{sm.headline}</b></p>
      <EvidenceGraph x={x} />
      <ul className="reasons plain" style={{ marginTop: 14 }}>
        <li>• <b>Scam type:</b> {type ?? "none of the known playbooks matched. If payments like this keep coming, they show up under Emerging patterns."}</li>
        {sm.how.map((t) => <li key={t}>• {t}</li>)}
      </ul>
      <p className="muted" style={{ margin: "10px 0 0" }}>A kind of evidence is lit at 0.50 or more; at least {sm.lit_needed} must be lit to interrupt. Only measured signals are listed: unknown is never shown as safe.</p>
    </Card>
  );
}

/**
 * Evidence → kind of evidence → decision, left to right. Facts sit next to their own kind, so no
 * line crosses another; lit kinds feed the decision with a thick red line, unlit ones with a thin
 * dashed grey one.
 */
function EvidenceGraph({ x }: { x: Explanation }) {
  const sm = x.summary;
  const tier = x.user_view.tier;
  const lit = sm.families.filter((f) => f.lit).length;
  const type = sm.scam_type ? (PLAYBOOKS[sm.scam_type] ?? sm.scam_type) : "no known scam type";
  const W = 1000, rowH = 26, groupGap = 18, top = 12;
  const FACT_X = 470, BOX_X = 560, BOX_W = 180, BOX_H = 50, DEC_X = 810, DEC_W = 180;
  const cut = (t: string) => (t.length > 62 ? t.slice(0, 60) + "…" : t);

  let yCursor = top;
  const groups = sm.families.map((f) => {
    const rows = f.facts.length ? f.facts : ["nothing measured points to a scam"];
    const ys = rows.map((_, i) => yCursor + rowH * (i + 0.5));
    const mid = (ys[0] + ys[ys.length - 1]) / 2;
    yCursor += rows.length * rowH + groupGap;
    return { f, rows, ys, mid, empty: !f.facts.length };
  });
  const H = Math.max(yCursor - groupGap + top, 120 + 2 * top);
  const decY = H / 2, decH = 120;
  const curve = (x1: number, y1: number, x2: number, y2: number) =>
    `M${x1},${y1} C${(x1 + x2) / 2},${y1} ${(x1 + x2) / 2},${y2} ${x2},${y2}`;

  return (
    <div style={{ overflowX: "auto" }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ minWidth: 760 }} role="img"
           aria-label={`Evidence for this decision: ${sm.headline}`}>
        {groups.map(({ f, rows, ys, mid, empty }) => {
          const color = f.lit ? "var(--critical)" : "var(--ink-2)";
          const scoreW = Math.round(Math.min(1, f.score) * (BOX_W - 24));
          return (
            <g key={f.family}>
              {rows.map((t, i) => (
                <g key={i} opacity={f.lit ? 1 : 0.55}>
                  <text x={FACT_X - 10} y={ys[i] + 4} fontSize={13} textAnchor="end"
                        fill={empty ? "var(--ink-2)" : "var(--ink)"} fontStyle={empty ? "italic" : "normal"}>
                    <title>{t}</title>{cut(t)}
                  </text>
                  <circle cx={FACT_X} cy={ys[i]} r={3} fill={color} />
                  {!empty && <path d={curve(FACT_X, ys[i], BOX_X, mid)} fill="none" stroke={color}
                                   strokeOpacity={f.lit ? 0.45 : 0.3} strokeWidth={1.2} />}
                </g>
              ))}
              <path d={curve(BOX_X + BOX_W, mid, DEC_X, decY)} fill="none" stroke={f.lit ? "var(--critical)" : "var(--line)"}
                    strokeWidth={f.lit ? 3 : 1.2} strokeDasharray={f.lit ? undefined : "4 4"} />
              <rect x={BOX_X} y={mid - BOX_H / 2} width={BOX_W} height={BOX_H} rx={10}
                    fill="var(--surface)" stroke={f.lit ? "var(--critical)" : "var(--line)"} strokeWidth={f.lit ? 2 : 1} />
              <text x={BOX_X + 12} y={mid - 6} fontSize={13} fontWeight={600} fill="var(--ink)">
                {FAMILY_SHORT[f.family] ?? f.family}
                <tspan fontWeight={400} fill={color}>{`  ${f.score.toFixed(2)} · ${f.lit ? "lit" : "not lit"}`}</tspan>
              </text>
              <rect x={BOX_X + 12} y={mid + 8} width={BOX_W - 24} height={6} rx={3} fill="var(--line)" />
              <rect x={BOX_X + 12} y={mid + 8} width={scoreW} height={6} rx={3} fill={color} />
            </g>
          );
        })}
        <rect x={DEC_X} y={decY - decH / 2} width={DEC_W} height={decH} rx={12}
              fill="var(--surface-2)" stroke={tier === "T0" ? "var(--line)" : "var(--critical)"} strokeWidth={2} />
        <text x={DEC_X + 14} y={decY - 30} fontSize={22} fontWeight={700} fill="var(--ink)">{tier}</text>
        <text x={DEC_X + 14} y={decY - 8} fontSize={13} fontWeight={600} fill="var(--ink)">{TIERS[tier]?.name}</text>
        <text x={DEC_X + 14} y={decY + 14} fontSize={12} fill="var(--ink)">{lit} of 4 lit · {sm.lit_needed} needed</text>
        <text x={DEC_X + 14} y={decY + 34} fontSize={12} fill="var(--ink-2)"><title>{type}</title>{type.length > 24 ? type.slice(0, 23) + "…" : type}</text>
      </svg>
    </div>
  );
}
