import { api } from "../api";
import { Field, ModelSelect } from "../components";
import type { ConsoleState } from "../useConsole";
import { emptyRuntime, type Agent, type ReasoningEffort, type ReasoningMode, type StepConfig } from "../types";
import { useI18n } from "../i18n";
const numberOrNull = (value: string) => value === "" ? null : Number(value);
export function AgentDialog({ c }: { c: ConsoleState }) {
  const { t } = useI18n();
  const {
    error,
    busy,
    providers,
    agents,
    settings,
    runtimeConfigs,
    agentEdit,
    setAgentEdit,
    agentNew,
    load,
    act,
  } = c;
  const defaults = emptyRuntime();
  const runtime = {
    ...defaults,
    ...agentEdit?.runtime,
    reasoning: { ...defaults.reasoning, ...agentEdit?.runtime?.reasoning },
    generation: { ...defaults.generation, ...agentEdit?.runtime?.generation },
    timeouts: { ...defaults.timeouts, ...agentEdit?.runtime?.timeouts },
  };
  const effective = agentEdit ? runtimeConfigs[agentEdit.identifier] : undefined;
  const selectedRef = agentEdit?.model || settings?.model;
  const caps = selectedRef ? providers.find((provider) => provider.id === selectedRef.provider)?.models.find((model) => model.id === selectedRef.model)?.capabilities : undefined;
  const resetAgent = (scope: "reasoning" | "generation" | "steps" | "timeouts" | "all") => {
    if (!agentEdit || agentNew) return;
    if (scope === "all" && !confirm(t("agents.resetConfirm"))) return;
    act(async () => {
      const result = await api<{ agent: Agent }>(`/agents/${agentEdit.identifier}/reset`, "POST", { scope });
      setAgentEdit(result.agent);
      await load();
    }, scope === "all" ? t("agents.resetAllDone") : t("agents.resetGroupDone"));
  };
  return (
    <>
      {agentEdit && (
        <div className="modal-overlay">
          <section className="modal">
            <h2>{agentNew ? t("agents.newTitle") : t("agents.editTitle")}</h2>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                act(async () => {
                  await api(
                    agentNew ? "/agents" : `/agents/${agentEdit.identifier}`,
                    agentNew ? "POST" : "PUT",
                    agentEdit,
                  );
                  setAgentEdit(undefined);
                  await load();
                }, t("agents.saved"));
              }}
            >
              <Field title={t("agents.name")}>
                <input
                  required
                  value={agentEdit.name}
                  onChange={(e) =>
                    setAgentEdit({ ...agentEdit, name: e.target.value })
                  }
                />
              </Field>
              <Field title="Identifier">
                <input
                  required
                  disabled={!agentNew}
                  pattern="[a-z][a-z0-9_]{0,63}"
                  value={agentEdit.identifier}
                  onChange={(e) =>
                    setAgentEdit({ ...agentEdit, identifier: e.target.value })
                  }
                />
              </Field>
              <Field title={t("agents.description")}>
                <textarea
                  required
                  maxLength={400}
                  rows={2}
                  value={agentEdit.description}
                  onChange={(e) =>
                    setAgentEdit({ ...agentEdit, description: e.target.value })
                  }
                />
              </Field>
              <Field title={t("agents.prompt")}>
                <textarea
                  required
                  rows={5}
                  value={agentEdit.system_prompt}
                  onChange={(e) =>
                    setAgentEdit({
                      ...agentEdit,
                      system_prompt: e.target.value,
                    })
                  }
                />
              </Field>
              <Field title={t("common.model")}>
                <ModelSelect
                  inherit
                  providers={providers}
                  value={agentEdit.model}
                  onChange={(model) => setAgentEdit({ ...agentEdit, model })}
                />
              </Field>
              {effective && <div className="effective-config"><strong>{t("model.current")}</strong><span>{effective.provider_name} / {effective.model_display_name}</span><span>Reasoning: {effective.reasoning_mode} / {effective.reasoning_effort}</span><span>Steps: {effective.steps_mode} · {effective.soft_step_limit} soft / {effective.hard_step_limit} hard</span><span>Timeout: model {effective.model_timeout}s · tool {effective.tool_timeout}s · task {effective.task_timeout}s</span></div>}
              <details>
                <summary>{t("agents.advanced")}</summary>
                <div className="group-head"><h3>Reasoning</h3>{!agentNew && <button type="button" className="text" onClick={() => resetAgent("reasoning")}>{t("settings.resetGroup")}</button>}</div>
                <div className="inline-fields">
                  <Field title="Mode" hint={caps && !caps.supports_reasoning ? t("model.unsupported") : undefined}><select disabled={!!caps && !caps.supports_reasoning} value={runtime.reasoning.mode ?? ""} onChange={(e) => setAgentEdit({ ...agentEdit, runtime: { ...runtime, reasoning: { ...runtime.reasoning, mode: (e.target.value || null) as ReasoningMode | null } } })}><option value="">Inherit</option><option value="auto">Auto</option><option value="on">On</option><option value="off">Off</option></select></Field>
                  <Field title="Effort" hint={caps && !caps.supports_reasoning_effort ? t("model.unsupported") : undefined}><select disabled={!!caps && !caps.supports_reasoning_effort} value={runtime.reasoning.effort ?? ""} onChange={(e) => setAgentEdit({ ...agentEdit, runtime: { ...runtime, reasoning: { ...runtime.reasoning, effort: (e.target.value || null) as ReasoningEffort | null } } })}><option value="">Inherit</option><option value="inherit">Provider default</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="extra_high">Extra high</option></select></Field>
                  <Field title="Budget" hint={caps && !caps.supports_reasoning_budget ? t("model.unsupported") : t("agents.inheritHint")}><input disabled={!!caps && !caps.supports_reasoning_budget} value={runtime.reasoning.budget ?? ""} onChange={(e) => setAgentEdit({ ...agentEdit, runtime: { ...runtime, reasoning: { ...runtime.reasoning, budget: e.target.value === "" ? null : e.target.value === "auto" || e.target.value === "unset" ? e.target.value : Number(e.target.value) } } })} /></Field>
                </div>
                <div className="group-head"><h3>{t("agents.generation")}</h3>{!agentNew && <button type="button" className="text" onClick={() => resetAgent("generation")}>{t("settings.resetGroup")}</button>}</div>
                <div className="inline-fields">
                  <Field title="Temperature" hint={caps && !caps.supports_temperature ? t("model.unsupported") : undefined}><input disabled={!!caps && !caps.supports_temperature} type="number" min={0} max={2} step="0.01" value={runtime.generation.temperature ?? ""} onChange={(e) => setAgentEdit({ ...agentEdit, runtime: { ...runtime, generation: { ...runtime.generation, temperature: numberOrNull(e.target.value) } } })} /></Field>
                  <Field title="Top P" hint={caps && !caps.supports_top_p ? t("model.unsupported") : undefined}><input disabled={!!caps && !caps.supports_top_p} type="number" min={0.0001} max={1} step="0.01" value={runtime.generation.top_p ?? ""} onChange={(e) => setAgentEdit({ ...agentEdit, runtime: { ...runtime, generation: { ...runtime.generation, top_p: numberOrNull(e.target.value) } } })} /></Field>
                  <Field title="Max output tokens" hint={caps && !caps.supports_max_output_tokens ? t("model.unsupported") : undefined}><input disabled={!!caps && !caps.supports_max_output_tokens} type="number" min={1} value={runtime.generation.max_output_tokens ?? ""} onChange={(e) => setAgentEdit({ ...agentEdit, runtime: { ...runtime, generation: { ...runtime.generation, max_output_tokens: numberOrNull(e.target.value) } } })} /></Field>
                </div>
                <div className="group-head"><h3>Steps / Budget</h3>{!agentNew && <button type="button" className="text" onClick={() => resetAgent("steps")}>{t("settings.resetGroup")}</button>}</div>
                <Field title={t("settings.mode")}><select value={runtime.steps?.mode || "inherit"} onChange={(e) => { const value = e.target.value; const steps: StepConfig | null = value === "inherit" ? null : { mode: value as "auto" | "fixed", fixed_steps: value === "fixed" ? 50 : null, soft_limit: null, hard_limit: null, extension: 20, loop_threshold: 3 }; setAgentEdit({ ...agentEdit, runtime: { ...runtime, steps } }) }}><option value="inherit">Inherit</option><option value="auto">Auto</option><option value="fixed">Fixed</option></select></Field>
                {runtime.steps && <div className="inline-fields">
                  {runtime.steps.mode === "fixed" && <Field title="Fixed steps"><input required type="number" min={1} max={2000} value={runtime.steps.fixed_steps ?? ""} onChange={(e) => setAgentEdit({ ...agentEdit, runtime: { ...runtime, steps: { ...runtime.steps!, fixed_steps: numberOrNull(e.target.value) } } })} /></Field>}
                  <Field title="Soft limit"><input type="number" min={1} max={2000} value={runtime.steps.soft_limit ?? ""} onChange={(e) => setAgentEdit({ ...agentEdit, runtime: { ...runtime, steps: { ...runtime.steps!, soft_limit: numberOrNull(e.target.value) } } })} /></Field>
                  <Field title="Hard limit"><input type="number" min={1} max={4000} value={runtime.steps.hard_limit ?? ""} onChange={(e) => setAgentEdit({ ...agentEdit, runtime: { ...runtime, steps: { ...runtime.steps!, hard_limit: numberOrNull(e.target.value) } } })} /></Field>
                  <Field title={t("settings.extension")}><input type="number" min={1} max={200} value={runtime.steps.extension} onChange={(e) => setAgentEdit({ ...agentEdit, runtime: { ...runtime, steps: { ...runtime.steps!, extension: Number(e.target.value) } } })} /></Field>
                  <Field title={t("settings.loopThreshold")}><input type="number" min={2} max={20} value={runtime.steps.loop_threshold} onChange={(e) => setAgentEdit({ ...agentEdit, runtime: { ...runtime, steps: { ...runtime.steps!, loop_threshold: Number(e.target.value) } } })} /></Field>
                </div>}
                <div className="group-head"><h3>{t("agents.timeouts")}</h3>{!agentNew && <button type="button" className="text" onClick={() => resetAgent("timeouts")}>{t("settings.resetGroup")}</button>}</div>
                <div className="inline-fields">
                  <Field title="Model request"><input type="number" min={1} max={7200} value={runtime.timeouts.model_request ?? ""} onChange={(e) => setAgentEdit({ ...agentEdit, runtime: { ...runtime, timeouts: { ...runtime.timeouts, model_request: numberOrNull(e.target.value) } } })} /></Field>
                  <Field title="Tool call"><input type="number" min={1} max={7200} value={runtime.timeouts.tool_call ?? ""} onChange={(e) => setAgentEdit({ ...agentEdit, runtime: { ...runtime, timeouts: { ...runtime.timeouts, tool_call: numberOrNull(e.target.value) } } })} /></Field>
                  <Field title="Agent task"><input type="number" min={1} max={86400} value={runtime.timeouts.agent_task ?? ""} onChange={(e) => setAgentEdit({ ...agentEdit, runtime: { ...runtime, timeouts: { ...runtime.timeouts, agent_task: numberOrNull(e.target.value) } } })} /></Field>
                  <Field title="Sandbox TTL"><input type="number" min={60} max={86400} value={runtime.timeouts.sandbox_ttl ?? ""} onChange={(e) => setAgentEdit({ ...agentEdit, runtime: { ...runtime, timeouts: { ...runtime.timeouts, sandbox_ttl: numberOrNull(e.target.value) } } })} /></Field>
                </div>
                {!agentNew && <div className="actions"><button type="button" className="danger" onClick={() => resetAgent("all")}>{t("settings.resetAll")}</button></div>}
              </details>
              {error && <p className="error">{error}</p>}
              <div className="actions">
                <button disabled={busy} className="primary">
                  {t("agents.save")}
                </button>
                <button type="button" onClick={() => setAgentEdit(undefined)}>
                  {t("common.cancel")}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
    </>
  );
}

