import { api } from "./api";
import { useLoad, useRoute } from "./components/ui";
import { Alerts } from "./pages/Alerts";
import { EpisodeCaseView, PaymentCase } from "./pages/CaseDetail";
import { Evaluation } from "./pages/Evaluation";
import { Explore } from "./pages/Explore";
import { Overview } from "./pages/Overview";
import { Suspects } from "./pages/Suspects";

const NAV = [
  { key: "", label: "Overview", icon: "M3 13h8V3H3zm10 8h8V11h-8zM3 21h8v-6H3zm10-18v6h8V3z" },
  { key: "alerts", label: "Alerts & cases", icon: "M12 2 1 21h22zm0 5 7.5 12h-15zm-1 4v4h2v-4zm0 5v2h2v-2z" },
  { key: "suspects", label: "Mule suspects", icon: "M12 12a5 5 0 1 0 0-10 5 5 0 0 0 0 10zm0 2c-4 0-8 2-8 5v3h16v-3c0-3-4-5-8-5z" },
  { key: "explore", label: "Account explorer", icon: "M10 2a8 8 0 1 0 4.9 14.3l5.4 5.4 1.4-1.4-5.4-5.4A8 8 0 0 0 10 2zm0 2a6 6 0 1 1 0 12 6 6 0 0 1 0-12z" },
  { key: "evaluation", label: "Evaluation", icon: "M4 20h16v2H4zM5 10h3v8H5zm5-6h3v14h-3zm5 9h3v5h-3z" },
];

function Icon({ d }: { d: string }) {
  return <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden><path d={d} fill="currentColor" /></svg>;
}

export function App() {
  const { path, query } = useRoute();
  const section = path[0] ?? "";
  const counts = useLoad(async () => {
    const [alerts, suspects] = await Promise.all([api.alerts("T2"), api.suspects("med")]);
    return { alerts: alerts.length, suspects: suspects.suspects.filter((s) => !s.review.approved).length };
  }, [section]);

  let page;
  if (section === "alerts") page = <Alerts tab={path[1] ?? ""} />;
  else if (section === "case" && path[1] === "payment") page = <PaymentCase id={path[2] ?? ""} />;
  else if (section === "case" && path[1] === "episode") page = <EpisodeCaseView id={path[2] ?? ""} />;
  else if (section === "suspects") page = <Suspects />;
  else if (section === "explore") page = <Explore upi={query.get("upi") ?? ""} />;
  else if (section === "evaluation") page = <Evaluation />;
  else page = <Overview />;

  const active = section === "case" ? "alerts" : section;
  return (
    <div className="shell">
      <aside className="side">
        <div className="brand">
          <div className="brand-mark">
            <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden><path d="M12 2 4 5.5v6c0 5 3.4 9.4 8 10.5 4.6-1.1 8-5.5 8-10.5v-6z" fill="#fff" /></svg>
          </div>
          <div><b>RUKO</b><small>Analyst console</small></div>
        </div>
        <nav className="nav">
          {NAV.map((n) => (
            <a key={n.key} href={`#/${n.key}`} className={active === n.key ? "on" : ""}>
              <Icon d={n.icon} />{n.label}
              {n.key === "alerts" && counts.data ? <span className="count">{counts.data.alerts}</span> : null}
              {n.key === "suspects" && counts.data ? <span className="count">{counts.data.suspects}</span> : null}
            </a>
          ))}
        </nav>
        <div className="side-foot">Synthetic data · users shown without identities</div>
      </aside>
      <main className="main">{page}</main>
    </div>
  );
}
