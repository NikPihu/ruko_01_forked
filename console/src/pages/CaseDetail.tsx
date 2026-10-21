import { api, type Alert, type EpisodeCase, type Story } from "../api";
import { inr, PLAYBOOKS, STAGES, TIERS, userLabel, when } from "../format";
import { reasonFamily, reasonText } from "../reasons";
import { FlowDiagram } from "../components/FlowDiagram";
import { Card, Check, Empty, Loading, TierChip, exploreHref, go, useLoad } from "../components/ui";

const FAMILY: Record<string, string> = { C: "Context (phone)", P: "Payee", B: "Behaviour", L: "Lure" };

function Reasons({ codes }: { codes: string[] }) {
  if (!codes.length) return <span className="muted">No reasons recorded.</span>;
  return (
    <ul className="reasons">
      {codes.map((c) => (
        <li key={c}><span className="fam">{reasonFamily(c)}</span><span>{reasonText(c)}</span></li>
      ))}
    </ul>
  );
}

function Journey({ path }: { path: [string, string][] }) {
  const reached = new Map(path.map(([s, ts]) => [s, ts]));
  return (
    <ol className="timeline">
      {["S1", "S2", "S3", "S4", "S5"].map((s) => (
        <li key={s} className={reached.has(s) ? "done" : ""}>
          <div className="bar" />
          <div className="st">{STAGES[s]}</div>
          <div className="muted">{reached.has(s) ? when(reached.get(s)) : "not seen"}</div>
        </li>
      ))}
    </ol>
  );
}

function MoneyAround({ story }: { story: Story | null }) {
  if (!story) return null;
  return (
    <Card title="Money around this account" action={<a href={exploreHref(story.center)}>Open in explorer →</a>}>
      <ul className="story" style={{ marginBottom: 16 }}>
        {story.summary.map((s) => <li key={s}>{s}</li>)}
      </ul>
      <FlowDiagram story={story} onSelect={(upi) => go(exploreHref(upi))} />
    </Card>
  );
}

function Evidence({ id }: { id: string | null }) {
  const v = useLoad(() => api.verify());
  return (
    <Card title="Evidence">
      {id ? <div>Record <code>{id}</code></div> : <div className="muted">No record (tier T0)</div>}
      <div className="row" style={{ marginTop: 10 }}>
        {v.data && <Check ok={v.data.ok} label={v.data.ok ? "Hash chain intact" : `Chain broken at ${v.data.first_bad_id}`} />}
        <button className="btn" onClick={v.reload}>Re-check</button>
      </div>
      <p className="muted" style={{ margin: "10px 0 0" }}>
        Tamper-evident: each record includes the hash of the one before it.
      </p>
    </Card>
  );
}

export function PaymentCase({ id }: { id: string }) {
  const { data, error, loading } = useLoad(async () => {
    const all = await api.alerts("T1");
    const alert = all.find((a) => a.alert_id === id) ?? null;
    const story = alert ? await api.story(alert.payee) : null;
    return { alert, story };
  }, [id]);
  if (!data) return <Loading error={error} loading={loading} />;
  if (!data.alert) return <Empty title="Alert not found">It may have been cleared by a demo reset. <a href="#/alerts">Back to alerts</a></Empty>;
  const a: Alert = data.alert;

  return (
    <div className="stack">
      <a href="#/alerts">← Alerts</a>
      <div className="page-head">
        <div>
          <div className="row"><TierChip tier={a.tier} />{a.playbook && <span className="chip">{PLAYBOOKS[a.playbook] ?? a.playbook}</span>}</div>
          <h1 style={{ marginTop: 8 }}>{inr(a.amount_inr)} to <span className="mono">{a.payee}</span></h1>
          <p>{userLabel(a.user_hash)} · {when(a.ts)} · UPI ID {a.entry_method === "typed" ? "typed by hand" : `entered by ${a.entry_method}`}</p>
        </div>
      </div>

      <div className="grid grid-main">
        <div className="stack">
          <Card title="What RUKO did">
            <div className="callout">
              <b>{TIERS[a.tier]?.name}.</b> {TIERS[a.tier]?.action}.
            </div>
            <p className="ink2" style={{ margin: "12px 0 0" }}>
              Signal families that agreed: {a.families.length ? a.families.map((f) => FAMILY[f] ?? f).join(", ") : "—"}.
              RUKO only interrupts when at least two independent families agree.
            </p>
          </Card>
          <Card title="Why"><Reasons codes={a.reasons} /></Card>
          <Card title="Scam journey so far"><Journey path={a.stage_path} /></Card>
        </div>
        <Evidence id={a.evidence_id} />
      </div>

      <MoneyAround story={data.story} />
    </div>
  );
}

export function EpisodeCaseView({ id }: { id: string }) {
  const { data, error, loading } = useLoad(async () => {
    const all = await api.cases();
    const c = all.find((x) => x.case_id === id) ?? null;
    let story: Story | null = null;
    if (c) {
      const stories = await Promise.all(c.accounts.map((u) => api.story(u)));
      story = stories.find((s) => s.center_role === "payee") ?? stories[0] ?? null;
    }
    return { c, story };
  }, [id]);
  if (!data) return <Loading error={error} loading={loading} />;
  if (!data.c) return <Empty title="Case not found"><a href="#/alerts/cases">Back to cases</a></Empty>;
  const c: EpisodeCase = data.c;

  return (
    <div className="stack">
      <a href="#/alerts/cases">← Task-scam cases</a>
      <div className="page-head">
        <div>
          <span className="chip t4"><span className="dot" />High risk episode</span>
          <h1 style={{ marginTop: 8 }}>Task-scam case <span className="mono">{c.case_id}</span></h1>
          <p>Reported by {userLabel(c.user_hash)}'s phone · {when(c.opened_at)}</p>
        </div>
      </div>
      <div className="grid grid-main">
        <div className="stack">
          <Card title="Why"><Reasons codes={c.reasons} /></Card>
          <Card title="Accounts involved">
            {c.accounts.map((u) => <div key={u}><a className="mono" href={exploreHref(u)}>{u}</a></div>)}
            {c.loop_paths.length > 0 && (
              <div className="callout" style={{ marginTop: 12 }}>
                <b>Money loop:</b> <span className="mono">{c.loop_paths[0]}</span>
              </div>
            )}
          </Card>
        </div>
        <Evidence id={c.evidence_id} />
      </div>
      <MoneyAround story={data.story} />
    </div>
  );
}
