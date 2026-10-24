import { useEffect, useState } from "react";
import { api, type LabLatest, type LabPresets, type LabSent, type LabStatus, type LabWorkflow } from "../api";
import { inr, PLAYBOOKS, when } from "../format";
import { Card, Check, Empty, Loading, TierChip, useLoad } from "../components/ui";

/** Scam lab: the judge plays the AI scammer from here; the victim uses Cache Pay on the emulator.
 * The lab only delivers messages and calls to the emulator (adb). RUKO decides on the phone's
 * signals as always; this page then shows, from the scammer's side, whether the scam worked. */
export function Lab() {
  const status = useLoad(() => api.labStatus(), []);
  if (status.data === null) return <Loading error={status.error} loading={status.loading} />;
  if (status.data === false) {
    return (
      <div className="stack">
        <Head />
        <Empty title="The scam lab is off">
          Start the engine with <code>--lab</code> (<code>scripts\dev.ps1</code> does this) on the laptop that runs the
          Android emulator, then refresh.
        </Empty>
      </div>
    );
  }
  return <LabOn status={status.data} />;
}

function Head() {
  return (
    <div className="page-head">
      <div>
        <h1>AI scammer</h1>
        <p>You are the scammer. Your victim is on the emulator using <b>Cache Pay</b>. Send messages, ring the phone,
          or run a ready-made scam, then tell the victim who to pay. Messages land in the emulator's Messages app and
          calls really ring. RUKO never sees what you write: only what the phone measures.</p>
      </div>
    </div>
  );
}

function LabOn({ status }: { status: LabStatus }) {
  const [workflow, setWorkflow] = useState<string | undefined>(undefined);
  const [tick, setTick] = useState(0);
  const flows = useLoad(() => api.labWorkflows(), []);
  const presets = useLoad(() => api.labPresets(), []);
  const bump = () => setTick((t) => t + 1);
  const reset = async () => {
    await api.labReset();
    setWorkflow(undefined);
    bump();
  };
  return (
    <div className="stack">
      <Head />
      <Card>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div className="row">
            <Check ok={!!status.emulator} label={status.emulator ? `Emulator ${status.emulator}` : "No emulator found"} />
            <span className="chip">Victim: {status.victim}</span>
            {!status.adb && <span className="muted">adb not found: install the Android SDK platform-tools</span>}
          </div>
          <button className="btn" onClick={reset}>Reset everything</button>
        </div>
        {flows.data && (
          <p className="muted" style={{ margin: "10px 0 0" }}>
            On the phone, switch on in Cache Pay's settings: {flows.data.app_switches.join(" · ")}.
          </p>
        )}
      </Card>

      <div className="grid grid-main">
        <div className="stack">
          <Card title="Ready-made scams">
            {!flows.data ? <Loading error={flows.error} loading={flows.loading} /> : (
              <div className="stack">
                {flows.data.workflows.map((f) => (
                  <FlowCard key={f.id} f={f} active={workflow === f.id} onPick={() => setWorkflow(f.id)} onSent={bump} />
                ))}
              </div>
            )}
          </Card>
          {presets.data && <Composer presets={presets.data} onSent={bump} />}
        </div>
        <div className="stack">
          <Result workflow={workflow} />
          <SentLog tick={tick} />
        </div>
      </div>
    </div>
  );
}

function useAction() {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const run = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      setMsg({ ok: true, text: label });
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally { setBusy(false); }
  };
  return { busy, msg, run };
}

function Note({ msg }: { msg: { ok: boolean; text: string } | null }) {
  if (!msg) return null;
  return <span className={msg.ok ? "muted" : "error"}>{msg.text}</span>;
}

