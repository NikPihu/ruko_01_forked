import { useEffect, useState } from "react";
import { api, type AlertHealth, type Spreading } from "../api";
import { inr, pct, PLAYBOOKS, userLabel, when } from "../format";
import { reasonText } from "../reasons";
import { BandChip, Card, Check, Empty, Loading, Stat, TierChip, exploreHref, go, useLoad } from "../components/ui";

export function Overview() {
  const { data, error, loading } = useLoad(async () => {
    const [alerts, cases, suspects, verify, health, alertHealth, spreading] = await Promise.all([
      api.alerts("T1"), api.cases(), api.suspects("med"), api.verify(), api.health(),
      api.alertHealth().catch(() => null), api.spreading().catch(() => null),
    ]);
    return { alerts, cases, suspects, verify, health, alertHealth, spreading };
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
      {data.spreading && <SpreadingCard s={data.spreading} />}
      <DemoCard />

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
const WATCH_TEXT: Record<string, string> = {
  lure_seen: "scam messages seen", long_unknown_call: "long calls with unknown callers",
  remote_access_on: "screen-sharing apps installed", sideload: "apps from outside the store",
};

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
      <p className="ink2" style={{ margin: "8px 0 0" }}>
        {h.watch && Object.keys(h.watch).length
          ? <>Early warnings from phones before paying: {Object.entries(h.watch).map(([k, n]) => `${WATCH_TEXT[k] ?? k} (${n})`).join(", ")}
              {h.lures?.ai_written ? `; ${h.lures.ai_written} of the scam messages looked AI-written` : ""}.</>
          : "No early warnings from phones yet (they need the \"Early warnings\" switch on the phone)."}
      </p>
    </Card>
  );
}

type DemoState = Awaited<ReturnType<typeof api.demoResults>>;

/** Runs the scripted demo agents (every scam type, honest users, a hidden new scam type) live. */
function DemoCard() {
  const [st, setSt] = useState<DemoState | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.demoResults().then(setSt).catch(() => setSt(null)); }, []);
  useEffect(() => {
    if (!st?.running) return;
    const t = setInterval(() => api.demoResults().then(setSt).catch(() => undefined), 1500);
    return () => clearInterval(t);
  }, [st?.running]);
  const start = async () => {
    setErr(null);
    try {
      const r = await api.demoRun();
      if (!r.started) setErr(r.reason ?? "not started");
      setSt(await api.demoResults());
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };
  const rows = st?.results ?? [];
  return (
    <Card title="Demo scenarios" action={<button className="btn" onClick={start} disabled={!!st?.running}>{st?.running ? "Running…" : "Run demo scenarios"}</button>}>
      <p className="ink2" style={{ marginTop: 0 }}>Scripted people pay through the real API: every known scam type, honest users, and a
        hidden new scam type ("relative emergency") that should appear under Emerging patterns. Afterwards, refresh this page.</p>
      {err && <p className="error">{err}</p>}
      {st?.error && <p className="error">{st.error}</p>}
      {rows.length > 0 && (
        <div className="table-wrap">
          <table className="list">
            <thead><tr><th>Scenario</th><th>RUKO decided</th><th>Scam type</th><th>Expected</th><th></th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.scenario}>
                  <td>{r.scenario.replace(/_/g, " ")}</td>
                  <td>{r.tiers.join(", ")}</td>
                  <td>{r.playbooks.map((b) => PLAYBOOKS[b] ?? b).join(", ") || "none known"}</td>
                  <td className="muted">{r.expect}</td>
                  <td>{r.ok ? <span className="chip good">✓ as expected</span> : <span className="chip t4">✕ check</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

const HANDLE_KIND: Record<string, string> = { upi: "UPI ID", link: "Link", phone: "Call-back number" };

/**
 * Same scam, many phones (c2-0.13): money handles going around in scam messages right now. AI crews
 * reword the message for every victim but must reuse the UPI ID, link or number; RUKO counts how many
 * different people got each one. Links and numbers stay hidden (only their pseudonyms reach RUKO).
 */
function SpreadingCard({ s }: { s: Spreading }) {
  return (
    <Card title="Spreading now" pad={false}>
      <p className="ink2" style={{ margin: "12px 16px 0" }}>
        The same UPI ID, link or call-back number in scam messages on different phones in the last {s.window_minutes} minutes.
        At {s.min_users}+ people, paying it gets the reason "this account is being sent to many people in scam messages" (R13),
        before any registry knows it.
      </p>
      {s.handles.length === 0 ? (
        <div style={{ padding: 16 }}><Empty title="Nothing spreading right now">Handles appear here when two or more phones report the same one.</Empty></div>
      ) : (
        <div className="table-wrap">
          <table className="list">
            <thead><tr><th>What</th><th>Handle</th><th>People</th><th>First seen</th><th>Last seen</th></tr></thead>
            <tbody>
              {s.handles.map((h, i) => (
                <tr key={i}>
                  <td>{HANDLE_KIND[h.kind] ?? h.kind}{h.spreading && <span className="chip bad" style={{ marginLeft: 6 }}>spreading</span>}</td>
                  <td className="mono">{h.value ?? <span className="muted">hidden (pseudonym only)</span>}</td>
                  <td>{h.users}</td>
                  <td>{when(h.first_seen)}</td>
                  <td>{when(h.last_seen)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
