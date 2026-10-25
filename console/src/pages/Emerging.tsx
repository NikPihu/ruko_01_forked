import { useState } from "react";
import { api, type EmergingPattern } from "../api";
import { inr, when } from "../format";
import { Card, Empty, Loading, Stat, useLoad } from "../components/ui";

/** New scam workflows RUKO has no name for yet (A4). Analyst view only: never in a payment decision. */
export function Emerging() {
  const [tick, setTick] = useState(0);
  const { data, error, loading } = useLoad(() => api.emerging(), [tick]);
  if (!data) return <Loading error={error} loading={loading} />;
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <div className="eyebrow">Scams with no name yet</div>
          <h1 className="page-title">New patterns<span className="accent">spotted before they have a name.</span></h1>
          <p>Flagged and near-miss payments that match <b>no known scam type</b>, grouped by how they happened.
            A group from several different people that keeps growing is a new scam workflow: name it to draft a
            playbook, or dismiss it. Nothing here changes any payment.</p>
          <ol className="howto">
            <li>Each card groups payments that happened the same way.</li>
            <li>A growing group from several people is likely a new scam.</li>
            <li><b>Name it</b> to draft a playbook, or <b>Dismiss</b>. Nothing here changes a payment.</li>
          </ol>
        </div>
      </div>
      {data.patterns.length === 0 ? (
        <Empty title="No new patterns">Every suspicious payment in the last 7 days matched a known scam type.</Empty>
      ) : data.patterns.map((p) => <PatternCard key={p.pattern_id} p={p} onDone={() => setTick((t) => t + 1)} />)}
    </div>
  );
}

function PatternCard({ p, onDone }: { p: EmergingPattern; onDone: () => void }) {
  const [name, setName] = useState("");
  const [analyst, setAnalyst] = useState(() => sessionStorage.getItem("analyst") ?? "");
  const [draft, setDraft] = useState<string | null>(p.review?.draft ?? null);
  const [busy, setBusy] = useState(false);
  const act = async (action: "name" | "dismiss") => {
    if (!analyst.trim()) return;
    sessionStorage.setItem("analyst", analyst.trim());
    setBusy(true);
    try {
      const r = await api.reviewPattern(p.pattern_id, analyst.trim(), action, name);
      if (action === "name") setDraft(r.draft_playbook);
      else onDone();
    } finally { setBusy(false); }
  };
  return (
    <Card title={<span>{p.review?.status === "named" ? `Named: ${p.review.name}` : "Unnamed scam workflow"}
      {p.growing && <span className="chip t3" style={{ marginLeft: 8 }}>Growing</span>}</span>}>
      <p style={{ marginTop: 0 }}><b>{p.description}</b></p>
      <div className="grid grid-4">
        <Stat label="People" value={p.people} sub={`${p.payees} payee account${p.payees === 1 ? "" : "s"}`} />
        <Stat label="Payments" value={p.payments} sub={Object.entries(p.tiers).map(([t, n]) => `${t}×${n}`).join(" · ")} />
        <Stat label="Money involved" value={inr(p.money_inr)} />
        <Stat label="First seen" value={when(p.first_seen)} sub={`last ${when(p.last_seen)}`} />
      </div>
      <p className="muted">Example payments: {p.examples.map((id, i) => (
        <a key={id} href={`#/transactions/${encodeURIComponent(id)}`} style={{ marginRight: 8 }}>#{i + 1}</a>))}
        <span className="ink2"> (open one to see every signal behind it)</span></p>
      <div className="row">
        <input className="input" placeholder="Your name" value={analyst} onChange={(e) => setAnalyst(e.target.value)} />
        <input className="input" placeholder="Name this scam (e.g. Relative emergency)" value={name} onChange={(e) => setName(e.target.value)} />
        <button className="btn" disabled={busy || !analyst.trim() || !name.trim()} onClick={() => act("name")}>Name it</button>
        <button className="btn" disabled={busy || !analyst.trim()} onClick={() => act("dismiss")}>Dismiss</button>
      </div>
      {draft && (
        <>
          <p className="muted">Draft playbook for the data folder (the data owner checks and adds it):</p>
          <pre className="mono" style={{ whiteSpace: "pre-wrap", fontSize: 12, background: "var(--surface-2)", padding: 12, borderRadius: 8 }}>{draft}</pre>
        </>
      )}
    </Card>
  );
}

