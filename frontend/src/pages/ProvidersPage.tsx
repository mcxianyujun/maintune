import { api } from "../api";
import type { ConsoleState } from "../useConsole";
import { EmptyState, NavMascotIcon } from "../assets/theme/ThemeArt";
import { useI18n } from "../i18n";
export function ProvidersPage({ c }: { c: ConsoleState }) {
  const { t } = useI18n();
  const {
    page,
    setNotice,
    busy,
    providers,
    load,
    act,
    editProvider,
  } = c;
  return (
    <>
      {page === "模型" && (
        <div className="cards">
          {providers.map((p) => (
            <section key={p.id}>
              <div className="section-head">
                <div className="provider-icon"><NavMascotIcon kind="models"/></div>
                <span className="badge">OpenAI-compatible</span>
              </div>
              <h2>{p.name}</h2>
              <p className="muted break">{p.base_url}</p>
              <p>
                {p.models.map((m) => (
                  <span className="model-tag" key={m.id}>
                    {m.display_name || m.id}{!m.enabled && t("providers.disabledSuffix")}
                  </span>
                ))}
              </p>
              <p className="muted">API Key {p.api_key_masked || t("providers.keyUnset")}</p>
              <div className="actions">
                <button onClick={() => editProvider(p)}>{t("common.edit")}</button>
                <button
                  disabled={busy}
                  onClick={() =>
                    act(async () => {
                      const r = await api<{ models: string[] }>(
                        `/providers/${p.id}/test`,
                        "POST",
                      );
                      setNotice(
                        t("providers.connected", {count: r.models.length, models: r.models.slice(0, 8).join(", ")}),
                      );
                    })
                  }
                >
                  {t("integration.testConnection")}
                </button>
                <button
                  className="danger text"
                  onClick={() => {
                    if (confirm(t("providers.deleteConfirm")))
                      act(async () => {
                        await api(`/providers/${p.id}`, "DELETE");
                        await load();
                      });
                  }}
                >
                  {t("providers.delete")}
                </button>
              </div>
            </section>
          ))}
          {!providers.length && (
            <section><EmptyState title={t("providers.empty")} action={<button onClick={() => editProvider()}>{t("providers.add")}</button>}>{t("providers.emptyHint")}</EmptyState></section>
          )}
        </div>
      )}
    </>
  );
}
