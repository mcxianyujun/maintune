import { api } from "../api";
import { Field, ModelSelect } from "../components";
import type { ConsoleState } from "../useConsole";
import type { ReasoningEffort, ReasoningMode, Sandbox, Settings } from "../types";
import { LanguageSwitch, useI18n } from "../i18n";
const numberOrNull = (value: string) => value === "" ? null : Number(value);
export function SettingsPage({ c }: { c: ConsoleState }) {
  const { t } = useI18n();
  const {
    page,
    setNotice,
    busy,
    providers,
    runtimeConfigs,
    settings,
    setSettings,
    sandbox,
    setSandbox,
    prompt,
    sandboxKey,
    setSandboxKey,
    load,
    act,
    setWizardOpen,
  } = c;
  const selectedModel = settings?.model
    ? providers.find((provider) => provider.id === settings.model?.provider)?.models.find((model) => model.id === settings.model?.model)
    : undefined;
  const caps = selectedModel?.capabilities;
  const effective = runtimeConfigs.main;
  const resetMain = (scope: "reasoning" | "generation" | "steps" | "timeouts" | "all") => {
    if (scope === "all" && !confirm(t("settings.confirmReset"))) return;
    act(async () => {
      const result = await api<{ settings: Settings }>("/settings/reset", "POST", { scope });
      setSettings(result.settings);
      await load();
    }, scope === "all" ? t("settings.resetAllDone") : t("settings.resetGroupDone"));
  };
  return (
    <>
      {["系统设置", "Sandbox"].includes(page) && settings && sandbox && (
        <div className="settings-grid">
          {page === "系统设置" && <section className="language-setting"><div><h2>{t("settings.languageTitle")}</h2><p className="muted">{t("settings.languageHint")}</p></div><LanguageSwitch/></section>}
          {page === "系统设置" &&
          <section>
            <div className="section-head"><div><h2>{t("settings.mainAgent")}</h2><p className="muted">{t("settings.mainHint")}</p></div><button type="button" onClick={()=>setWizardOpen(true)}>{t("settings.rerunWizard")}</button></div>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                act(async () => {
                  await api("/settings", "PUT", settings);
                }, t("settings.savedMain"));
              }}
            >
              <Field title={t("settings.defaultModel")}>
                <ModelSelect
                  providers={providers}
                  value={settings.model}
                  onChange={(model) => setSettings({ ...settings, model })}
                />
              </Field>
              <Field title="System Prompt">
                <textarea
                  rows={8}
                  value={settings.system_prompt}
                  onChange={(e) =>
                    setSettings({
                      ...settings,
                      system_prompt: e.target.value,
                    })
                  }
                />
              </Field>
              <button
                type="button"
                className="text"
                onClick={() =>
                  act(async () => {
                    const d = await api<{ system_prompt: string }>(
                      "/defaults/prompt",
                    );
                    setSettings({
                      ...settings,
                      system_prompt: d.system_prompt,
                    });
                  })
                }
              >
                {t("settings.restorePrompt")}
              </button>
              {effective && <div className="effective-config"><strong>{t("model.current")}</strong><span>{effective.provider_name} / {effective.model_display_name}</span><span>Reasoning: {effective.reasoning_mode} / {effective.reasoning_effort}</span><span>Steps: {effective.steps_mode} · {effective.soft_step_limit} soft / {effective.hard_step_limit} hard</span><span>Timeout: model {effective.model_timeout}s · tool {effective.tool_timeout}s · task {effective.task_timeout}s</span></div>}
              <details>
                <summary>{t("settings.advanced")}</summary>
                <div className="group-head"><h3>{t("settings.reasoning")}</h3><button type="button" className="text" onClick={() => resetMain("reasoning")}>{t("settings.resetGroup")}</button></div>
                <div className="inline-fields">
                  <Field title="Reasoning Mode" hint={caps && !caps.supports_reasoning ? t("model.unsupported") : undefined}><select disabled={!!caps && !caps.supports_reasoning} value={settings.reasoning.mode ?? ""} onChange={(e) => setSettings({ ...settings, reasoning: { ...settings.reasoning, mode: (e.target.value || null) as ReasoningMode | null } })}><option value="">{t("model.default")}</option><option value="auto">Auto</option><option value="on">On</option><option value="off">Off</option></select></Field>
                  <Field title="Reasoning Effort" hint={caps && !caps.supports_reasoning_effort ? t("model.unsupported") : undefined}><select disabled={!!caps && !caps.supports_reasoning_effort} value={settings.reasoning.effort ?? ""} onChange={(e) => setSettings({ ...settings, reasoning: { ...settings.reasoning, effort: (e.target.value || null) as ReasoningEffort | null } })}><option value="">{t("model.default")}</option><option value="inherit">Provider default</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="extra_high">Extra high</option></select></Field>
                  <Field title="Reasoning Budget" hint={caps && !caps.supports_reasoning_budget ? t("model.unsupported") : t("settings.reasoningHint")}><input disabled={!!caps && !caps.supports_reasoning_budget} value={settings.reasoning.budget ?? ""} onChange={(e) => setSettings({ ...settings, reasoning: { ...settings.reasoning, budget: e.target.value === "" ? null : e.target.value === "auto" || e.target.value === "unset" ? e.target.value : Number(e.target.value) } })} /></Field>
                </div>
                <div className="group-head"><h3>{t("settings.generation")}</h3><button type="button" className="text" onClick={() => resetMain("generation")}>{t("settings.resetGroup")}</button></div>
                <div className="inline-fields">
                  <Field title="Temperature" hint={caps && !caps.supports_temperature ? t("model.unsupported") : undefined}><input disabled={!!caps && !caps.supports_temperature} type="number" min={0} max={2} step="0.01" value={settings.generation.temperature ?? ""} onChange={(e) => setSettings({ ...settings, generation: { ...settings.generation, temperature: numberOrNull(e.target.value) } })} /></Field>
                  <Field title="Top P" hint={caps && !caps.supports_top_p ? t("model.unsupported") : undefined}><input disabled={!!caps && !caps.supports_top_p} type="number" min={0.0001} max={1} step="0.01" value={settings.generation.top_p ?? ""} onChange={(e) => setSettings({ ...settings, generation: { ...settings.generation, top_p: numberOrNull(e.target.value) } })} /></Field>
                  <Field title="Max output tokens" hint={caps && !caps.supports_max_output_tokens ? t("model.unsupported") : undefined}><input disabled={!!caps && !caps.supports_max_output_tokens} type="number" min={1} value={settings.generation.max_output_tokens ?? ""} onChange={(e) => setSettings({ ...settings, generation: { ...settings.generation, max_output_tokens: numberOrNull(e.target.value) } })} /></Field>
                </div>
                <div className="group-head"><h3>Steps / Budget</h3><button type="button" className="text" onClick={() => resetMain("steps")}>{t("settings.resetGroup")}</button></div>
                <div className="inline-fields">
                  <Field title={t("settings.mode")}><select value={settings.steps.mode} onChange={(e) => setSettings({ ...settings, steps: { ...settings.steps, mode: e.target.value as "auto" | "fixed", fixed_steps: e.target.value === "fixed" ? settings.steps.fixed_steps || 60 : settings.steps.fixed_steps } })}><option value="auto">{t("settings.autoSteps")}</option><option value="fixed">{t("settings.fixedSteps")}</option></select></Field>
                  {settings.steps.mode === "fixed" && <Field title="Fixed steps"><input required type="number" min={1} max={2000} value={settings.steps.fixed_steps ?? ""} onChange={(e) => setSettings({ ...settings, steps: { ...settings.steps, fixed_steps: numberOrNull(e.target.value) } })} /></Field>}
                  <Field title="Soft limit" hint={t("settings.softHint")}><input type="number" min={1} max={2000} value={settings.steps.soft_limit ?? ""} onChange={(e) => setSettings({ ...settings, steps: { ...settings.steps, soft_limit: numberOrNull(e.target.value) } })} /></Field>
                  <Field title="Hard limit" hint={t("settings.hardHint")}><input type="number" min={1} max={4000} value={settings.steps.hard_limit ?? ""} onChange={(e) => setSettings({ ...settings, steps: { ...settings.steps, hard_limit: numberOrNull(e.target.value) } })} /></Field>
                  <Field title={t("settings.extension")}><input type="number" min={1} max={200} value={settings.steps.extension} onChange={(e) => setSettings({ ...settings, steps: { ...settings.steps, extension: Number(e.target.value) } })} /></Field>
                  <Field title={t("settings.loopThreshold")}><input type="number" min={2} max={20} value={settings.steps.loop_threshold} onChange={(e) => setSettings({ ...settings, steps: { ...settings.steps, loop_threshold: Number(e.target.value) } })} /></Field>
                </div>
                <div className="group-head"><h3>{t("settings.timeouts")}</h3><button type="button" className="text" onClick={() => resetMain("timeouts")}>{t("settings.resetGroup")}</button></div>
                <div className="inline-fields">
                  <Field title="Model request" hint={t("settings.modelTimeoutHint")}><input type="number" min={1} max={7200} value={settings.timeouts.model_request ?? ""} onChange={(e) => setSettings({ ...settings, timeouts: { ...settings.timeouts, model_request: numberOrNull(e.target.value) } })} /></Field>
                  <Field title="Tool call" hint={t("settings.toolTimeoutHint")}><input type="number" min={1} max={7200} value={settings.timeouts.tool_call ?? ""} onChange={(e) => setSettings({ ...settings, timeouts: { ...settings.timeouts, tool_call: numberOrNull(e.target.value) } })} /></Field>
                  <Field title="Agent task" hint={t("settings.taskTimeoutHint")}><input type="number" min={1} max={86400} value={settings.timeouts.agent_task ?? ""} onChange={(e) => setSettings({ ...settings, timeouts: { ...settings.timeouts, agent_task: numberOrNull(e.target.value) } })} /></Field>
                  <Field title="Sandbox TTL" hint={t("settings.sandboxTimeoutHint")}><input type="number" min={60} max={86400} value={settings.timeouts.sandbox_ttl ?? ""} onChange={(e) => setSettings({ ...settings, timeouts: { ...settings.timeouts, sandbox_ttl: numberOrNull(e.target.value) } })} /></Field>
                </div>
                <div className="actions"><button type="button" className="danger" onClick={() => resetMain("all")}>{t("settings.resetAll")}</button></div>
              </details>
              <button disabled={busy} className="primary">
                {t("settings.saveMain")}
              </button>
            </form>
          </section>
          }
          {page === "Sandbox" &&
          <section>
            <h2>{t("sandbox.title")}</h2>
            <p className="muted">{t("sandbox.hint")}</p>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                act(async () => {
                  await api("/sandbox", "PUT", {
                    provider: sandbox.provider,
                    base_url: sandbox.base_url,
                    profile: sandbox.profile,
                    ...(sandboxKey ? { api_key: sandboxKey } : {}),
                  });
                  setSandboxKey("");
                  await load();
                }, t("common.saved"));
              }}
            >
              <Field title="Provider">
                <select
                  value={sandbox.provider}
                  onChange={(e) =>
                    setSandbox({
                      ...sandbox,
                      provider: e.target.value as Sandbox["provider"],
                    })
                  }
                >
                  <option value="local">{t("sandbox.localOption")}</option>
                  <option value="shipyard">{t("sandbox.shipyardOption")}</option>
                </select>
              </Field>
              {sandbox.provider === "local" ? (
                <div className="info">{t("sandbox.localInfo")}</div>
              ) : (
                <>
                  <Field title="Base URL">
                    <input
                      required
                      value={sandbox.base_url}
                      onChange={(e) =>
                        setSandbox({ ...sandbox, base_url: e.target.value })
                      }
                    />
                  </Field>
                  <Field
                    title="Replace API Key"
                    hint={t("sandbox.keyHint")}
                  >
                    <input
                      type="password"
                      autoComplete="off"
                      placeholder={sandbox.api_key_masked}
                      value={sandboxKey}
                      onChange={(e) => setSandboxKey(e.target.value)}
                    />
                  </Field>
                  <Field
                    title="Profile"
                    hint={t("sandbox.profileHint")}
                  >
                    <input
                      value={sandbox.profile}
                      onChange={(e) =>
                        setSandbox({ ...sandbox, profile: e.target.value })
                      }
                    />
                  </Field>
                </>
              )}
              <div className="actions">
                <button disabled={busy} className="primary">
                  {t("sandbox.save")}
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    act(async () => {
                      const r = await api<{ capability: string }>(
                        "/sandbox/test",
                        "POST",
                      );
                      setNotice(t("sandbox.testSuccess", { capability: r.capability }));
                    })
                  }
                >
                  {t("sandbox.testSaved")}
                </button>
              </div>
            </form>
          </section>
          }
        </div>
      )}
    </>
  );
}