function FlowCard({ f, active, onPick, onSent }: { f: LabWorkflow; active: boolean; onPick: () => void; onSent: () => void }) {
  const { busy, msg, run } = useAction();
  return (
    <section className="card" style={{ borderColor: active ? "var(--accent)" : undefined }}>
      <div className="card-pad">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <b>{f.title}</b>
          <span className={`chip ${f.flagged ? "bad" : "good"}`}>{f.flagged ? "RUKO should step in" : "RUKO should stay quiet"}</span>
        </div>
        <p style={{ margin: "8px 0" }}>{f.story}</p>
        {f.sms && (
          <div className="callout info" style={{ marginBottom: 8 }}>
            <div className="muted">Message from {f.sms.from}{f.call ? `, then a call from ${f.call}` : ""}</div>
            {f.sms.text}
          </div>
        )}
        <ol className="story">
          {f.victim_steps.map((s) => <li key={s}>{s}</li>)}
        </ol>
        <p className="muted" style={{ margin: "8px 0" }}>Expected: {f.expect}</p>
        <div className="row">
          {f.prepare && (
            <button className="btn" disabled={busy} title={f.prepare}
              onClick={() => run("Set up done: " + f.prepare, async () => { onPick(); await api.labPrepare(f.id); onSent(); })}>
              1. Set up
            </button>
          )}
          <button className="btn primary" disabled={busy}
            onClick={() => run(f.call ? "Message sent and the phone is ringing" : "Message sent",
              async () => { onPick(); await api.labSend(f.id); onSent(); })}>
            {f.prepare ? "2. " : ""}Send to the victim
          </button>
          {f.call && (
            <>
              <button className="btn" disabled={busy} onClick={() => run("Call answered", () => api.labCall(f.call!, "answer"))}>Answer call</button>
              <button className="btn" disabled={busy} onClick={() => run("Call ended", () => api.labCall(f.call!, "hangup"))}>Hang up</button>
            </>
          )}
          <Note msg={msg} />
        </div>
        {f.prepare && <p className="muted" style={{ margin: "8px 0 0" }}>Set up: {f.prepare}</p>}
      </div>
    </section>
  );
}

function Composer({ presets, onSent }: { presets: LabPresets; onSent: () => void }) {
  const [from, setFrom] = useState(presets.numbers.unknown[0] ?? "");
  const [text, setText] = useState("");
  const [number, setNumber] = useState(presets.numbers.unknown[0] ?? "");
  const sms = useAction();
  const call = useAction();
  const numbers = [
    ...presets.numbers.unknown.map((n) => ({ label: `${n} (unknown)`, value: n })),
    ...presets.numbers.contacts.map((c) => ({ label: `${c.mobile} (${c.name}, saved contact)`, value: c.mobile })),
  ];
  return (
    <Card title="Write your own">
      <div className="stack">
        <div className="row">
          <label className="muted" htmlFor="lab-from">From</label>
          <input id="lab-from" className="input" list="lab-numbers" value={from} onChange={(e) => setFrom(e.target.value)} />
          <select className="input" value="" onChange={(e) => e.target.value && setText(e.target.value)} aria-label="Pick a test message">
            <option value="">Pick a test message…</option>
            <optgroup label="AI-written scam messages (synthetic test set)">
              {presets.scam.map((p, i) => <option key={i} value={p.text}>[{p.tag}, {p.lang}] {p.text.slice(0, 70)}</option>)}
            </optgroup>
            <optgroup label="Everyday messages">
              {presets.everyday.map((p, i) => <option key={i} value={p.text}>[{p.lang}] {p.text.slice(0, 70)}</option>)}
            </optgroup>
          </select>
        </div>
        <datalist id="lab-numbers">{numbers.map((n) => <option key={n.value} value={n.value}>{n.label}</option>)}</datalist>
        <textarea className="input" rows={3} maxLength={480} placeholder="Type a message (up to 480 characters)"
          value={text} onChange={(e) => setText(e.target.value)} />
        <div className="row">
          <button className="btn primary" disabled={sms.busy || !text.trim() || !from.trim()}
            onClick={() => sms.run("Message sent", async () => { await api.labSms(from, text); onSent(); })}>Send message</button>
          <span className="muted">{text.length}/480</span>
          <Note msg={sms.msg} />
        </div>
        <div className="row" style={{ borderTop: "1px solid var(--line)", paddingTop: 12 }}>
          <label className="muted" htmlFor="lab-call">Call from</label>
          <input id="lab-call" className="input" list="lab-numbers" value={number} onChange={(e) => setNumber(e.target.value)} />
          {(["ring", "answer", "hangup"] as const).map((a) => (
            <button key={a} className="btn" disabled={call.busy || !number.trim()}
              onClick={() => call.run(a === "ring" ? "Ringing" : a === "answer" ? "Answered" : "Hung up",
                async () => { await api.labCall(number, a); onSent(); })}>
              {a === "ring" ? "Ring" : a === "answer" ? "Answer" : "Hang up"}
            </button>
          ))}
          <Note msg={call.msg} />
        </div>
      </div>
    </Card>
  );
}

