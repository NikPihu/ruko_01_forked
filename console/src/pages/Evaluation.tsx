import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { inr, pct } from "../format";
import { Card, Empty, Loading, Stat, useLoad } from "../components/ui";

interface Row { name: string; value: number; detail: string }

const SETUP = { A: "Today's systems", B: "+ Phone episode", C: "+ Episode + payment graph" } as const;

function BarsChart({ rows, label }: { rows: Row[]; label: string }) {
  return (
    <div style={{ width: "100%", height: 44 + rows.length * 52 }}>
      <ResponsiveContainer>
        <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 56, bottom: 4, left: 8 }} barCategoryGap={14}>
          <CartesianGrid horizontal={false} stroke="var(--line)" />
          <XAxis type="number" domain={[0, 1]} tickFormatter={(v: number) => pct(v)} stroke="var(--line-strong)"
            tick={{ fill: "var(--muted)", fontSize: 12 }} tickLine={false} />
          <YAxis type="category" dataKey="name" width={190} stroke="var(--line-strong)"
            tick={{ fill: "var(--ink-2)", fontSize: 13 }} tickLine={false} />
          <Tooltip cursor={{ fill: "var(--surface-2)" }}
            contentStyle={{ background: "var(--surface)", border: "1px solid var(--line)", borderRadius: 8, color: "var(--ink)" }}
            formatter={(v: number, _n, item) => [`${pct(v)} · ${(item.payload as Row).detail}`, label]} />
          <Bar dataKey="value" fill="var(--accent)" radius={[0, 4, 4, 0]} maxBarSize={26} isAnimationActive={false}>
            <LabelList dataKey="value" position="right" formatter={(v: number) => pct(v)}
              style={{ fill: "var(--ink)", fontSize: 13, fontWeight: 600 }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function Evaluation() {
  const { data, error, loading } = useLoad(() => api.evaluation());
  if (!data) return <Loading error={error} loading={loading} />;
  const ep = data.episode, gr = data.graph;
  const ai = data.ai_lures;
  if (!ep && !gr && !ai) {
    return <Card><Empty title="No evaluation results yet">Run <code>python -m eval.episode_eval</code> and <code>python -m eval.graph_eval</code>.</Empty></Card>;
  }

  const fresh = ep?.conditions.fresh_mules;
  const known = ep?.conditions.known_mules;
  const taskRows: Row[] = fresh ? (["A", "B", "C"] as const).map((k) => ({
    name: SETUP[k],
    value: fresh[k].share_inr_interrupted,
    detail: `${fresh[k].journeys_alerted}/${fresh[k].journeys} journeys alerted`,
  })) : [];
  const vis = gr?.visibility;
  const visName = { none: "No bank shares data", partner: "Partner banks share", dpip: "All banks share (DPIP)" } as const;
  const graphRows: Row[] = vis ? (["none", "partner", "dpip"] as const).map((k) => ({
    name: visName[k], value: vis[k].share_of_mules_flagged_before_registry,
    detail: `${vis[k].mules_flagged} mules flagged`,
  })) : [];

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Evaluation</h1>
          <p>How much more scam money RUKO stops than today's systems, measured on the synthetic world. Small sample:
            treat these as early indications, not proof.</p>
        </div>
      </div>

      {ai && (
        <Card title="AI-written scam messages: does the phone's lure model catch them?">
          <p className="ink2" style={{ marginTop: 0 }}>
            {ai.scam_messages} polished, personalised scam messages written the way AI writes them, in phrasings the
            model never saw (English, Hindi, Hinglish), plus {ai.honest_messages} honest look-alikes (real OTPs,
            bank and RBI notices, refunds). Scored exactly as the phone does. Small hand-written set: an early check.
          </p>
          <div className="grid grid-4">
            <Stat label="Scam messages caught" value={pct(ai.caught)} sub={`unseen templates before: ${pct(ai.baseline_caught_unseen_templates)}`} />
            <Stat label="Right scam type" value={pct(ai.right_scam_type)} />
            <Stat label="False alarms on honest messages" value={pct(ai.false_alarms)} />
            <Stat label="By scam type" value={Object.keys(ai.by_scam_type).length}
              sub={Object.entries(ai.by_scam_type).map(([k, v]) => `${k.replace("_", " ")} ${pct(v)}`).join(" · ")} />
          </div>
          {ai.missed.length > 0 && <p className="muted" style={{ marginBottom: 0 }}>Missed: {ai.missed.map((m) => `${m.tag} (${m.lang}): "${m.text}…"`).join(" · ")}</p>}
        </Card>
      )}

      {fresh && known && ep && (
        <>
          <div className="grid grid-4">
            <Stat label="Task-scam money interrupted (fresh mules)" value={pct(fresh.C.share_inr_interrupted)}
              sub={`up from ${pct(fresh.A.share_inr_interrupted)} with today's systems`} />
            <Stat label="First alert lands at payment" value={`#${fresh.C.median_first_alert_payment ?? "—"}`}
              sub={`was #${fresh.A.median_first_alert_payment ?? "—"} (median)`} />
            <Stat label="False interruptions" value={pct(fresh.C.false_interruption_rate, 2)}
              sub={`of normal payments; was ${pct(fresh.A.false_interruption_rate, 2)}`} />
            <Stat label="Known mules" value={pct(known.C.share_inr_interrupted)} sub="caught in every setup" />
          </div>
          <Card title="Task scams paid to brand-new mules: share of scam money interrupted (T2 or stronger)">
            <p className="ink2" style={{ marginTop: 0 }}>
              “Fresh” mules are accounts no list or bank knows yet. Today's systems miss most of them; the phone's
              episode and the payment graph close the gap.
            </p>
            <BarsChart rows={taskRows} label="Interrupted" />
            <table className="list" style={{ marginTop: 8 }}>
              <thead><tr><th>Setup</th><th className="num">Money interrupted</th><th className="num">Journeys alerted</th><th className="num">First alert (median payment #)</th></tr></thead>
              <tbody>
                {(["A", "B", "C"] as const).map((k) => (
                  <tr key={k}><td>{SETUP[k]}</td><td className="num">{pct(fresh[k].share_inr_interrupted)}</td>
                    <td className="num">{fresh[k].journeys_alerted} / {fresh[k].journeys}</td>
                    <td className="num">{fresh[k].median_first_alert_payment ?? "—"}</td></tr>
                ))}
              </tbody>
            </table>
            <p className="muted" style={{ marginBottom: 0 }}>{ep.world.task_journeys} task-scam journeys worth {inr(ep.world.task_inr)} among {ep.world.users.toLocaleString("en-IN")} synthetic users.</p>
          </Card>
        </>
      )}

      {vis && gr && (
        <Card title="Mules found before the fraud registry lists them">
          <p className="ink2" style={{ marginTop: 0 }}>
            The payment graph flags mules from how money moves. How early depends on how much bank data RUKO can see.
          </p>
          <BarsChart rows={graphRows} label="Flagged before listing" />
          <table className="list" style={{ marginTop: 8 }}>
            <thead><tr><th>Bank data RUKO sees</th><th className="num">Flagged before listing</th><th className="num">Head start (median)</th><th className="num">Analyst list precision</th><th className="num">Rings</th></tr></thead>
            <tbody>
              {(["none", "partner", "dpip"] as const).map((k) => (
                <tr key={k}><td>{visName[k]}</td><td className="num">{pct(vis[k].share_of_mules_flagged_before_registry)}</td>
                  <td className="num">{vis[k].median_days_before_listing != null ? `${vis[k].median_days_before_listing} days` : "—"}</td>
                  <td className="num">{pct(vis[k].analyst_list_precision)}</td><td className="num">{vis[k].rings}</td></tr>
              ))}
            </tbody>
          </table>
          <p className="muted" style={{ marginBottom: 0 }}>{gr.world.mules} mules, {gr.world.episode_events} episode reports from {gr.world.users.toLocaleString("en-IN")} synthetic users.</p>
        </Card>
      )}
    </div>
  );
}
