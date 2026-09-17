import type { ConsoleState } from "../useConsole";
import { MascotScene } from "../assets/theme/ThemeArt";
import { useI18n } from "../i18n";
export function PluginsPage({ c }: { c: ConsoleState }) {
  const { t } = useI18n();
  const { page } = c;
  return (
    <>
      {page === "扩展" && (
        <section className="empty experimental-panel">
          <MascotScene variant="empty" compact/>
          <p className="eyebrow">EXPERIMENTAL</p>
          <h2>{t("plugins.title")}</h2>
          <p>{t("plugins.description")}</p>
          <span className="badge warning-badge">{t("plugins.warning")}</span>
          <div className="actions"><button disabled>{t("plugins.install")}</button><button disabled>{t("plugins.browse")}</button></div>
        </section>
      )}
    </>
  );
}
