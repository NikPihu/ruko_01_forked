import type { Story, StoryLink, StoryNode } from "../api";
import { inr, inrShort } from "../format";

// Left to right: who sent "rewards" -> the RUKO users (one box) -> who they paid -> where that
// money went next. A link from the right back to the left (drawn underneath) is the money loop.

const W = 1000;
const COLS = [
  { key: "senders", x: 8, w: 210, head: "Sent “rewards”", role: "sender" },
  { key: "users", x: 270, w: 170, head: "RUKO users", role: "users" },
  { key: "payees", x: 492, w: 250, head: "Paid by those users", role: "payee" },
  { key: "cashouts", x: 794, w: 198, head: "Money moved on to", role: "cash" },
] as const;
const TOP = 46;
const NODE_H = 54;
const GAP = 14;

interface Box { id: string; col: number; x: number; y: number; w: number; label: string; sub: string; warn?: string; placeholder?: boolean }

/** Fit a UPI ID into a box of width w (13px text, ~7.4px per character, 22px of padding). */
function fit(upi: string, w: number) {
  const max = Math.floor((w - 22) / 7.4);
  return upi.length > max ? upi.slice(0, max - 1) + "…" : upi;
}

function warnOf(n: StoryNode): string | undefined {
  if (n.marks.listed) return "Reported";
  if (n.marks.flagged) return "Flagged";
  return undefined;
}

