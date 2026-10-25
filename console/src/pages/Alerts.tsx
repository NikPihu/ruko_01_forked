import { useState } from "react";
import { api, type Tier } from "../api";
import { inr, PLAYBOOKS, userLabel, when } from "../format";
import { reasonText } from "../reasons";
import { Card, Empty, Loading, TierChip, go, useLoad } from "../components/ui";

export function Alerts({ tab }: { tab: string }) {
  const [minTier, setMinTier] = useState<Tier>("T2");
  const alerts = useLoad(() => api.alerts(minTier), [minTier]);
  const cases = useLoad(() => api.cases());
  const showCases = tab === "cases";

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <div className="eyebrow">Respond</div>
          <h1 className="page-title">Alerts<span className="accent">payments RUKO stepped in on.</span></h1>
          <p>
            <b>Payment alerts</b> are payments RUKO stepped in on at the moment of paying.{" "}
            <b>Task-scam cases</b> are opened when a phone reports a “rewards, then pay more” episode and RUKO
            confirms a payee is part of it.
          </p>
          <ol className="howto">
            <li>Pick <b>Payment alerts</b> or <b>Task-scam cases</b> below.</li>
            <li>Use <b>Show</b> to add tips (T1) or keep only pauses (T3+).</li>
            <li>Open a row for the full story and what the person did next.</li>
          </ol>
          <div className="tier-key">
            <span><TierChip tier="T1" /> a tip on the PIN screen</span>
            <span><TierChip tier="T2" /> a warning card, slide to pay</span>
            <span><TierChip tier="T3" /> a 30-minute pause</span>
            <span><TierChip tier="T4" /> held for analyst review</span>
          </div>
        </div>
      </div>

      <div className="row">
        <a className={`btn ${!showCases ? "primary" : ""}`} href="#/alerts">
          Payment alerts{alerts.data ? ` (${alerts.data.length})` : ""}
        </a>
        <a className={`btn ${showCases ? "primary" : ""}`} href="#/alerts/cases">
          Task-scam cases{cases.data ? ` (${cases.data.length})` : ""}
        </a>
        {!showCases && (
          <label className="row ink2" style={{ marginLeft: "auto" }}>
            Show
            <select className="input" value={minTier} onChange={(e) => setMinTier(e.target.value as Tier)}>
              <option value="T1">All, including tips (T1+)</option>
              <option value="T2">Warned or stronger (T2+)</option>
              <option value="T3">Paused or held (T3+)</option>
            </select>
          </label>
        )}
      </div>

      {!showCases ? (
        <Card pad={false}>
          {!alerts.data ? <Loading error={alerts.error} loading={alerts.loading} /> :
            alerts.data.length === 0 ? <Empty title="No payment alerts at this level" /> : (
              <div className="table-wrap">
                <table className="list">
                  <thead><tr><th>When</th><th>Decision</th><th>Paid to</th><th className="num">Amount</th><th>Why</th><th>Looks like</th></tr></thead>
                  <tbody>
                    {alerts.data.map((a) => (
                      <tr key={a.alert_id} className="click" onClick={() => go(`#/case/payment/${a.alert_id}`)}>
                        <td className="muted when">{when(a.ts)}<div>{userLabel(a.user_hash)}</div></td>
                        <td><TierChip tier={a.tier} /></td>
                        <td className="mono">{a.payee}</td>
                        <td className="num">{inr(a.amount_inr)}</td>
                        <td>{reasonText(a.reasons[0] ?? "")}
                          {a.reasons.length > 1 && <span className="muted"> +{a.reasons.length - 1} more</span>}</td>
                        <td>{a.playbook ? PLAYBOOKS[a.playbook] ?? a.playbook : <span className="muted">—</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
        </Card>
      ) : (
        <Card pad={false}>
          {!cases.data ? <Loading error={cases.error} loading={cases.loading} /> :
            cases.data.length === 0 ? (
              <Empty title="No task-scam cases yet">Run <code>python -m sim.bait_pump --check</code> to create the demo ring.</Empty>
            ) : (
              <div className="table-wrap">
                <table className="list">
                  <thead><tr><th>Opened</th><th>Accounts involved</th><th>Why</th><th>Money loop</th></tr></thead>
                  <tbody>
                    {[...cases.data].reverse().map((c) => (
                      <tr key={c.case_id} className="click" onClick={() => go(`#/case/episode/${c.case_id}`)}>
                        <td className="muted when">{when(c.opened_at)}<div>{userLabel(c.user_hash)}</div></td>
                        <td>{c.accounts.map((a) => <div key={a} className="mono">{a}</div>)}</td>
                        <td>{c.reasons.map(reasonText).slice(0, 2).map((t) => <div key={t}>{t}</div>)}</td>
                        <td>{c.loop_paths.length ? <b className="error">Yes</b> : <span className="muted">Not seen</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
        </Card>
      )}
    </div>
  );
}
