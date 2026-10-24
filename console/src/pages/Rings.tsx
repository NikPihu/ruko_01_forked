import { api, type Ring } from "../api";
import { inr } from "../format";
import { BandChip, Card, Empty, Loading, Stat, exploreHref, go, useLoad } from "../components/ui";

/** Mule rings found in the payment graph: members, hubs, victims, money and speed. */
export function Rings() {
  const { data, error, loading } = useLoad(() => api.rings());
  if (!data) return <Loading error={error} loading={loading} />;
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Scam rings</h1>
          <p>Groups of accounts linked by money and by the people they took it from. Discovery starts from
            accounts with hard evidence (on a fraud list, flagged in a task scam, or the payee of a payment RUKO
            stopped) and follows the money from there. Open a ring to see, step by step, why each account is in it.
            Nothing here blocks a payment until two analysts approve a suspect.</p>
        </div>
      </div>
      {data.rings.length === 0 ? <Empty title="No rings yet">Rings appear once RUKO stops a payment to a mule-like account, or a listed or
          flagged account is linked to others. Overview → Run scenario adds demo payments.</Empty> : (
        <Card pad={false}>
          <div className="table-wrap">
            <table className="list">
              <thead><tr><th>Ring</th><th className="num">Accounts</th><th className="num">Victims</th><th className="num">Money from victims</th><th>Summary</th><th>Found from</th></tr></thead>
              <tbody>
                {data.rings.map((r) => (
                  <tr key={r.ring_id} className="click" onClick={() => go(`#/rings/${r.ring_id}`)}>
                    <td><b>Ring {r.ring_id.replace(/^ring_/, "")}</b>{r.automated && <div><span className="chip t3">Bot-scale</span></div>}</td>
                    <td className="num">{r.size}</td>
                    <td className="num">{r.victims}</td>
                    <td className="num">{inr(r.money_from_victims_inr)}</td>
                    <td>{r.summary}</td>
                    <td>{r.explanation.started_from.map((s) => (
                      <div key={s.upi_id}><span className="mono">{s.upi_id}</span><div className="muted">{s.why}</div></div>))}</td>
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

export function RingDetail({ id }: { id: string }) {
  const { data, error, loading } = useLoad(() => api.rings(), [id]);
  if (!data) return <Loading error={error} loading={loading} />;
  const r = data.rings.find((x) => x.ring_id === id);
  if (!r) return <Empty title="Ring not found">Ring ids change when the graph changes. <a href="#/rings">Back to rings</a></Empty>;
  return (
    <div className="stack">
      <a href="#/rings">← Scam rings</a>
      <div className="page-head">
        <div>
          <h1>Ring {r.ring_id.replace(/^ring_/, "")}{r.automated && <span className="chip t3" style={{ marginLeft: 8 }}>Bot-scale</span>}</h1>
          <p>{r.summary}</p>
        </div>
      </div>
      <div className="grid grid-4">
        <Stat label="Accounts" value={r.size} sub={`${r.hubs.length} hub${r.hubs.length === 1 ? "" : "s"}`} />
        <Stat label="RUKO users who paid in" value={r.victims} sub={r.baited_users ? `${r.baited_users} got "rewards"` : "—"} />
        <Stat label="Money from victims" value={inr(r.money_from_victims_inr)} />
        <Stat label="Fastest money out" value={r.fastest_hold_min != null ? `${Math.round(r.fastest_hold_min)} min` : "—"} sub="median hold, from bank flows" />
      </div>
      <Card title="Why this is a ring">
        <ol className="story">
          {r.explanation.steps.map((s, i) => <li key={i}>{s}</li>)}
        </ol>
      </Card>
      <Card title="How the ring is linked"><RingGraph r={r} /></Card>
      <Card title="Accounts" pad={false}>
        <div className="table-wrap">
          <table className="list">
            <thead><tr><th>Account</th><th>Role</th><th className="num">Hub score</th><th className="num">Payers</th><th className="num">Money in / out</th><th>Why</th></tr></thead>
            <tbody>
              {r.accounts.map((a) => (
                <tr key={a.upi_id}>
                  <td><a className="mono" href={exploreHref(a.upi_id)}>{a.upi_id}</a>
                    <div className="row" style={{ marginTop: 4 }}>
                      {a.is_hub && <span className="chip">Hub</span>}
                      {a.automated && <span className="chip t3" title={a.automation_why ?? ""}>Bot-scale</span>}
                      {a.registry_listed && <span className="chip">Reported</span>}
                      {a.approved && <span className="chip good">Approved</span>}
                    </div></td>
                  <td>{a.role === "seed" ? "Seed" : <BandChip band={a.band ?? "low"} />}</td>
                  <td className="num">{a.hub_score.toFixed(2)}<div className="muted" style={{ fontSize: 11 }}>
                    {Object.entries(a.hub_parts).map(([k, v]) => `${k.replace("_", " ")} ${v.toFixed(1)}`).join(" · ")}</div></td>
                  <td className="num">{a.payers}</td>
                  <td className="num">{inr(a.inr_in)} / {inr(a.inr_out)}</td>
                  <td>{a.role === "seed" ? <>Started here: {a.why}</> : a.linked_by ? <>Tied in: {a.linked_by}</> : a.why ?? "—"}
                    {a.automation_why && <div className="muted">{a.automation_why}</div>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

/** Ring members on a circle; lines are money between them; the number by each is how many RUKO users paid it. */
function RingGraph({ r }: { r: Ring }) {
  const W = 760, H = 380, cx = W / 2, cy = H / 2, R = Math.min(W, H) / 2 - 70;
  const pos: Record<string, [number, number]> = {};
  r.accounts.forEach((a, i) => {
    const t = (2 * Math.PI * i) / r.accounts.length - Math.PI / 2;
    pos[a.upi_id] = [cx + R * Math.cos(t), cy + R * Math.sin(t)];
  });
  const maxInr = Math.max(1, ...r.links.map((l) => l.inr));
  return (
    <div style={{ overflowX: "auto" }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ minWidth: 600 }} role="img" aria-label="Ring graph">
        {r.links.filter((l) => pos[l.from] && pos[l.to]).map((l, i) => {
          const [x1, y1] = pos[l.from], [x2, y2] = pos[l.to];
          return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--accent)" strokeOpacity={0.7}
                       strokeWidth={1 + 4 * (l.inr / maxInr)}><title>{`${l.from} → ${l.to}: ${inr(l.inr)}`}</title></line>;
        })}
        {r.accounts.map((a) => {
          const [x, y] = pos[a.upi_id];
          const v = r.victims_per_account[a.upi_id] ?? 0;
          return (
            <g key={a.upi_id}>
              <circle cx={x} cy={y} r={a.is_hub ? 14 : 9} fill={a.role === "seed" ? "var(--critical)" : "var(--surface)"}
                      stroke={a.automated ? "var(--critical)" : "var(--accent)"} strokeWidth={a.automated ? 3 : 1.5} />
              <text x={x} y={y + (y < cy ? -20 : 28)} textAnchor="middle" fontSize={11} fill="var(--ink)">{a.upi_id}</text>
              {v > 0 && <text x={x} y={y + (y < cy ? -34 : 42)} textAnchor="middle" fontSize={10} fill="var(--ink-2)">{v} user{v === 1 ? "" : "s"} paid</text>}
            </g>
          );
        })}
      </svg>
      <p className="muted" style={{ margin: "6px 0 0" }}>Filled = where discovery started (listed, flagged or stopped by RUKO). Large = hub. Thick red outline = bot-scale. Line width = money moved between members.</p>
    </div>
  );
}
