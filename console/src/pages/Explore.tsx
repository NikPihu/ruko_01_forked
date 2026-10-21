import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { api, type Story } from "../api";
import { FlowDiagram } from "../components/FlowDiagram";
import { Card, Empty, Loading, exploreHref, go, useLoad } from "../components/ui";

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

export function Explore({ upi }: { upi: string }) {
  const [q, setQ] = useState(upi);
  useEffect(() => setQ(upi), [upi]);
  const picks = useLoad(async () => {
    const [cases, suspects] = await Promise.all([api.cases(), api.suspects("med")]);
    const s = new Set<string>([DEMO_MULE]);
    cases.forEach((c) => c.accounts.forEach((a) => s.add(a)));
    suspects.suspects.slice(0, 3).forEach((x) => s.add(x.upi_id));
    return [...s].slice(0, 6);
  });
  const story = useLoad(() => (upi ? api.story(upi) : Promise.resolve(null)), [upi]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (q.trim()) go(exploreHref(q.trim().toLowerCase()));
  };

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Account explorer</h1>
          <p>Look up any UPI ID to see, in one picture, who sent it money, who it paid, and whether money comes back
            to the account that paid the “rewards”. Built only from what RUKO itself sees.</p>
        </div>
      </div>

      <form className="card card-pad row" onSubmit={submit}>
        <input className="input" style={{ flex: "1 1 280px" }} placeholder="UPI ID, e.g. secure.settlement.desk@okaxis"
          value={q} onChange={(e) => setQ(e.target.value)} aria-label="UPI ID" />
        <button className="btn primary" type="submit">Show money flow</button>
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
          </>
        )}
    </div>
  );
}
