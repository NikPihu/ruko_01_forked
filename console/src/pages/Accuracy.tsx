import { api, type Accuracy as Acc, type AccuracyScorer } from "../api";
import { inr, PLAYBOOKS } from "../format";
import { Card, Empty, Loading, Stat, useLoad } from "../components/ui";

const pct = (x: number | null | undefined, d = 1) => (x == null ? "—" : `${(100 * x).toFixed(d)}%`);
const num = (x: number) => x.toLocaleString("en-IN");
const LANG: Record<string, string> = { en: "English", hi: "Hindi", hinglish: "Hinglish" };
const MSG_TYPE: Record<string, string> = {
  arrest_threat: "Arrest threat", kyc: "KYC", task_job: "Task / job", trading_tip: "Trading tip",
  refund: "Refund", other_scam: "Other scam", normal: "Normal message",
};

/** What RUKO gets right and wrong, measured on data it never trained on. Read-only; nothing live. */
export function Accuracy() {
  const { data, error, loading } = useLoad(() => api.accuracy());
  if (data === null && !loading && !error) {
    return <Empty title="No accuracy results yet">Run <code>python -m evalsuite.accuracy</code> (see its header).</Empty>;
  }
  if (!data) return <Loading error={error} loading={loading} />;
  const p = data.payments;
  const live = p.scorers[p.live_scorer];
  const rules = p.scorers[p.rules_scorer];
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <div className="eyebrow">Measured, not claimed</div>
          <h1 className="page-title">Accuracy<span className="accent">on data RUKO never trained on.</span></h1>
          <p>Measured on data RUKO never trained on: a held-out simulated world for payments, held-out message
            templates for the phone's scam-message check, and 50 new scams the red team wrote to beat it. False
            alarms and misses are shown next to the catches, and the weak spots are named.</p>
          <ol className="howto">
            <li>Catches are shown next to false alarms and misses.</li>
            <li>The failure cases name RUKO's weak spots.</li>
            <li>The simulated world is easier than real fraud: read the numbers with that in mind.</li>
          </ol>
        </div>
      </div>

      <Card title={`Payments: ${p.world}`}>
        <div className="grid grid-4">
          <Stat label="Scam payments interrupted" value={pct(live.scam_caught_rate)} sub={`rules alone: ${pct(rules?.scam_caught_rate)}`} />
          <Stat label="Scam money interrupted" value={pct(live.scam_rupees_caught_rate)} />
          <Stat label="False alarms" value={`${live.false_alarms_per_1000} / 1,000`}
            sub={`honest payments interrupted (rules: ${rules?.false_alarms_per_1000 ?? "—"})`} />
          <Stat label="Gentle tips on honest payments" value={`${live.legit_tips_per_1000} / 1,000`} sub="T1: a line of text, no stop" />
        </div>
        <h3 style={{ margin: "18px 0 8px" }}>Confusion table ({p.live_scorer}, through the real policy)</h3>
        <Confusion s={live} />
        <p className="muted" style={{ margin: "8px 0 0" }}>
          {num(p.rows)} payments replayed ({num(p.scam_payments)} scam). Honest payments were sampled 1 in 4 and weighted back,
          so their counts are estimates. "Interrupted" means a warning or a pause (T2 or higher).
        </p>
      </Card>

      <div className="grid grid-2">
        <Card title="By scam type (payments interrupted)" pad={false}>
          <table className="list">
            <thead><tr><th>Scam type</th><th className="num">{p.live_scorer}</th><th className="num">{p.rules_scorer}</th></tr></thead>
            <tbody>
              {Object.entries(live.by_scam_type).sort((a, b) => a[1] - b[1]).map(([k, v]) => (
                <tr key={k}><td>{PLAYBOOKS[k] ?? k}</td><td className="num">{pct(v, 0)}</td>
                  <td className="num">{pct(rules?.by_scam_type[k], 0)}</td></tr>
              ))}
            </tbody>
          </table>
        </Card>
        <Card title="Scams it missed, and what they had in common" pad={false}>
          {live.missed_by_type.length === 0 ? <Empty title="No misses on this world" /> : (
            <div className="table-wrap">
              <table className="list">
                <thead><tr><th>Scam type</th><th className="num">Missed</th><th className="num">Median</th><th>Most of them…</th></tr></thead>
                <tbody>
                  {live.missed_by_type.map((g) => (
                    <tr key={g.scam_type}>
                      <td>{PLAYBOOKS[g.scam_type] ?? g.scam_type}</td>
                      <td className="num">{g.missed} of {g.of}</td>
                      <td className="num">{g.median_inr != null ? inr(g.median_inr) : "—"}</td>
                      <td className="muted">{traits(g).join("; ") || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      <Messages m={data.messages} />
      <NewScams n={data.new_scams} />

      <Card title="Where RUKO is weak (named failure cases)">
        <div className="stack">
          {data.failure_cases.map((c) => (
            <div key={c.name} className="callout">
              <b>{c.name}</b>
              <div style={{ marginTop: 4 }}><span className="muted">Measured:</span> {c.measured}</div>
              <div><span className="muted">Why:</span> {c.why}</div>
              <div><span className="muted">What we do about it:</span> {c.fix}</div>
            </div>
          ))}
        </div>
      </Card>
      <p className="muted">Built {new Date(data.built_at).toLocaleString()} with <code>{data.command}</code>.</p>
    </div>
  );
}

function traits(g: AccuracyScorer["missed_by_type"][number]): string[] {
  const out: string[] = [];
  if ((g.no_scam_message ?? 0) >= 0.5) out.push("no scam message seen");
  if ((g.no_call_during_payment ?? 0) >= 0.5) out.push("no call during the payment");
  if ((g.payee_older_than_90d ?? 0) >= 0.5) out.push("payee account older than 90 days");
  if ((g.under_2000_inr ?? 0) >= 0.5) out.push("under ₹2,000");
  return out;
}

function Confusion({ s }: { s: AccuracyScorer }) {
  const c = s.confusion;
  const cell = (n: number, good: boolean, label: string) => (
    <td className="num" style={{ background: good ? "var(--surface-2)" : undefined }}>
      <b style={{ fontSize: 18 }}>{num(n)}</b><div className="muted" style={{ fontSize: 12 }}>{label}</div>
    </td>
  );
  return (
    <div className="table-wrap">
      <table className="list" style={{ minWidth: 0 }}>
        <thead><tr><th></th><th className="num">RUKO interrupted</th><th className="num">RUKO let it through</th></tr></thead>
        <tbody>
          <tr><td><b>Scam payment</b></td>{cell(c.scam_interrupted, true, "caught")}{cell(c.scam_missed, false, "missed")}</tr>
          <tr><td><b>Honest payment</b></td>{cell(c.legit_interrupted, false, "false alarm")}{cell(c.legit_not_interrupted, true, "left alone")}</tr>
        </tbody>
      </table>
    </div>
  );
}

function Messages({ m }: { m: Acc["messages"] }) {
  return (
    <Card title={`Scam messages, checked on the phone (${m.model}, ${num(m.messages)} ${m.held_out})`}>
      <div className="grid grid-4">
        <Stat label="Scam messages caught" value={pct(m.scam_caught)} sub={`right scam type ${pct(m.scam_right_type)}`} />
        <Stat label="Scam messages missed" value={pct(m.scam_called_normal)} sub={`plus ${pct(m.scam_unclear)} 'unclear'`} />
        <Stat label="Normal messages flagged" value={pct(m.normal_false_alarm)} sub="false alarms (a message alone never interrupts a payment)" />
        <Stat label="Normal messages 'unclear'" value={pct(m.normal_unclear)} />
      </div>
      <div className="grid grid-2" style={{ marginTop: 16 }}>
        <table className="list">
          <thead><tr><th>Language</th><th className="num">Messages</th><th className="num">Scams caught</th><th className="num">Normal flagged</th></tr></thead>
          <tbody>
            {Object.entries(m.by_language).map(([k, v]) => (
              <tr key={k}><td>{LANG[k] ?? k}</td><td className="num">{num(v.messages)}</td>
                <td className="num">{pct(v.scam_caught, 0)}</td><td className="num">{pct(v.normal_false_alarm)}</td></tr>
            ))}
          </tbody>
        </table>
        <table className="list">
          <thead><tr><th>Message type</th><th className="num">F1</th></tr></thead>
          <tbody>
            {Object.entries(m.per_type_f1).sort((a, b) => a[1] - b[1]).map(([k, v]) => (
              <tr key={k}><td>{MSG_TYPE[k] ?? k}</td><td className="num">{v.toFixed(2)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function NewScams({ n }: { n: Acc["new_scams"] }) {
  return (
    <Card title="New scams: the red team's attacks">
      <p style={{ marginTop: 0 }}>{n.source}. These are scams RUKO has no playbook for, written to slip past it. They show
        what an attacker who knows RUKO can do, and feed the blue team, which turns the complaints they cause into new
        playbooks that two analysts approve.</p>
      <div className="grid grid-4">
        <Stat label="New scams" value={n.playbooks} sub={`${num(n.scam_payments)} scam payments`} />
        <Stat label="Missed" value={pct(n.missed, 0)} sub={`rules alone: ${pct(n.rules_missed, 0)}`} />
        {Object.entries(n.by_shape).map(([k, v]) => (
          <Stat key={k} label={k} value={pct(v.missed, 0)} sub={`missed, ${v.playbooks} scams`} />
        ))}
      </div>
      <ul className="reasons plain" style={{ marginTop: 14 }}>
        {n.examples.map((e) => <li key={e.name}><b>{pct(e.missed, 0)} missed</b> · {e.title}</li>)}
      </ul>
    </Card>
  );
}