const RESULT_CHIP: Record<string, string> = {
  stopped: "good", interrupted: "good", paid_anyway: "bad", paid: "bad", not_flagged: "", cancelled: "",
};

function Result({ workflow }: { workflow?: string }) {
  const [r, setR] = useState<LabLatest | null>(null);
  useEffect(() => {
    let live = true;
    const load = () => api.labLatest(workflow).then((x) => { if (live) setR(x); }).catch(() => undefined);
    load();
    const t = setInterval(load, 2000);
    return () => { live = false; clearInterval(t); };
  }, [workflow]);
  const p = r?.payment;
  return (
    <Card title="Did your scam work?">
      {!p ? (
        <Empty title="Waiting for the victim to pay">When the victim taps Pay in Cache Pay, RUKO's decision shows here.</Empty>
      ) : (
        <div className="stack">
          <div>
            <span className={`chip ${RESULT_CHIP[r!.result ?? ""] ?? ""}`} style={{ fontSize: 14 }}>{r!.words}</span>
          </div>
          <div className="row">
            <TierChip tier={p.tier} />
            <span className="mono">{p.payee_upi}</span>
            <b>{inr(p.amount_inr)}</b>
            <span className="muted">{when(p.ts)}</span>
          </div>
          {p.playbook && <div>Looks like: <b>{PLAYBOOKS[p.playbook] ?? p.playbook}</b></div>}
          <div className="muted">{r!.headline}</div>
          {r!.reasons && r!.reasons.length > 0 && (
            <ul className="reasons plain">
              {r!.reasons.map((x) => <li key={x.code}>{x.text}</li>)}
            </ul>
          )}
          {r!.expected && (
            <Check ok={r!.expected.met && r!.expected.same_payee}
              label={!r!.expected.same_payee ? "Paid someone other than this scam asked for"
                : r!.expected.met ? "As expected for this scam" : `Not as expected: ${r!.expected.words}`} />
          )}
          <a href={`#/transactions/${encodeURIComponent(p.payment_id)}`}>Open why (analyst view) →</a>
        </div>
      )}
    </Card>
  );
}

function SentLog({ tick }: { tick: number }) {
  const { data } = useLoad(() => api.labSent(), [tick]);
  const rows: LabSent[] = data?.sent ?? [];
  return (
    <Card title="What you sent" pad={false}>
      {rows.length === 0 ? <Empty title="Nothing sent yet" /> : (
        <ul className="reasons plain" style={{ padding: "14px 20px" }}>
          {rows.slice(0, 12).map((s, i) => (
            <li key={i}>
              <span className="muted">{when(s.ts)} · </span>
              {s.kind === "sms" ? `Message from ${s.from} (${s.chars} characters)`
                : s.kind === "call" ? `Call ${s.action} ${s.number}` : `Set up: ${s.workflow}`}
              {s.workflow && s.kind !== "prepare" ? <span className="muted"> · {s.workflow}</span> : null}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
