import { api } from "../api";
import { Field } from "../components";
import { useI18n } from "../i18n";
import type { ConsoleState } from "../useConsole";
import type { Run, Sandbox } from "../types";
export function RunsPage({ c }: { c: ConsoleState }) {
  const { t } = useI18n();
  const {
    page,
    busy,
    agents,
    runs,
    settings,
    prompt,
    setPrompt,
    runAgent,
    setRunAgent,
    key,
    setDetail,
    load,
    act,
    runTable,
  } = c;
  return (
    <>
      {page === "运行记录" && (
        <>
          <section>
            <h2>{t("runs.diagnostic")}</h2>
            <p className="muted">
              {t("runs.description")}
            </p>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                act(async () => {
                  const r = await api<Run>("/runs", "POST", {
                    agent: runAgent,
                    prompt,
                  });
                  setDetail(r);
                  await load();
                });
              }}
            >
              <Field title={t("runs.agent")}>
                <select
                  value={runAgent}
                  onChange={(e) => setRunAgent(e.target.value)}
                >
                  <option value="main">{t("runs.mainAgent")}</option>
                  {agents
                    .filter((a) => a.enabled)
                    .map((a) => (
                      <option key={a.identifier} value={a.identifier}>
                        {a.name}
                      </option>
                    ))}
                </select>
              </Field>
              <Field title={t("runs.input")}>
                <textarea
                  required
                  rows={3}
                  maxLength={16000}
                  placeholder={t("runs.placeholder")}
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                />
              </Field>
              <button className="primary" disabled={busy || !settings?.model}>
                {busy ? t("runs.executing") : t("runs.run")}
              </button>
            </form>
          </section>
          <section>
            <div className="section-head">
              <h2>{t("runs.history")}</h2>
              <small>{t("runs.latest")}</small>
            </div>
            {runTable(runs)}
          </section>
        </>
      )}
    </>
  );
}