export function FlowDiagram({ story, onSelect }: { story: Story; onSelect?: (upi: string) => void }) {
  const cols: Box[][] = [[], [], [], []];
  const add = (c: number, id: string, label: string, sub: string, warn?: string, placeholder = false) =>
    cols[c].push({ id, col: c, x: COLS[c].x, y: 0, w: COLS[c].w, label, sub, warn, placeholder });

  const baitInr = new Map(story.links.filter((l) => l.kind === "bait").map((l) => [l.from, l]));
  story.senders.forEach((s) => {
    const l = baitInr.get(s.id);
    const each = l?.users ? `${inr(l.inr / l.users)} each to ` : "rewards to ";
    add(0, s.id, fit(s.id, COLS[0].w), `${each}${s.users_baited ?? 0} users`, warnOf(s));
  });
  if (!story.senders.length) add(0, "_none_s", "None seen", "no “rewards” linked", undefined, true);

  const u = story.users;
  add(1, "users", `${u.count} RUKO user${u.count === 1 ? "" : "s"}`,
    [u.baited ? `${u.baited} got rewards` : "", u.paid ? `${u.paid} paid on` : ""].filter(Boolean).join(" · ") || "—");

  story.payees.forEach((p) =>
    add(2, p.id, fit(p.id, COLS[2].w), p.users ? `${p.users} users paid ${inrShort(p.inr ?? 0)}` : "no payments seen", warnOf(p)));
  if (!story.payees.length) add(2, "_none_p", "None seen", "no payee linked yet", undefined, true);

  story.cashouts.forEach((c) =>
    add(3, c.id, fit(c.id, COLS[3].w), `${inrShort(c.inr ?? 0)}${c.hold_min != null ? ` · after ~${Math.round(c.hold_min)} min` : ""}`, warnOf(c)));
  if (!story.cashouts.length) {
    const hidden = story.flows_visible === null || story.flows_visible === undefined;
    add(3, "_none_c", hidden ? "Not visible" : "None seen", hidden ? "payee's bank doesn't share" : "no onward payments", undefined, true);
  }

  // Vertical layout: each column centred on the tallest one.
  const tallest = Math.max(...cols.map((c) => c.length));
  const contentH = tallest * NODE_H + (tallest - 1) * GAP;
  cols.forEach((c) => {
    const h = c.length * NODE_H + (c.length - 1) * GAP;
    c.forEach((b, i) => { b.y = TOP + (contentH - h) / 2 + i * (NODE_H + GAP); });
  });
  const byId = new Map<string, Box>();
  cols.flat().forEach((b) => byId.set(b.id, b));

  const forward = story.links.filter((l) => l.kind === "bait" || l.kind === "pay" || l.kind === "forward");
  const back = story.links.filter((l) => l.kind === "loop" || l.kind === "shared");
  const maxInr = Math.max(1, ...forward.map((l) => l.inr || 0));
  const width = (l: StoryLink) => 1.5 + 5 * Math.sqrt((l.inr || 0) / maxInr);
  const bottom = TOP + contentH;
  const H = bottom + (back.length ? 36 + back.length * 26 : 18);

  const center = story.center;
  const roleVar = (c: number) => `var(--role-${COLS[c].role})`;

  return (
    <div className="flow">
      <div style={{ overflowX: "auto" }}>
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Money flow diagram" style={{ minWidth: 720 }}>
          <defs>
            <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="11" markerHeight="11" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" fill="var(--line-strong)" />
            </marker>
            <marker id="arr-loop" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="12" markerHeight="12" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" fill="var(--critical)" />
            </marker>
          </defs>

          {COLS.map((c) => (
            <text key={c.key} className="col-head" x={c.x} y={22}>{c.head}</text>
          ))}

          {forward.map((l, i) => {
            const a = byId.get(l.from), b = byId.get(l.to);
            if (!a || !b) return null;
            const x1 = a.x + a.w, y1 = a.y + NODE_H / 2, x2 = b.x - 2, y2 = b.y + NODE_H / 2;
            const mx = (x1 + x2) / 2;
            const label =
              l.kind === "bait" ? `${l.from} sent ${inr(l.inr)} in “rewards” to ${l.users ?? 0} users`
              : l.kind === "pay" ? `${l.users ?? 0} users paid ${l.to} ${inr(l.inr)} in ${l.n ?? 0} payments`
              : `${l.from} moved ${inr(l.inr)} to ${l.to}`;
            return (
              <path key={`f${i}`} d={`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2 - 6},${y2}`} fill="none"
                stroke="var(--line-strong)" strokeWidth={width(l)} strokeLinecap="round" markerEnd="url(#arr)" opacity={0.9}>
                <title>{label}</title>
              </path>
            );
          })}

          {back.map((l, i) => {
            const a = byId.get(l.from), b = byId.get(l.to);
            if (!a || !b) return null;
            const yb = bottom + 30 + i * 26;
            const x1 = a.x + a.w / 2, x2 = b.x + b.w / 2;
            const y1 = a.y + NODE_H, y2 = b.y + NODE_H + 2;
            const dir = x2 < x1 ? -1 : 1;
            const d = `M${x1},${y1} L${x1},${yb - 10} Q${x1},${yb} ${x1 + 10 * dir},${yb} L${x2 - 10 * dir},${yb} Q${x2},${yb} ${x2},${yb - 10} L${x2},${y2}`;
            const label = l.kind === "loop"
              ? `Money flows back: ${inrShort(l.inr)}${l.hold_min != null ? ` after ~${Math.round(l.hold_min)} min` : ""}`
              : `Same cash-out account as the payee`;
            return (
              <g key={`b${i}`}>
                <path d={d} fill="none" stroke="var(--critical)" strokeWidth={2.5} strokeDasharray="7 5" markerEnd="url(#arr-loop)" />
                <text className="lbl loop" x={(x1 + x2) / 2} y={yb - 7} textAnchor="middle">{label}</text>
              </g>
            );
          })}

          {cols.flat().map((b) => {
            const isCenter = b.id === center;
            const clickable = !b.placeholder && b.id !== "users" && !!onSelect;
            return (
              <g key={b.id} className="node" transform={`translate(${b.x},${b.y})`}
                onClick={clickable ? () => onSelect!(b.id) : undefined}
                style={{ cursor: clickable ? "pointer" : "default" }}>
                <title>{b.placeholder ? b.sub : `${b.id}${clickable ? " — click to follow this account" : ""}`}</title>
                <rect width={b.w} height={NODE_H} rx={9}
                  fill={b.placeholder ? "transparent" : roleVar(b.col)} fillOpacity={b.placeholder ? 0 : 0.12}
                  stroke={b.placeholder ? "var(--line-strong)" : roleVar(b.col)}
                  strokeDasharray={b.placeholder ? "4 4" : undefined} strokeWidth={isCenter ? 3 : 1.5} />
                <rect width={5} height={NODE_H} rx={2} fill={b.placeholder ? "transparent" : roleVar(b.col)} />
                <text x={14} y={22} fontWeight={isCenter ? 700 : 560} className={b.placeholder ? "sub" : undefined}>
                  {b.label}
                </text>
                <text x={14} y={40} className="sub">
                  {b.warn && <tspan fill="var(--critical-ink)" fontWeight={650}>⚠ {b.warn} · </tspan>}
                  {b.sub}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      <div className="legend" style={{ marginTop: 10 }}>
        <span><i style={{ background: "var(--role-sender)" }} /> Sent “rewards” (bait)</span>
        <span><i style={{ background: "var(--role-users)" }} /> RUKO users (anonymous)</span>
        <span><i style={{ background: "var(--role-payee)" }} /> Paid by users</span>
        <span><i style={{ background: "var(--role-cash)" }} /> Money moved on to</span>
        <span><i style={{ background: "var(--critical)" }} /> Money loop (back to the bait account)</span>
        <span className="muted">Thick bold border = the account you looked up. Click an account to follow it.</span>
      </div>
    </div>
  );
}
