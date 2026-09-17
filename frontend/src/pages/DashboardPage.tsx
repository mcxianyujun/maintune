import { EmptyState, MascotScene } from "../assets/theme/ThemeArt";
import type { ConsoleState } from "../useConsole";
import { statusKeys } from "../components";
import { useI18n } from "../i18n";

const systemNames: Record<string,string> = { database:"Database", github_app:"GitHub App", webhook:"Webhook", model:"Model", agent_runtime:"Agent Runtime", sandbox:"Sandbox", smtp:"SMTP", automation:"Automation" };
export function DashboardPage({ c }: { c: ConsoleState }) {
  const { t, date, locale } = useI18n();
  const { page, setPage, dashboard, tasks, window, setWindow } = c;
  if (page !== "概览") return null;
  const usage = dashboard?.tokens[window];
  const maxModel = Math.max(1, ...Object.values(usage?.models || {}));
  const systems = Object.entries(dashboard?.systems || {});
  const readySystems = systems.filter(([, value]) => ["ready", "healthy", "optional"].includes(value)).length;
  const progress = systems.length ? Math.round((readySystems / systems.length) * 100) : 0;
  const attention = [
    [t("dashboard.owner"), dashboard?.counts.owner_pending || 0, "waiting"],
    [t("dashboard.contributor"), dashboard?.counts.contributor_pending || 0, "waiting"],
    [t("dashboard.failures"), dashboard?.counts.failed || 0, "failed"],
    [t("dashboard.warnings"), dashboard?.configuration_warnings || 0, "warning"],
  ];
  return <div className="operations-dashboard">
    <section className="dashboard-hero">
      <div className="hero-copy">
        <span className="soft-pill">✦ SELF-HOSTED PREVIEW</span>
        <h2>{tasks.length ? t("dashboard.cared") : t("dashboard.start")}</h2>
        <p>{tasks.length ? t("dashboard.summary", { count: tasks.length }) : t("dashboard.emptySummary")}</p>
        <div className="hero-actions"><button className="primary" onClick={()=>c.setWizardOpen(true)}>{t("dashboard.checkSetup")}</button><button onClick={()=>setPage("维护任务")}>{t("dashboard.viewTasks")}</button></div>
        <div className="hero-meta"><span><i className="status-dot success"/>Controller policy</span><span><i className="status-dot success"/>Audit trail</span><span><i className="status-dot success"/>Private by default</span></div>
      </div>
      <MascotScene variant="dashboard" />
    </section>

    <div className="dashboard-primary">
      <section className="setup-progress-card">
        <div className="section-head"><div><p className="eyebrow">QUICK START</p><h2>{t("dashboard.progress")}</h2></div><strong className="progress-number">{progress}%</strong></div>
        <div className="soft-progress" aria-label={t("dashboard.progressAria", { progress })}><span style={{width:`${progress}%`}}/></div>
        <p className="muted">{t("dashboard.readyCount", { ready: readySystems, total: systems.length || 0 })}</p>
        <div className="status-grid">{systems.map(([key,value])=><div className="system-row" key={key}><span className={`status-dot ${value === "ready" || value === "healthy" ? "success" : value === "optional" ? "neutral" : "warning"}`}/><strong>{systemNames[key] || key}</strong><span>{value === "optional" ? t("common.optional") : value === "unconfigured" ? t("common.notConfigured") : value === "waiting" ? t("common.pending") : t("common.ready")}</span></div>)}</div>
      </section>
      <section className="attention soft-panel"><div className="section-head"><div><p className="eyebrow">NEEDS YOU</p><h2>{t("dashboard.attention")}</h2></div><button className="text" onClick={()=>setPage("维护任务")}>{t("dashboard.viewTasks")} →</button></div><div className="attention-grid">{attention.map(([label,count,tone])=><button key={String(label)} onClick={()=>setPage("维护任务")} className={`attention-item ${tone}`}><strong>{Number(count).toLocaleString(locale)}</strong><span>{label}</span></button>)}</div></section>
    </div>

    <div className="dashboard-secondary">
      <section className="recent-tasks"><div className="section-head"><div><p className="eyebrow">RECENT ACTIVITY</p><h2>{t("dashboard.recent")}</h2><p className="muted">{t("dashboard.recentHint")}</p></div><button className="text" onClick={()=>setPage("维护任务")}>{t("dashboard.allTasks")}</button></div><div className="table-wrap"><table><thead><tr><th>{t("dashboard.repoNumber")}</th><th>{t("dashboard.type")}</th><th>{t("common.status")}</th><th>{t("dashboard.duration")}</th><th>{t("dashboard.updated")}</th></tr></thead><tbody>{tasks.slice(0,6).map(task=><tr key={task.id}><td><strong>{task.repository}</strong><small>#{task.number}</small></td><td>{task.kind}</td><td><span className={`badge ${task.status}`}>{statusKeys[task.status] ? t(statusKeys[task.status]) : task.status}</span></td><td>{duration(task.created,task.updated)}</td><td>{date(task.updated)}</td></tr>)}</tbody></table>{!tasks.length&&<EmptyState title={t("dashboard.noTasks")} action={<button onClick={()=>c.setWizardOpen(true)}>{t("dashboard.checkConnection")}</button>}>{t("dashboard.noTasksHint")}</EmptyState>}</div></section>
      <section className="usage-widget soft-panel"><div className="section-head"><div><p className="eyebrow">MODEL USAGE</p><h2>{t("dashboard.usage")}</h2></div><div className="segments">{["24h","7d","30d"].map(item=><button key={item} className={window===item?"active":""} onClick={()=>setWindow(item)}>{item}</button>)}</div></div><strong className="usage-total">{usage?.total.toLocaleString(locale) || "0"}<small> total tokens</small></strong><div className="usage-breakdown"><Metric name="Input" value={usage?.input}/><Metric name="Output" value={usage?.output}/><Metric name="Reasoning" value={usage?.reasoning}/><Metric name="Cached" value={usage?.cached}/></div><div className="model-bars">{Object.entries(usage?.models || {}).map(([name,value])=><div key={name}><span>{name}</span><i><b style={{width:`${Math.max(4,(value/maxModel)*100)}%`}}/></i><strong>{value.toLocaleString(locale)}</strong></div>)}</div>{!Object.keys(usage?.models || {}).length&&<p className="gentle-empty">{t("dashboard.usageEmpty")}</p>}</section>
    </div>
    <div className="dashboard-tertiary">
      <section><div className="section-head"><div><p className="eyebrow">REPOSITORY AUTOMATION</p><h2>{t("dashboard.automation")}</h2></div><button className="text" onClick={()=>setPage("仓库")}>{t("dashboard.configure")}</button></div><div className="automation-grid"><Metric name="Repositories" value={dashboard?.automation.repositories}/><Metric name="Issue workflows" value={dashboard?.automation.issues}/><Metric name="PR review" value={dashboard?.automation.reviews}/><Metric name="Auto merge" value={dashboard?.automation.auto_merge}/></div></section>
      <section><div className="section-head"><div><p className="eyebrow">CONFIGURATION HEALTH</p><h2>{t("dashboard.diagnostics")}</h2></div><button className="text" onClick={()=>c.setWizardOpen(true)}>{t("dashboard.rerunDiagnostics")}</button></div>{dashboard?.diagnostics ? <div className="diagnostic-list">{Object.entries(dashboard.diagnostics.checks).map(([name,result])=><div className="diagnostic-row" key={name}><span className={`status-dot ${result.ok?"success":"failed"}`}/><strong>{name}</strong><span>{result.detail}</span></div>)}</div> : <div className="info">{t("dashboard.noDiagnostics")}</div>}</section>
    </div>
  </div>;
}

function Metric({name,value}:{name:string;value?:number}) { return <div className="metric"><span>{name}</span><strong>{(value || 0).toLocaleString()}</strong></div>; }
function duration(start:number,end:number) { const seconds=Math.max(0,Math.round(end-start)); return seconds<60?`${seconds}s`:`${Math.floor(seconds/60)}m ${seconds%60}s`; }
