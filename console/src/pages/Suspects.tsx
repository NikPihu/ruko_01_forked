import { useState } from "react";
import { api, type Suspect } from "../api";
import { when } from "../format";
import { BandChip, Card, Empty, Loading, exploreHref, useLoad } from "../components/ui";

const NAME_KEY = "ruko.reviewer";

function readName() {
  try { return localStorage.getItem(NAME_KEY) ?? ""; } catch { return ""; }
}

export function Suspects() {
  const [band, setBand] = useState("med");
  const [name, setName] = useState(readName);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const { data, error, loading, reload } = useLoad(() => api.suspects(band), [band]);

  const saveName = (v: string) => {
    setName(v);
    try { localStorage.setItem(NAME_KEY, v); } catch { /* private window: keep in memory */ }
  };

  const review = async (s: Suspect, decision: "approve" | "reject") => {
    setBusy(s.upi_id);
    setMsg(null);
    try {
      const r = await api.review(s.upi_id, name.trim(), decision);
      setMsg(r.approved ? `${s.upi_id} is approved: live payment checks now treat it as a confirmed suspect.`
        : `Recorded your ${decision === "approve" ? "approval" : "rejection"} of ${s.upi_id}.`);
      reload();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const groups = new Map<string, Suspect[]>();
  (data?.suspects ?? []).forEach((s) => {
    const k = s.ring_id ?? "_single";
    groups.set(k, [...(groups.get(k) ?? []), s]);
  });
  const needed = data?.approvals_needed ?? 2;

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Mule suspects</h1>
          <p>
            Accounts that RUKO's payment graph links to known scam accounts, often before anyone has reported them.
            A suspect only affects live payment checks after <b>{needed} different analysts approve it</b>.
          </p>
        </div>
      </div>

      <div className="card card-pad row" style={{ justifyContent: "space-between" }}>
        <label className="row ink2">
          Reviewing as
          <input className="input" placeholder="Your name" value={name} onChange={(e) => saveName(e.target.value)} />
        </label>
        <label className="row ink2">
          Show
          <select className="input" value={band} onChange={(e) => setBand(e.target.value)}>
            <option value="med">Medium and high suspicion</option>
            <option value="high">High only</option>
            <option value="low">Everything</option>
          </select>
        </label>
        <button className="btn" onClick={reload}>Re-run discovery</button>
      </div>

      {msg && <div className="callout info">{msg}</div>}
      {!data ? <Loading error={error} loading={loading} /> :
        data.suspects.length === 0 ? (
          <Card><Empty title="No suspects at this level">Suspects appear once phones report task-scam episodes (try <code>python -m sim.bait_pump</code>).</Empty></Card>
        ) : (
          [...groups.entries()].map(([ring, list]) => (
            <Card key={ring} pad={false}
              title={<h2>{ring === "_single" ? "Not linked to a ring" : `Ring ${ring.replace(/^ring_/, "")}`}
                <span className="muted" style={{ fontWeight: 400 }}> · {list.length} account{list.length > 1 ? "s" : ""}</span></h2>}>
              <div className="table-wrap">
                <table className="list">
                  <thead><tr><th>Account</th><th>Why RUKO suspects it</th><th>Registry</th><th>Approvals</th><th></th></tr></thead>
                  <tbody>
                    {list.map((s) => {
                      const mine = name.trim() && (s.review.approved_by.includes(name.trim()) || s.review.rejected_by.includes(name.trim()));
                      return (
                        <tr key={s.upi_id}>
                          <td>
                            <a className="mono" href={exploreHref(s.upi_id)}>{s.upi_id}</a>
                            <div className="row" style={{ marginTop: 6 }}>
                              <BandChip band={s.band} />
                              {s.is_hub && <span className="chip">Cash-out hub</span>}
                            </div>
                          </td>
                          <td>{s.why.charAt(0).toUpperCase() + s.why.slice(1)}<div className="muted">first seen {when(s.first_seen)}</div></td>
                          <td className="when">{s.registry_listed ? <span className="ink2">Reported</span>
                            : <b>Not yet</b>}</td>
                          <td>
                            {s.review.approved ? <span className="chip good">✓ Approved</span>
                              : <span className="ink2">{s.review.approved_by.length} of {needed}</span>}
                            {(s.review.approved_by.length > 0 || s.review.rejected_by.length > 0) && (
                              <div className="muted">
                                {s.review.approved_by.length > 0 && <>✓ {s.review.approved_by.join(", ")} </>}
                                {s.review.rejected_by.length > 0 && <>✕ {s.review.rejected_by.join(", ")}</>}
                              </div>
                            )}
                          </td>
                          <td>
                            <div className="row" style={{ flexWrap: "nowrap" }}>
                              <button className="btn good" disabled={!name.trim() || !!mine || busy === s.upi_id}
                                title={!name.trim() ? "Enter your name first" : mine ? "You already reviewed this one" : ""}
                                onClick={() => review(s, "approve")}>Approve</button>
                              <button className="btn bad" disabled={!name.trim() || !!mine || busy === s.upi_id}
                                onClick={() => review(s, "reject")}>Reject</button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Card>
          ))
        )}
    </div>
  );
}
