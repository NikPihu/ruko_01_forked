import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { api, type Payment, type Story } from "../api";
import { FlowDiagram } from "../components/FlowDiagram";
import { Card, Empty, Loading, TierChip, exploreHref, go, useLoad } from "../components/ui";
import { PAYMENT_STATUS, inr, shortId, userLabel, when } from "../format";

const DEMO_MULE = "secure.settlement.desk@okaxis";

function yesNo(v: unknown, yes: string, no: string, unknown: string) {
  if (v === true) return <b className="error">{yes}</b>;
  if (v === false) return <span>{no}</span>;
  return <span className="muted">{unknown}</span>;
}

function Verdict({ story }: { story: Story }) {
  const s = story.signals as Record<string, unknown>;
  if (story.center_role === "unknown") return null;
  const ring = story.loop.found === true || s.crowd === true;
  return ring ? (
    <div className="callout">
      <b>Looks like part of a scam ring.</b>{" "}
      {story.loop.found ? "Money from this ring flows back to the account that paid the “rewards”."
        : "Many RUKO users are linked to it through the same “rewards” account."}
    </div>
  ) : (
    <div className="callout info"><b>No ring signals yet.</b> RUKO keeps watching as more payments come in.</div>
  );
}

function Signals({ story }: { story: Story }) {
  const s = story.signals as Record<string, number | boolean | null>;
  const rows: [string, ReactNode][] = [
    ["Money loop back to a “rewards” account", yesNo(s.money_loop, "Yes", "No", "Can't see: bank doesn't share")],
    ["Many RUKO users linked to it (crowd signal)", yesNo(s.crowd, "Yes", "No", "—")],
    ["RUKO users who paid it in the last 6 hours", <span className="num">{String(s.payee_fanin_ruko_6h ?? 0)}</span>],
    ["Users it sent “rewards” to (last 7 days)", <span className="num">{String(s.bait_sender_fanout_7d ?? 0)}</span>],
    ["Users whose task-scam episode includes it", <span className="num">{String(s.payee_in_episodes_7d ?? 0)}</span>],
    ["Sends money to a known cash-out account", yesNo(s.forwards_to_known_cashout, "Yes", "No", "—")],
  ];
  return (
    <table className="list">
      <tbody>
        {rows.map(([k, v]) => <tr key={k}><td className="ink2">{k}</td><td style={{ textAlign: "right" }}>{v}</td></tr>)}
      </tbody>
    </table>
  );
}

function Decision({ p }: { p: Payment }) {
  if (p.tier) return <TierChip tier={p.tier} />;
  return <span className="muted">{p.checked ? "No answer in time (payment allowed)" : "Not checked"}</span>;
}

