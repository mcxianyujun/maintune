import { useEffect, useState } from "react";
import { api } from "../api";
import { Field } from "../components";
import { emptyModel, type ModelDefinition, type Provider } from "../types";
import type { ConsoleState } from "../useConsole";
import { useI18n } from "../i18n";

const capabilities: [keyof ModelDefinition["capabilities"], string][] = [
  ["supports_reasoning", "Reasoning"], ["supports_reasoning_effort", "Reasoning Effort"],
  ["supports_reasoning_budget", "Reasoning Budget"], ["supports_temperature", "Temperature"],
  ["supports_top_p", "Top P"], ["supports_max_output_tokens", "Max output tokens"],
];
const secretNames = new Set(["api_key", "apikey", "authorization", "token", "access_token", "password", "secret", "client_secret"]);
function assertNoSecrets(value: unknown, secretError: (field: string) => string) {
  if (Array.isArray(value)) return value.forEach(item => assertNoSecrets(item, secretError));
  if (value && typeof value === "object") for (const [key, nested] of Object.entries(value)) {
    if (secretNames.has(key.toLowerCase().replaceAll("-", "_"))) throw new Error(secretError(key));
    assertNoSecrets(nested, secretError);
  }
}
function nullableNumber(value: string): number | null { return value === "" ? null : Number(value); }

