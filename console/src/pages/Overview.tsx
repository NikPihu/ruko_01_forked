import { api, type AlertHealth } from "../api";
import { inr, pct, PLAYBOOKS, userLabel, when } from "../format";
import { reasonText } from "../reasons";
import { BandChip, Card, Check, Empty, Loading, Stat, TierChip, exploreHref, go, useLoad } from "../components/ui";

export function Overview() {
  const { data, error, loading } = useLoad(async () => {
    const [alerts, cases, suspects, verify, health, alertHealth] = await Promise.all([
      api.alerts("T1"), api.cases(), api.suspects("med"), api.verify(), api.health(),
      api.alertHealth().catch(() => null),
    ]);
    return { alerts, cases, suspects, verify, health, alertHealth };
  });
  if (!data) return <Loading error={error} loading={loading} />;

  const interrupted = data.alerts.filter((a) => a.tier !== "T1");
  const paused = interrupted.filter((a) => a.tier === "T3" || a.tier === "T4");
  const held = interrupted.reduce((s, a) => s + a.amount_inr, 0);
  const users = new Set(interrupted.map((a) => a.user_hash)).size;
  const pending = data.suspects.suspects.filter((s) => !s.review.approved);
  const rings = new Set(pending.map((s) => s.ring_id).filter(Boolean)).size;

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Overview</h1>
          <p>Payments RUKO stepped in on, scam rings it found, and whether its evidence log is intact.</p>
        </div>
      </div>

      <div className="grid grid-4">
        <Stat label="Payments interrupted" value={interrupted.length}
          sub={`${paused.length} paused for 30 min or held`} />
        <Stat label="Money at stake in those payments" value={inr(held)} sub={`${users} ${users === 1 ? "person" : "people"}`} />
        <Stat label="Task-scam cases" value={data.cases.length} sub="opened from phones' episode reports" />
        <Stat label="Mule suspects to review" value={pending.length}
          sub={rings ? `in ${rings} ring${rings > 1 ? "s" : ""}` : "none grouped yet"} />
      </div>

      {data.alertHealth && <AlertHealthCard h={data.alertHealth} />}

      <div className="grid grid-main">
        <Card title="Latest interrupted payments" pad={false}
          action={<a href="#/alerts">View all →</a>}>
          {interrupted.length === 0 ? (
            <Empty title="No payments interrupted yet">
              Run <code>scripts\dev.ps1</code>, then pay <code>secure.settlement.desk@okaxis</code> from the app.
            </Empty>
          ) : (
            <div className="table-wrap">
              <table className="list">
                <thead><tr><th>When</th><th>Decision</th><th>Paid to</th><th className="num">Amount</th><th>Main reason</th></tr></thead>
                <tbody>
                  {interrupted.slice(0, 6).map((a) => (
                    <tr key={a.alert_id} className="click" onClick={() => go(`#/case/payment/${a.alert_id}`)}>
                      <td className="muted when">{when(a.ts)}</td>
                      <td><TierChip tier={a.tier} /></td>
                      <td><span className="mono">{a.payee}</span><div className="muted">{userLabel(a.user_hash)}</div></td>
                      <td className="num">{inr(a.amount_inr)}</td>
                      <td>{reasonText(a.reasons[0] ?? "")}
                        {a.playbook && <div className="muted">{PLAYBOOKS[a.playbook] ?? a.playbook}</div>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <div className="stack">
          <Card title="Rings to look at" pad={false} action={<a href="#/suspects">Review →</a>}>
            {pending.length === 0 ? <Empty title="No suspects waiting" /> : (
              <ul className="reasons" style={{ padding: "14px 20px" }}>
                {pending.slice(0, 4).map((s) => (
                  <li key={s.upi_id} style={{ gridTemplateColumns: "1fr auto" }}>
                    <span><a className="mono" href={exploreHref(s.upi_id)}>{s.upi_id}</a>
                      <div className="muted">{s.why.charAt(0).toUpperCase() + s.why.slice(1)}</div></span>
                    <BandChip band={s.band} />
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card title="Evidence log">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <Check ok={data.verify.ok} label={data.verify.ok ? "Chain intact" : "Chain broken"} />
              <span className="muted">{data.verify.rows_checked} records checked</span>
            </div>
            <p className="muted" style={{ margin: "10px 0 0" }}>
              Every decision is hash-chained, so a changed record breaks the chain. Records can back a 1930 complaint
              or a dispute.
            </p>
          </Card>
          <Card title="Engine">
            <div className="ink2">
              Scorer <code>{data.health.model_version}</code> · policy <code>{data.health.policy_version}</code><br />
              Contract <code>{data.health.contract_version}</code>
              {data.health.demo_clock && <> · demo clock on</>}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

const ACTION_TEXT: Record<string, string> = {
  tip_seen: "saw a tip", slid_to_pay: "slid to pay", cancelled_from_alert: "cancelled", waited: "waited out the pause",
  pay_after_pause: "paid after the pause", called_trusted: "called a trusted person", messaged_trusted: "messaged a trusted person",
  called_1930: "called 1930", i_know_them: "said \"I know this person\"",
};

/** How people respond to alerts (aggregates only): the alert-fatigue check. */
function AlertHealthCard({ h }: { h: AlertHealth }) {
  const tiers = ["T1", "T2", "T3", "T4"].filter((t) => h.tiers[t]?.shown);
  const actions = Object.entries(h.actions).sort((a, b) => b[1] - a[1]);
  return (
    <Card title="Alert health" action={<a href="#/transactions">All transactions →</a>}>
      <div className="grid grid-4">
        <Stat label="Payment checks" value={h.checks} sub="recorded this run" />
        <Stat label="Interruptions per 1,000 checks" value={h.interruptions_per_1000_checks ?? "—"} sub="T2 or higher" />
        {tiers.slice(0, 2).map((t) => (
          <Stat key={t} label={`${t} alerts shown`} value={h.tiers[t].shown}
            sub={`${pct(h.tiers[t].cancelled_share)} cancelled · ${pct(h.tiers[t].completed_share)} paid`} />
        ))}
      </div>
      <p className="ink2" style={{ margin: "12px 0 0" }}>
        {actions.length ? <>On alerts, people {actions.map(([a, n]) => `${ACTION_TEXT[a] ?? a} (${n})`).join(", ")}.</> : "No alert feedback from phones yet."}
        {(h.i_know_them.accepted || h.i_know_them.refused) ? <> "I know this person": {h.i_know_them.accepted ?? 0} accepted, {h.i_know_them.refused ?? 0} refused (someone may control the phone, the payee looks like a mule, or it is on a list).</> : null}
      </p>
    </Card>
  );
}
