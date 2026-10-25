import { api } from "./api";
import { useLoad, useRoute } from "./components/ui";
import { Alerts } from "./pages/Alerts";
import { EpisodeCaseView, PaymentCase } from "./pages/CaseDetail";
import { Explore } from "./pages/Explore";
import { Overview } from "./pages/Overview";
import { Suspects } from "./pages/Suspects";
import { PaymentExplain, Transactions } from "./pages/Transactions";
import { Emerging } from "./pages/Emerging";
import { RingDetail, Rings } from "./pages/Rings";
import { Lab } from "./pages/Lab";
import { Accuracy } from "./pages/Accuracy";

// Short labels for the top bar; each page explains itself in its own header.
const NAV = [
  { key: "", label: "Overview" },
  { key: "alerts", label: "Alerts" },
  { key: "transactions", label: "Payments" },
  { key: "emerging", label: "New patterns" },
  { key: "rings", label: "Rings" },
  { key: "suspects", label: "Suspects" },
  { key: "explore", label: "Explorer" },
  { key: "accuracy", label: "Accuracy" },
  { key: "lab", label: "AI scammer" },
];


export function App() {
  const { path, query } = useRoute();
  const section = path[0] ?? "";
  const counts = useLoad(async () => {
    const [alerts, suspects, health] = await Promise.all([api.alerts("T2"), api.suspects("med"), api.health().catch(() => null)]);
    return { alerts: alerts.length, suspects: suspects.suspects.filter((s) => !s.review.approved).length, health };
  }, [section]);

  let page;
  if (section === "alerts") page = <Alerts tab={path[1] ?? ""} />;
  else if (section === "case" && path[1] === "payment") page = <PaymentCase id={path[2] ?? ""} />;
  else if (section === "case" && path[1] === "episode") page = <EpisodeCaseView id={path[2] ?? ""} />;
  else if (section === "transactions" && path[1]) page = <PaymentExplain id={decodeURIComponent(path[1])} />;
  else if (section === "transactions") page = <Transactions />;
  else if (section === "emerging") page = <Emerging />;
  else if (section === "rings" && path[1]) page = <RingDetail id={path[1]} />;
  else if (section === "rings") page = <Rings />;
  else if (section === "suspects") page = <Suspects />;
  else if (section === "explore") page = <Explore upi={query.get("upi") ?? ""} payment={query.get("payment") ?? ""} />;
  else if (section === "lab") page = <Lab />;
  else if (section === "accuracy") page = <Accuracy />;
  else page = <Overview />;

  const active = section === "case" ? "alerts" : section;
  const h = counts.data?.health;
  return (
    <div className="shell">
      <div className="banner">
        <span className="tag">DEMO</span>
        <span>Synthetic data from the simulator. People appear as pseudonyms, never names.</span>
        {h && <span>Engine {h.model_version} · contract {h.contract_version}{h.demo_clock ? " · demo clock" : ""}</span>}
      </div>
      <header className="side">
        <a className="brand" href="#/">
          <span className="brand-mark" aria-hidden>
            <svg width="20" height="26" viewBox="0 0 20 26"><rect x="1" y="1" width="2.5" height="24" fill="#ede6d8" /><path d="M3.5 2h15l-4 5.5 4 5.5h-15z" fill="#e8673f" /></svg>
          </span>
          <span><b>RUKO</b><small>Analyst console</small></span>
        </a>
        <nav className="nav" aria-label="Pages">
          {NAV.map((n) => (
            <a key={n.key} href={`#/${n.key}`} className={active === n.key ? "on" : ""} aria-current={active === n.key ? "page" : undefined}
              title={n.label}>
              {n.label}
              {n.key === "alerts" && counts.data ? <span className="count" title="Payments interrupted (T2 or higher)">{counts.data.alerts}</span> : null}
              {n.key === "suspects" && counts.data ? <span className="count" title="Suspects waiting for review">{counts.data.suspects}</span> : null}
            </a>
          ))}
        </nav>
        <div className="side-foot"><span className="who">AN</span><span>Analyst</span><span className="badge">Fraud team</span></div>
      </header>
      <main className="main">{page}</main>
    </div>
  );
}
