import { createRoot } from "react-dom/client";
import { setCredential } from "./api";
import { Field } from "./components";
import { useConsole } from "./useConsole";
import "./style.css";
import { DashboardPage } from "./pages/DashboardPage";
import { ProvidersPage } from "./pages/ProvidersPage";
import { SettingsPage } from "./pages/SettingsPage";
import { AgentsPage } from "./pages/AgentsPage";
import { PluginsPage } from "./pages/PluginsPage";
import { RunsPage } from "./pages/RunsPage";
import { ProviderDialog } from "./pages/ProviderDialog";
import { AgentDialog } from "./pages/AgentDialog";
import { RunDialog } from "./pages/RunDialog";
import { IntegrationsPage } from "./pages/IntegrationsPage";
import { TasksPage } from "./pages/TasksPage";
import { SetupWizard } from "./pages/SetupWizard";
import { emptyRuntime } from "./types";
import { BrandGlyph, MascotScene, NavMascotIcon, type ThemeIconKind } from "./assets/theme/ThemeArt";
import { I18nProvider, LanguageSwitch, useI18n } from "./i18n";
import type { MessageKey } from "./i18n/resources";
const pages = [
  { id: "概览", label: "nav.overview", description: "nav.desc.overview", icon: "overview" },
  { id: "GitHub", label: "nav.github", description: "nav.desc.github", icon: "github" },
  { id: "仓库", label: "nav.repositories", description: "nav.desc.repositories", icon: "repository" },
  { id: "维护任务", label: "nav.tasks", description: "nav.desc.tasks", icon: "tasks" },
  { id: "模型", label: "nav.providers", description: "nav.desc.providers", icon: "models" },
  { id: "Agents", label: "nav.agents", description: "nav.desc.agents", icon: "agents" },
  { id: "Sandbox", label: "nav.sandbox", description: "nav.desc.sandbox", icon: "sandbox" },
  { id: "扩展", label: "nav.plugins", description: "nav.desc.plugins", icon: "plugins", experimental: true },
  { id: "运行记录", label: "nav.runs", description: "nav.desc.runs", icon: "runs" },
  { id: "系统设置", label: "nav.settings", description: "nav.desc.settings", icon: "settings" },
];
function App() {
  const { t } = useI18n();
  const c = useConsole();
  const {
    logged,
    setLogged,
    token,
    setToken,
    page,
    setPage,
    error,
    setError,
    notice,
    setNotice,
    busy,
    agents,
    setAgentEdit,
    setAgentNew,
    login,
    editProvider,
    act,
    load,
  } = c;
  const currentPage = pages.find((item) => item.id === page) || pages[0];
  if (!logged)
    return (
      <div className="login">
        <form onSubmit={login}>
          <LanguageSwitch compact />
          <div className="brand-mark"><BrandGlyph /></div>
          <p className="eyebrow">WELCOME BACK</p>
          <h1>{t("login.welcome")}</h1>
          <p>{t("login.description")}</p>
          <Field
            title={t("login.token")}
            hint={t("login.tokenHint")}
          >
            <input
              type="password"
              autoComplete="off"
              required
              value={token}
              onChange={(e) => setToken(e.target.value)}
            />
          </Field>
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          <button disabled={busy} className="primary">
            {busy ? t("login.connecting") : t("login.enter")}
          </button>
          <small>{t("login.accessHint")}</small>
        </form>
        <div className="login-art">
          <span>SELF-HOSTED · PREVIEW</span>
          <h2>
            {t("login.heroTitle1")}
            <br />
            {t("login.heroTitle2")}
          </h2>
          <p>{t("login.heroSubtitle")}</p>
          <MascotScene variant="welcome" />
        </div>
      </div>
    );
  return (
    <div className="shell">
      <aside>
        <div className="brand">
          <div className="brand-mark"><BrandGlyph /></div>
          <div>
            Maintune<small>SELF-HOSTED</small>
          </div>
        </div>
        <p className="nav-label">{t("nav.workspace")}</p>
        <nav>
          {pages.map((p) => (
            <button
              key={p.id}
              className={page === p.id ? "active" : ""}
              onClick={() => {
                setPage(p.id);
                setError("");
                setNotice("");
              }}
            >
              <span className="nav-icon"><NavMascotIcon kind={p.icon as ThemeIconKind}/></span>
              {t(p.label as MessageKey)}
              {p.experimental && <small>{t("nav.experimental")}</small>}
              {p.id === "Agents" && <small>{agents.length}</small>}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span className="dot" /> {t("shell.automationPreview")}
          <p>{t("shell.sidebarNote")}</p>
          <button
            className="text"
            onClick={() => {
              setCredential("");
              setLogged(false);
            }}
          >
            {t("shell.logout")}
          </button>
        </div>
      </aside>
      <main>
        <header>
          <div className="breadcrumb">
            {t("nav.workspace")} <span>/</span> {t(currentPage.label as MessageKey)}
          </div>
          <span className="local-chip"><i/> {t("shell.instance")}</span>
        </header>
        <div className="content">
          <div className="page-title">
            <div className="page-title-copy">
              <NavMascotIcon kind={currentPage.icon as ThemeIconKind}/>
              <div>
              <p className="eyebrow">MAINTUNE CONSOLE</p>
              <h1>{t(currentPage.label as MessageKey)}</h1>
              <p>
                {t(currentPage.description as MessageKey)}
              </p>
              </div>
            </div>
            {page === "模型" ? (
              <button className="primary" onClick={() => editProvider()}>
                {t("shell.addProvider")}
              </button>
            ) : page === "Agents" ? (
              <button
                className="primary"
                onClick={() => {
                  setAgentNew(true);
                  setAgentEdit({
                    name: "",
                    identifier: "",
                    enabled: true,
                    description: "",
                    system_prompt: "",
                    model: null,
                    runtime: emptyRuntime(),
                  });
                }}
              >
                {t("shell.addAgent")}
              </button>
            ) : (
              <button disabled={busy} onClick={() => act(load, t("shell.refreshed"))}>
                ↻ {t("common.refresh")}
              </button>
            )}
          </div>
          {error && (
            <div className="error" role="alert">
              {error}
            </div>
          )}
          {notice && (
            <div className="notice" role="status">
              {notice}
            </div>
          )}
          <DashboardPage c={c} />
          <IntegrationsPage c={c} />
          <TasksPage c={c} />
          <ProvidersPage c={c} />
          <SettingsPage c={c} />
          <AgentsPage c={c} />
          <PluginsPage c={c} />
          <RunsPage c={c} />
        </div>
        <footer>
          Maintune v0.1.0-preview.1 <span>{t("shell.footer")}</span>
        </footer>
      </main>
      <ProviderDialog c={c} />
      <AgentDialog c={c} />
      <RunDialog c={c} />
      <SetupWizard c={c} />
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<I18nProvider><App /></I18nProvider>);

