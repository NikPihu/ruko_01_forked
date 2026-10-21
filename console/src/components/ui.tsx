import { useCallback, useEffect, useState, type ReactNode } from "react";
import { TIERS } from "../format";
import type { Tier } from "../api";

/** Hash routes: #/alerts, #/case/payment/e_123, #/explore?upi=x@ybl ... */
export function useRoute(): { path: string[]; query: URLSearchParams } {
  const read = () => {
    const raw = window.location.hash.replace(/^#\/?/, "");
    const [p, q = ""] = raw.split("?");
    return { path: p.split("/").filter(Boolean).map(decodeURIComponent), query: new URLSearchParams(q) };
  };
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const on = () => setRoute(read());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

export function go(hash: string) {
  window.location.hash = hash;
}

export function exploreHref(upi: string) {
  return `#/explore?upi=${encodeURIComponent(upi)}`;
}

/** Load once, reload on demand; errors are shown, never thrown. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const load = useCallback(() => {
    setLoading(true);
    fn()
      .then((d) => { setData(d); setError(null); })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(load, [load]);
  return { data, error, loading, reload: load };
}

export function TierChip({ tier }: { tier: Tier | string }) {
  const t = TIERS[tier];
  return (
    <span className={`chip ${tier.toLowerCase()}`} title={t?.action}>
      <span className="dot" aria-hidden />
      {tier} · {t?.name ?? tier}
    </span>
  );
}

export function BandChip({ band }: { band: string }) {
  const map: Record<string, string> = { high: "t4", med: "t3", low: "t1" };
  const word: Record<string, string> = { high: "High suspicion", med: "Medium suspicion", low: "Low suspicion" };
  return (
    <span className={`chip ${map[band] ?? ""}`}>
      <span className="dot" aria-hidden />
      {word[band] ?? band}
    </span>
  );
}

export function Card({ title, action, children, pad = true }: {
  title?: ReactNode; action?: ReactNode; children: ReactNode; pad?: boolean;
}) {
  return (
    <section className="card">
      {(title || action) && (
        <div className="card-head">
          {typeof title === "string" ? <h2>{title}</h2> : title}
          {action}
        </div>
      )}
      {pad ? <div className="card-pad">{children}</div> : children}
    </section>
  );
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="card stat">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <b>{title}</b>
      {children}
    </div>
  );
}

export function Loading({ error, loading }: { error: string | null; loading: boolean }) {
  if (error) {
    return (
      <Empty title="Can't reach the RUKO engine">
        <span className="error">{error}</span>
        <div className="muted" style={{ marginTop: 6 }}>Start it with <code>scripts\dev.ps1</code> and refresh.</div>
      </Empty>
    );
  }
  return loading ? <Empty title="Loading…" /> : null;
}

export function Check({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={`chip ${ok ? "good" : "bad"}`}>
      <span aria-hidden>{ok ? "✓" : "✕"}</span>
      {label}
    </span>
  );
}