export function ProviderDialog({ c }: { c: ConsoleState }) {
  const { t } = useI18n();
  const { error, busy, providerEdit, setProviderEdit, key, setKey, load, act } = c;
  const [extraTexts, setExtraTexts] = useState<string[]>([]);
  const modalKey = providerEdit ? providerEdit.id || "__new__" : "__closed__";
  useEffect(() => {
    setExtraTexts((providerEdit?.models || []).map((m) => JSON.stringify(m.defaults.extra_params, null, 2)));
  }, [modalKey]);
  if (!providerEdit) return null;
  const models = providerEdit.models || [];
  const updateModel = (index: number, update: (model: ModelDefinition) => ModelDefinition) => {
    setProviderEdit({ ...providerEdit, models: models.map((m, i) => i === index ? update(m) : m) });
  };
  const toggleCapability = (index: number, name: keyof ModelDefinition["capabilities"], enabled: boolean) => updateModel(index, (model) => {
    const defaults = { ...model.defaults, reasoning: { ...model.defaults.reasoning }, generation: { ...model.defaults.generation } };
    if (!enabled) {
      if (name === "supports_reasoning") defaults.reasoning.mode = "auto";
      if (name === "supports_reasoning_effort") defaults.reasoning.effort = "inherit";
      if (name === "supports_reasoning_budget") defaults.reasoning.budget = null;
      if (name === "supports_temperature") defaults.generation.temperature = null;
      if (name === "supports_top_p") defaults.generation.top_p = null;
      if (name === "supports_max_output_tokens") defaults.generation.max_output_tokens = null;
    }
    return { ...model, capabilities: { ...model.capabilities, [name]: enabled }, defaults };
  });
  const resetModel = (index: number, scope: "reasoning" | "generation" | "advanced" | "all") => {
    if (scope === "all" && !confirm(t("providers.resetAllConfirm"))) return;
    act(async () => {
      if (!providerEdit.id) throw new Error(t("providers.saveFirst"));
      const result = await api<{ provider: Provider }>(`/providers/${providerEdit.id}/models/${encodeURIComponent(models[index].id)}/reset`, "POST", { scope });
      setProviderEdit(result.provider);
      setExtraTexts(result.provider.models.map((model) => JSON.stringify(model.defaults.extra_params, null, 2)));
      await load();
    }, scope === "all" ? t("providers.resetAllDone") : t("settings.resetGroupDone"));
  };
  return (
    <div className="modal-overlay">
      <section className="modal modal-wide">
        <h2>{providerEdit.id ? t("providers.edit") : t("providers.addTitle")}</h2>
        <form onSubmit={(e) => {
          e.preventDefault();
          act(async () => {
            const parsedModels = models.map((model, index) => {
              let parsed: unknown;
              try { parsed = JSON.parse(extraTexts[index] || "{}"); }
              catch { throw new Error(t("providers.invalidJson", {model: model.id || t("providers.newModel", {number: index + 1})})); }
              if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error(t("providers.objectRequired"));
              assertNoSecrets(parsed, field => t("providers.secretError", {field}));
              return { ...model, defaults: { ...model.defaults, extra_params: parsed as Record<string, unknown> } };
            });
            await api(providerEdit.id ? `/providers/${providerEdit.id}` : "/providers", providerEdit.id ? "PUT" : "POST", {
              name: providerEdit.name, type: "openai-compatible", base_url: providerEdit.base_url, models: parsedModels,
              ...(key ? { api_key: key } : {}),
            });
            setProviderEdit(undefined); setKey(""); await load();
          }, t("providers.saved"));
        }}>
          <div className="inline-fields">
            <Field title={t("providers.name")}><input required value={providerEdit.name || ""} onChange={(e) => setProviderEdit({ ...providerEdit, name: e.target.value })} /></Field>
            <Field title={t("providers.baseUrlLabel")}><input required value={providerEdit.base_url || ""} onChange={(e) => setProviderEdit({ ...providerEdit, base_url: e.target.value })} /></Field>
          </div>
          <Field title="API Key / Replace Key" hint={t("providers.keyHint")}>
            <input type="password" autoComplete="off" placeholder={providerEdit.api_key_masked} value={key} onChange={(e) => setKey(e.target.value)} />
          </Field>
          <div className="section-head"><div><h3>{t("providers.models")}</h3><small>{t("providers.modelsHint")}</small></div><button type="button" onClick={() => { setProviderEdit({ ...providerEdit, models: [...models, emptyModel()] }); setExtraTexts([...extraTexts, "{}"]) }}>{t("providers.addModel")}</button></div>
          {models.map((model, index) => (
            <details className="model-editor" key={index} open={models.length === 1 && !model.id}>
              <summary>{model.display_name || model.id || t("providers.newModel", {number: index + 1})} <span className="muted">{model.enabled ? t("common.enabled") : t("common.disabled")}</span></summary>
              <div className="inline-fields">
                <Field title="Model ID"><input required value={model.id} onChange={(e) => updateModel(index, (m) => ({ ...m, id: e.target.value }))} /></Field>
                <Field title={t("providers.displayName")}><input value={model.display_name || ""} onChange={(e) => updateModel(index, (m) => ({ ...m, display_name: e.target.value || null }))} /></Field>
              </div>
              <label className="toggle"><input type="checkbox" checked={model.enabled} onChange={(e) => updateModel(index, (m) => ({ ...m, enabled: e.target.checked }))} />{t("providers.enableModel")}</label>
              <h3>Capabilities</h3>
              <div className="capability-grid">{capabilities.map(([name, label]) => <label className="toggle" key={name}><input type="checkbox" checked={model.capabilities[name]} onChange={(e) => toggleCapability(index, name, e.target.checked)} />{label}</label>)}</div>
              <h3>{t("providers.defaults")}</h3>
              <div className="reset-actions">
                <button type="button" className="text" onClick={() => resetModel(index, "reasoning")}>Reasoning · {t("settings.resetGroup")}</button>
                <button type="button" className="text" onClick={() => resetModel(index, "generation")}>Generation · {t("settings.resetGroup")}</button>
                <button type="button" className="text" onClick={() => resetModel(index, "advanced")}>Advanced · {t("settings.resetGroup")}</button>
                <button type="button" className="danger" onClick={() => resetModel(index, "all")}>{t("settings.resetAll")}</button>
              </div>
              <div className="inline-fields">
                <Field title="Reasoning Mode" hint={!model.capabilities.supports_reasoning ? t("providers.capabilityDisabled") : undefined}>
                  <select disabled={!model.capabilities.supports_reasoning} value={model.defaults.reasoning.mode} onChange={(e) => updateModel(index, (m) => ({ ...m, defaults: { ...m.defaults, reasoning: { ...m.defaults.reasoning, mode: e.target.value as ModelDefinition["defaults"]["reasoning"]["mode"] } } }))}><option value="auto">Auto</option><option value="on">On</option><option value="off">Off</option></select>
                </Field>
                <Field title="Reasoning Effort" hint={!model.capabilities.supports_reasoning_effort ? t("providers.capabilityDisabled") : undefined}>
                  <select disabled={!model.capabilities.supports_reasoning_effort} value={model.defaults.reasoning.effort} onChange={(e) => updateModel(index, (m) => ({ ...m, defaults: { ...m.defaults, reasoning: { ...m.defaults.reasoning, effort: e.target.value as ModelDefinition["defaults"]["reasoning"]["effort"] } } }))}><option value="inherit">Provider default</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="extra_high">Extra high</option></select>
                </Field>
                <Field title="Reasoning Budget" hint={!model.capabilities.supports_reasoning_budget ? t("providers.capabilityDisabled") : t("providers.budgetHint")}>
                  <input disabled={!model.capabilities.supports_reasoning_budget} value={model.defaults.reasoning.budget ?? ""} onChange={(e) => updateModel(index, (m) => ({ ...m, defaults: { ...m.defaults, reasoning: { ...m.defaults.reasoning, budget: e.target.value === "" ? null : e.target.value === "auto" ? "auto" : Number(e.target.value) } } }))} />
                </Field>
                <Field title={t("providers.timeoutLabel")}><input type="number" min={1} max={7200} value={model.defaults.request_timeout ?? ""} onChange={(e) => updateModel(index, (m) => ({ ...m, defaults: { ...m.defaults, request_timeout: nullableNumber(e.target.value) } }))} /></Field>
                <Field title="Temperature" hint={!model.capabilities.supports_temperature ? t("providers.capabilityDisabled") : undefined}><input disabled={!model.capabilities.supports_temperature} type="number" min={0} max={2} step="0.01" value={model.defaults.generation.temperature ?? ""} onChange={(e) => updateModel(index, (m) => ({ ...m, defaults: { ...m.defaults, generation: { ...m.defaults.generation, temperature: nullableNumber(e.target.value) } } }))} /></Field>
                <Field title="Top P" hint={!model.capabilities.supports_top_p ? t("providers.capabilityDisabled") : undefined}><input disabled={!model.capabilities.supports_top_p} type="number" min={0.0001} max={1} step="0.01" value={model.defaults.generation.top_p ?? ""} onChange={(e) => updateModel(index, (m) => ({ ...m, defaults: { ...m.defaults, generation: { ...m.defaults.generation, top_p: nullableNumber(e.target.value) } } }))} /></Field>
                <Field title="Max output tokens" hint={!model.capabilities.supports_max_output_tokens ? t("providers.capabilityDisabled") : undefined}><input disabled={!model.capabilities.supports_max_output_tokens} type="number" min={1} value={model.defaults.generation.max_output_tokens ?? ""} onChange={(e) => updateModel(index, (m) => ({ ...m, defaults: { ...m.defaults, generation: { ...m.defaults.generation, max_output_tokens: nullableNumber(e.target.value) } } }))} /></Field>
              </div>
              <Field title="Extra Params JSON" hint={t("providers.extraHint")}><textarea rows={5} value={extraTexts[index] || "{}"} onChange={(e) => setExtraTexts(extraTexts.map((x, i) => i === index ? e.target.value : x))} /></Field>
              <button type="button" className="danger text" onClick={() => { setProviderEdit({ ...providerEdit, models: models.filter((_, i) => i !== index) }); setExtraTexts(extraTexts.filter((_, i) => i !== index)) }}>{t("providers.deleteModel")}</button>
            </details>
          ))}
          {error && <p className="error">{error}</p>}
          <div className="actions"><button disabled={busy} className="primary">{t("common.save")}</button><button type="button" onClick={() => { setProviderEdit(undefined); setKey("") }}>{t("common.cancel")}</button></div>
        </form>
      </section>
    </div>
  );
}