/** Payments into the account, each with its payment id, RUKO's decision and what the user did. */
function Payments({ upi, highlight }: { upi: string; highlight: string }) {
  const list = useLoad(() => api.payments(upi), [upi]);
  if (!list.data) return <Loading error={list.error} loading={list.loading} />;
  const d = list.data;
  if (!d.total) return <Empty title="No payments to this account seen by RUKO" />;
  return (
    <>
      <p className="ink2" style={{ margin: "0 20px 12px" }}>
        {d.total} payment{d.total === 1 ? "" : "s"} checked · {d.by_status.completed} paid ({inr(d.completed_inr)}) · {d.by_status.cancelled}{" "}
        cancelled · {d.by_status.checked} not reported yet
      </p>
      <div className="table-wrap">
        <table className="list">
          <thead><tr><th>Payment ID</th><th>When</th><th>From</th><th>Amount</th><th>RUKO decided</th><th>User</th></tr></thead>
          <tbody>
            {d.payments.map((p) => {
              const open = p.evidence_id && p.tier && p.tier !== "T0" ? `#/case/payment/${p.evidence_id}` : null;
              return (
                <tr key={p.payment_id} className={open ? "click" : undefined} onClick={open ? () => go(open) : undefined}
                  style={p.payment_id === highlight ? { background: "var(--surface-2)" } : undefined}>
                  <td className="mono" title={p.payment_id}>{shortId(p.payment_id)}</td>
                  <td className="when">{when(p.outcome_ts ?? p.ts)}</td>
                  <td>{userLabel(p.user)}</td>
                  <td className="num">{inr(p.inr)}</td>
                  <td><Decision p={p} /></td>
                  <td>{PAYMENT_STATUS[p.status] ?? p.status}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

function FoundPayment({ id }: { id: string }) {
  const p = useLoad(() => api.payment(id), [id]);
  if (!p.data) return p.loading || p.error ? <Loading error={p.error} loading={p.loading} /> : null;
  const x = p.data;
  return (
    <div className="callout info">
      <b>Payment <span className="mono">{x.payment_id}</span></b>: {inr(x.inr)} from {userLabel(x.user)} to{" "}
      <span className="mono">{x.payee}</span>, checked {when(x.ts)}. RUKO decided <Decision p={x} />.{" "}
      User: <b>{PAYMENT_STATUS[x.status] ?? x.status}</b>{x.outcome_ts ? ` (${when(x.outcome_ts)})` : ""}.
    </div>
  );
}

export function Explore({ upi, payment = "" }: { upi: string; payment?: string }) {
  const [q, setQ] = useState(upi);
  const [notFound, setNotFound] = useState<string | null>(null);
  useEffect(() => setQ(payment || upi), [upi, payment]);
  const picks = useLoad(async () => {
    const [cases, suspects] = await Promise.all([api.cases(), api.suspects("med")]);
    const s = new Set<string>([DEMO_MULE]);
    cases.forEach((c) => c.accounts.forEach((a) => s.add(a)));
    suspects.suspects.slice(0, 3).forEach((x) => s.add(x.upi_id));
    return [...s].slice(0, 6);
  });
  const story = useLoad(() => (upi ? api.story(upi) : Promise.resolve(null)), [upi]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const v = q.trim();
    setNotFound(null);
    if (!v) return;
    if (v.includes("@")) return go(exploreHref(v.toLowerCase()));
    // No "@": a payment id. Open the account it was paid to, with that payment highlighted.
    const p = await api.payment(v).catch(() => null);
    if (p) go(exploreHref(p.payee, p.payment_id));
    else setNotFound(v);
  };

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Account explorer</h1>
          <p>Look up any UPI ID to see, in one picture, who sent it money, who it paid, and whether money comes back
            to the account that paid the “rewards”. Or paste a payment ID from the app to trace one payment.
            Built only from what RUKO itself sees.</p>
        </div>
      </div>

      <form className="card card-pad row" onSubmit={submit}>
        <input className="input" style={{ flex: "1 1 280px" }} placeholder="UPI ID (secure.settlement.desk@okaxis) or payment ID"
          value={q} onChange={(e) => setQ(e.target.value)} aria-label="UPI ID or payment ID" />
        <button className="btn primary" type="submit">Show money flow</button>
        {notFound && <div className="error" style={{ flexBasis: "100%" }}>
          No payment with ID <span className="mono">{notFound}</span> in the last 30 days.</div>}
        {picks.data && (
          <div className="row" style={{ flexBasis: "100%" }}>
            <span className="muted">Try:</span>
            {picks.data.map((p) => <a key={p} className="chip mono" href={exploreHref(p)}>{p}</a>)}
          </div>
        )}
      </form>

      {!upi ? <Card><Empty title="Pick an account above" /></Card> :
        !story.data ? <Loading error={story.error} loading={story.loading} /> : (
          <>
            {payment && <FoundPayment id={payment} />}
            <Verdict story={story.data} />
            <div className="grid grid-main">
              <Card title={<h2>What happened, in words</h2>}>
                <ul className="story">{story.data.summary.map((s) => <li key={s}>{s}</li>)}</ul>
              </Card>
              <Card title="Signals" pad={false}><Signals story={story.data} /></Card>
            </div>
            {story.data.center_role !== "unknown" && (
              <Card title={<h2>Money flow around <span className="mono">{story.data.center}</span></h2>}>
                <FlowDiagram story={story.data} onSelect={(u) => go(exploreHref(u))} />
              </Card>
            )}
            <Card title={<h2>Payments into <span className="mono">{story.data.center}</span></h2>} pad={false}>
              <Payments upi={story.data.center} highlight={payment} />
            </Card>
          </>
        )}
    </div>
  );
}
