import { api } from "../api";
import type { ConsoleState } from "../useConsole";
import { useI18n } from "../i18n";
export function AgentsPage({ c }: { c: ConsoleState }) {
  const { t } = useI18n();
  const {
    page,
    busy,
    providers,
    agents,
    runtimeConfigs,
    setAgentEdit,
    setAgentNew,
    load,
    act,
  } = c;
  return (
    <>
      {page === "Agents" && (
        <div className="cards agent-cards">
          {agents.map((a) => (
            <section key={a.identifier}>
              <div className="section-head">
                <code>{a.identifier}</code>
                <span className={"badge " + (a.enabled ? "completed" : "")}>
                  {a.enabled ? t("common.enabled") : t("common.disabled")}
                </span>
              </div>
              <h2>{a.name}</h2>
              <p>{a.description}</p>
              <p className="muted">
                ◈{" "}
                {a.model
                  ? `${providers.find((p) => p.id === a.model?.provider)?.name} / ${a.model.model}`
                  : "Follow Main Model"}
              </p>
              {runtimeConfigs[a.identifier] && <div className="runtime-summary">
                <span>Reasoning {runtimeConfigs[a.identifier].reasoning_mode} / {runtimeConfigs[a.identifier].reasoning_effort}</span>
                <span>{runtimeConfigs[a.identifier].steps_mode} · {runtimeConfigs[a.identifier].soft_step_limit}/{runtimeConfigs[a.identifier].hard_step_limit} steps</span>
                <span>{runtimeConfigs[a.identifier].model_timeout}s model · {runtimeConfigs[a.identifier].tool_timeout}s tool · {runtimeConfigs[a.identifier].task_timeout}s task</span>
              </div>}
              <div className="actions">
                <button
                  onClick={() => {
                    setAgentNew(false);
                    setAgentEdit(a);
                  }}
                >
                  {t("agents.edit")}
                </button>
                <button
                  className="text"
                  disabled={busy}
                  onClick={() =>
                    act(async () => {
                      await api(`/agents/${a.identifier}`, "PUT", {
                        ...a,
                        enabled: !a.enabled,
                      });
                      await load();
                    })
                  }
                >
                  {a.enabled ? t("common.disable") : t("common.enable")}
                </button>
                <button
                  className="text danger"
                  onClick={() => {
                    if (confirm(t("agents.deleteConfirm")))
                      act(async () => {
                        await api(`/agents/${a.identifier}`, "DELETE");
                        await load();
                      });
                  }}
                >
                  {t("agents.delete")}
                </button>
              </div>
            </section>
          ))}
        </div>
      )}
    </>
  );
}
