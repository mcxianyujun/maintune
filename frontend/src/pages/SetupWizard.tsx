import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { Field } from "../components";
import type { Provider, Repository, SetupStatus } from "../types";
import type { ConsoleState } from "../useConsole";
import { BrandGlyph, MascotScene } from "../assets/theme/ThemeArt";
import { LanguageSwitch, useI18n } from "../i18n";
import type { MessageKey } from "../i18n/resources";

const stepKeys: MessageKey[] = ["wizard.stepWelcome", "wizard.stepSystem", "wizard.stepModel", "wizard.stepGithub", "wizard.stepSandbox", "wizard.stepRepository", "wizard.stepOptional", "wizard.stepDiagnostics", "wizard.stepReady"];
const blankRepo: Repository = { full_name: "", installation_id: null, enabled: true, auto_handle_issues: true, auto_review_prs: true, auto_merge: false, default_branch: "main", install_command: "", test_command: "", lint_command: "", build_command: "", working_directory: ".", additional_instructions: "" };

export function SetupWizard({ c }: { c: ConsoleState }) {
  const { t } = useI18n();
  const { wizardOpen, setWizardOpen, setupStatus, setSetupStatus, providers, settings, github, sandbox, busy, act, load } = c;
  const [step, setStep] = useState(() => Math.min(Number(localStorage.getItem("maintainer.setup.step") || 0), stepKeys.length - 1));
  const [providerName, setProviderName] = useState(""), [baseUrl, setBaseUrl] = useState("https://api.example.com/v1"), [apiKey, setApiKey] = useState(""), [modelId, setModelId] = useState("");
  const [modelRef, setModelRef] = useState("");
  const [appId, setAppId] = useState(github?.app_id || 0), [installationId, setInstallationId] = useState<number | null>(github?.installation_id ?? null), [privateKey, setPrivateKey] = useState(""), [webhookSecret, setWebhookSecret] = useState("");
  const [githubApiUrl, setGithubApiUrl] = useState(github?.api_url || "https://api.github.com");
  const [sandboxProvider, setSandboxProvider] = useState<"local" | "shipyard">(sandbox?.provider || "local"), [sandboxUrl, setSandboxUrl] = useState(sandbox?.base_url || "http://127.0.0.1:8123"), [sandboxKey, setSandboxKey] = useState("");
  const [repo, setRepo] = useState(blankRepo);
  useEffect(() => { localStorage.setItem("maintainer.setup.step", String(step)); }, [step]);
  useEffect(() => { if (github) { setAppId(github.app_id); setInstallationId(github.installation_id); setGithubApiUrl(github.api_url); } }, [github]);
  const configuredModels = useMemo(() => providers.flatMap(p => p.models.filter(m => m.enabled).map(m => ({ value: JSON.stringify({ provider: p.id, model: m.id }), label: `${p.name} / ${m.display_name || m.id}` }))), [providers]);
  if (!wizardOpen || !setupStatus || !github || !sandbox || !settings) return null;

  const next = () => setStep(value => Math.min(value + 1, stepKeys.length - 1));
  const saveModel = () => act(async () => {
    let ref = modelRef ? JSON.parse(modelRef) : null;
    if (!ref) {
      if (!providerName.trim() || !baseUrl.trim() || !apiKey || !modelId.trim()) throw new Error(t("wizard.validationModel"));
      const created = await api<Provider>("/providers", "POST", { name: providerName, base_url: baseUrl, api_key: apiKey, models: [modelId] });
      ref = { provider: created.id, model: modelId };
      setApiKey("");
    }
    await api("/settings", "PUT", { ...settings, model: ref });
    await load(); next();
  }, t("wizard.modelSaved"));
  const saveGitHub = () => act(async () => {
    await api("/github", "PUT", { app_id: appId, installation_id: installationId, api_url: githubApiUrl, ...(privateKey ? { private_key: privateKey } : {}), ...(webhookSecret ? { webhook_secret: webhookSecret } : {}) });
    setPrivateKey(""); setWebhookSecret(""); await load(); next();
  }, t("wizard.githubSaved"));
  const saveSandbox = () => act(async () => {
    await api("/sandbox", "PUT", { provider: sandboxProvider, base_url: sandboxUrl, profile: sandbox.profile, ...(sandboxKey ? { api_key: sandboxKey } : {}) });
    setSandboxKey(""); await api("/sandbox/test", "POST"); await load(); next();
  }, t("wizard.sandboxPassed"));
  const saveRepository = () => act(async () => {
    const [owner, name, extra] = repo.full_name.split("/"); if (!owner || !name || extra) throw new Error(t("wizard.validationRepo"));
    await api(`/repositories/${encodeURIComponent(owner)}/${encodeURIComponent(name)}`, "PUT", repo); await load(); next();
  }, t("wizard.repoSaved"));
  const runDiagnostics = () => act(async () => { const status = await api<SetupStatus>("/setup/diagnostics", "POST"); setSetupStatus(status); if (status.steps.diagnostics) next(); }, t("wizard.diagnosticsDone"));

  return <div className="wizard-overlay" role="dialog" aria-modal="true" aria-label={t("wizard.dialogLabel")}>
    <div className="wizard-shell">
      <aside className="wizard-steps"><div className="brand"><div className="brand-mark"><BrandGlyph/></div><div>Maintune<small>FIRST RUN</small></div></div><LanguageSwitch compact/><ol>{stepKeys.map((name, index) => <li key={name} className={index === step ? "active" : index < step ? "done" : ""}><span>{index < step ? "✓" : index + 1}</span>{t(name)}</li>)}</ol><div className="wizard-aside-note">{t("wizard.pauseNote")}</div><button className="text" onClick={() => setWizardOpen(false)}>{t("wizard.pause")}</button></aside>
      <main className="wizard-main"><div className="wizard-progress"><span style={{ width: `${((step + 1) / stepKeys.length) * 100}%` }} /></div>
        {step === 0 && <div className="wizard-panel welcome-panel"><div className="wizard-language"><LanguageSwitch/></div><div className="wizard-art"><MascotScene variant="welcome"/></div><p className="eyebrow">FIRST-RUN SETUP</p><h1>{t("wizard.welcome")}</h1><p className="lead">{t("wizard.welcomeLead")}</p><p>{t("wizard.secretNote")}</p><div className="wizard-choice"><span><strong>{t("common.required")}</strong> {t("wizard.requiredList")}</span><span><strong>{t("common.optional")}</strong> {t("wizard.optionalList")}</span></div><button className="primary" onClick={next}>{t("wizard.start")}</button></div>}
        {step === 1 && <div className="wizard-panel"><p className="eyebrow">01 / ENVIRONMENT</p><h1>{t("wizard.environment")}</h1><p>{t("wizard.environmentText")}</p><div className="deployment-choice"><div><strong>{t("wizard.localBuildTitle")}</strong><span>{t("wizard.localBuild")}</span></div><span className="badge completed">{t("wizard.currentMode")}</span></div><div className="diagnostic-list"><Status label={t("wizard.database") } ok/><Status label={t("wizard.persistentStorage")} ok={setupStatus.steps.system}/><Status label={t("wizard.runtimeSchema")} ok detail={`v${setupStatus.schema}`}/><Status label={t("wizard.publicBaseUrl")} ok detail={setupStatus.base_url}/></div><div className="actions"><button onClick={next} disabled={!setupStatus.steps.system} className="primary">{t("wizard.environmentReady")}</button></div></div>}
        {step === 2 && <div className="wizard-panel"><p className="eyebrow">02 / MODEL PROVIDER</p><h1>{t("wizard.connectModel")}</h1>{configuredModels.length > 0 && <Field title={t("wizard.existingModel")}><select value={modelRef} onChange={e=>setModelRef(e.target.value)}><option value="">{t("wizard.addProvider")}</option>{configuredModels.map(m=><option value={m.value} key={m.value}>{m.label}</option>)}</select></Field>}{!modelRef && <><Field title={t("wizard.providerName")}><input value={providerName} onChange={e=>setProviderName(e.target.value)}/></Field><Field title="Base URL"><input value={baseUrl} onChange={e=>setBaseUrl(e.target.value)}/></Field><Field title="API Key" hint={t("wizard.secretSaved")}><input type="password" autoComplete="off" value={apiKey} onChange={e=>setApiKey(e.target.value)}/></Field><Field title="Model ID"><input value={modelId} onChange={e=>setModelId(e.target.value)}/></Field></>}<button className="primary" disabled={busy} onClick={saveModel}>{t("wizard.saveContinue")}</button></div>}
        {step === 3 && <div className="wizard-panel"><p className="eyebrow">03 / GITHUB APP</p><h1>{t("wizard.connectGithub")}</h1><div className="info">Webhook URL: <code>{setupStatus.base_url}/webhooks/github</code><br/>{t("wizard.githubPermissions")}</div><div className="inline-fields"><Field title="App ID"><input type="number" min={1} value={appId || ""} onChange={e=>setAppId(Number(e.target.value))}/></Field><Field title={t("wizard.installationOptional")}><input type="number" min={1} value={installationId ?? ""} onChange={e=>setInstallationId(e.target.value ? Number(e.target.value) : null)}/></Field></div><Field title="GitHub API URL" hint={t("wizard.githubApiHint")}><input value={githubApiUrl} onChange={e=>setGithubApiUrl(e.target.value)}/></Field><Field title="Private key PEM" hint={github.has_private_key ? t("wizard.keepPrivateKey") : undefined}><textarea rows={4} value={privateKey} onChange={e=>setPrivateKey(e.target.value)}/></Field><Field title="Webhook Secret" hint={github.has_webhook_secret ? t("wizard.keepSecret") : undefined}><input type="password" value={webhookSecret} onChange={e=>setWebhookSecret(e.target.value)}/></Field><button className="primary" disabled={busy || !appId || !githubApiUrl.trim()} onClick={saveGitHub}>{t("wizard.saveContinue")}</button></div>}
        {step === 4 && <div className="wizard-panel"><p className="eyebrow">04 / SANDBOX</p><h1>{t("wizard.workspace")}</h1><Field title="Provider"><select value={sandboxProvider} onChange={e=>setSandboxProvider(e.target.value as "local"|"shipyard")}><option value="local">Local · fallback</option><option value="shipyard">Shipyard Neo</option></select></Field>{sandboxProvider === "local" ? <div className="warning">{t("wizard.localWarning")}</div> : <><Field title="Bay API Base URL"><input value={sandboxUrl} onChange={e=>setSandboxUrl(e.target.value)}/></Field><Field title="API Key"><input type="password" value={sandboxKey} placeholder={sandbox.api_key_masked} onChange={e=>setSandboxKey(e.target.value)}/></Field></>}<button className="primary" disabled={busy} onClick={saveSandbox}>{t("wizard.saveTestContinue")}</button></div>}
        {step === 5 && <div className="wizard-panel"><p className="eyebrow">05 / REPOSITORY</p><h1>{t("wizard.addRepository")}</h1><Field title="owner/repository"><input value={repo.full_name} onChange={e=>setRepo({...repo,full_name:e.target.value})}/></Field><div className="inline-fields"><Field title={t("wizard.defaultBranch")}><input value={repo.default_branch} onChange={e=>setRepo({...repo,default_branch:e.target.value})}/></Field><Field title={t("wizard.testCommand")}><input placeholder="npm test" value={repo.test_command} onChange={e=>setRepo({...repo,test_command:e.target.value})}/></Field></div><div className="actions"><label className="toggle"><input type="checkbox" checked={repo.auto_handle_issues} onChange={e=>setRepo({...repo,auto_handle_issues:e.target.checked})}/>{t("wizard.issueAutomation")}</label><label className="toggle"><input type="checkbox" checked={repo.auto_review_prs} onChange={e=>setRepo({...repo,auto_review_prs:e.target.checked})}/>{t("wizard.prReview")}</label><label className="toggle"><input type="checkbox" checked={repo.auto_merge} onChange={e=>setRepo({...repo,auto_merge:e.target.checked})}/>{t("wizard.autoMerge")}</label></div><button className="primary" disabled={busy} onClick={saveRepository}>{t("wizard.saveContinue")}</button></div>}
        {step === 6 && <div className="wizard-panel"><p className="eyebrow">06 / OPTIONAL SERVICES</p><h1>{t("wizard.optionalServices")}</h1><p>{t("wizard.optionalText")}</p><button className="primary" onClick={next}>{t("wizard.skip")}</button></div>}
        {step === 7 && <div className="wizard-panel"><p className="eyebrow">07 / DIAGNOSTICS</p><h1>{t("wizard.diagnostics")}</h1><div className="diagnostic-list">{["database","model","github","sandbox","runtime","repository"].map(name=><Status key={name} label={name} ok={setupStatus.checks[name]?.ok} detail={setupStatus.checks[name]?.detail}/>)}</div><button className="primary" disabled={busy} onClick={runDiagnostics}>{busy ? t("wizard.checking") : t("wizard.runAll")}</button></div>}
        {step === 8 && <div className="wizard-panel ready-panel"><MascotScene variant="ready" compact/><div className="ready-check">✓</div><p className="eyebrow">SETUP COMPLETE</p><h1>{t("wizard.complete")}</h1><p>{t("wizard.completeText")}</p><button className="primary" disabled={!setupStatus.complete} onClick={async()=>{await load();localStorage.removeItem("maintainer.setup.step");setWizardOpen(false);}}>{t("wizard.enter")}</button></div>}
        {step > 0 && step < 8 && <button className="wizard-back text" onClick={()=>setStep(step-1)}>{t("common.previous")}</button>}
      </main>
    </div>
  </div>;
}

function Status({ label, ok, detail }: { label: string; ok?: boolean; detail?: string }) { const { t } = useI18n(); return <div className="diagnostic-row"><span className={ok ? "status-dot success" : "status-dot pending"}/><strong>{label}</strong><span>{detail || (ok ? t("common.ready") : t("common.pending"))}</span></div>; }
