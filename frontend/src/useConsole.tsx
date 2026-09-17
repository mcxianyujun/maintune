import { useEffect, useState, type FormEvent } from "react";
import { api, setCredential } from "./api";
import type {
  Agent,
  Dashboard,
  EmailConfig,
  GitHubConfig,
  Provider,
  Repository,
  ResolvedRuntime,
  Run,
  Sandbox,
  Settings,
  SetupStatus,
  Task,
} from "./types";
import { statusKeys } from "./components";
import { useI18n } from "./i18n";
export function useConsole() {
  const { t, date } = useI18n();
  const [logged, setLogged] = useState(false),
    [token, setToken] = useState(""),
    [page, setPage] = useState("概览");
  const [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false);
  const [providers, setProviders] = useState<Provider[]>([]),
    [agents, setAgents] = useState<Agent[]>([]),
    [runs, setRuns] = useState<Run[]>([]);
  const [runtimeConfigs, setRuntimeConfigs] = useState<Record<string, ResolvedRuntime>>({});
  const [settings, setSettings] = useState<Settings>(),
    [sandbox, setSandbox] = useState<Sandbox>(),
    [dashboard, setDashboard] = useState<Dashboard>();
  const [github, setGithub] = useState<GitHubConfig>(),
    [email, setEmail] = useState<EmailConfig>(),
    [repositories, setRepositories] = useState<Repository[]>([]),
    [tasks, setTasks] = useState<Task[]>([]);
  const [window, setWindow] = useState("24h"),
    [prompt, setPrompt] = useState(""),
    [runAgent, setRunAgent] = useState("main");
  const [providerEdit, setProviderEdit] = useState<Partial<Provider>>(),
    [key, setKey] = useState("");
  const [agentEdit, setAgentEdit] = useState<Agent>(),
    [agentNew, setAgentNew] = useState(false),
    [sandboxKey, setSandboxKey] = useState("");
  const [detail, setDetail] = useState<Run>();
  const [setupStatus, setSetupStatus] = useState<SetupStatus>();
  const [wizardOpen, setWizardOpen] = useState(false);
  async function load() {
    const [p, a, r, s, b, d, g, e, repos, queued, effective, setup] = await Promise.all([
      api<Provider[]>("/providers"),
      api<Agent[]>("/agents"),
      api<Run[]>("/runs"),
      api<Settings>("/settings"),
      api<Sandbox>("/sandbox"),
      api<Dashboard>("/dashboard"),
      api<Partial<GitHubConfig>>("/github"),
      api<Partial<EmailConfig>>("/email"),
      api<Repository[]>("/repositories"),
      api<Task[]>("/tasks"),
      api<Record<string, ResolvedRuntime>>("/runtime-configs"),
      api<SetupStatus>("/setup/status"),
    ]);
    setProviders(p);
    setAgents(a);
    setRuns(r);
    setSettings(s);
    setSandbox(b);
    setDashboard(d);
    setGithub({ app_id: 0, installation_id: null, api_url: "https://api.github.com", has_private_key: false, private_key_masked: "", has_webhook_secret: false, webhook_secret_masked: "", ...g });
    setEmail({ host: "", port: 587, username: "", from_address: "", owner_email: "", mode: "starttls", enabled: false, has_password: false, password_masked: "", ...e });
    setRepositories(repos);
    setTasks(queued);
    setRuntimeConfigs(effective);
    setSetupStatus(setup);
    return setup;
  }
  async function act(fn: () => Promise<unknown>, message = "") {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await fn();
      if (message) setNotice(message);
    } catch (e) {
      setError(e instanceof Error && e.message !== "REQUEST_FAILED" ? e.message : t("common.requestFailed"));
    } finally {
      setBusy(false);
    }
  }
  async function login(e: FormEvent) {
    e.preventDefault();
    await act(async () => {
      setCredential(token);
      const setup = await load();
      setLogged(true);
      setWizardOpen(!setup.complete);
      setToken("");
    });
  }
  useEffect(() => {
    if (!logged) return;
    const timer = globalThis.setInterval(() => {
      Promise.all([api<Run[]>("/runs"), api<Dashboard>("/dashboard"), api<Task[]>("/tasks")])
        .then(([r, d, t]) => {
          setRuns(r);
          setDashboard(d);
          setTasks(t);
        })
        .catch(() => {});
    }, 10000);
    return () => clearInterval(timer);
  }, [logged]);
  function editProvider(
    p: Partial<Provider> = {
      name: "",
      base_url: "https://api.example.com/v1",
      models: [],
    },
  ) {
    setProviderEdit(p);
    setKey("");
  }
  const runTable = (items: Run[]) => (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>{t("runs.taskAgent")}</th>
            <th>{t("common.model")}</th>
            <th>{t("runs.started")}</th>
            <th>{t("common.status")}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {items.map((r) => (
            <tr key={r.id}>
              <td>
                <strong>{r.agent}</strong>
                <small>{r.id.slice(0, 8)} · {t("runs.manual")}</small>
              </td>
              <td>{r.model}</td>
              <td>{date(r.started)}</td>
              <td>
                <span className={"badge " + r.status}>
                  {statusKeys[r.status] ? t(statusKeys[r.status]) : r.status}
                </span>
              </td>
              <td>
                <button className="text" onClick={() => setDetail(r)}>
                  {t("common.details")} ↗
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!items.length && (
        <div className="empty">
          <div>◷</div>
          <h3>{t("runs.empty")}</h3>
          <p>{t("runs.emptyHint")}</p>
        </div>
      )}
    </div>
  );
  return {
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
    providers,
    agents,
    runtimeConfigs,
    runs,
    settings,
    setSettings,
    sandbox,
    setSandbox,
    dashboard,
    github,
    setGithub,
    email,
    setEmail,
    repositories,
    setRepositories,
    tasks,
    setTasks,
    window,
    setWindow,
    prompt,
    setPrompt,
    runAgent,
    setRunAgent,
    providerEdit,
    setProviderEdit,
    key,
    setKey,
    agentEdit,
    setAgentEdit,
    agentNew,
    setAgentNew,
    sandboxKey,
    setSandboxKey,
    detail,
    setDetail,
    setupStatus,
    setSetupStatus,
    wizardOpen,
    setWizardOpen,
    load,
    act,
    login,
    editProvider,
    runTable,
  };
}
export type ConsoleState = ReturnType<typeof useConsole>;
