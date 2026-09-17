import { api } from "../api";
import { statusKeys } from "../components";
import { useI18n } from "../i18n";
import type { ConsoleState } from "../useConsole";
import type { Run, Sandbox } from "../types";
export function RunDialog({ c }: { c: ConsoleState }) {
  const { t } = useI18n();
  const { error, detail, setDetail } = c;
  return (
    <>
      {detail && (
        <div className="modal-overlay">
          <section className="modal">
            <div className="section-head">
              <h2>{t("runs.detail")}</h2>
              <button onClick={() => setDetail(undefined)}>{t("common.close")}</button>
            </div>
            <p className="muted break">{detail.id}</p>
            <span className={"badge " + detail.status}>
              {statusKeys[detail.status] ? t(statusKeys[detail.status]) : detail.status}
            </span>
            <p>
              {detail.agent} · {detail.model}
            </p>
            {detail.usage_reported === false && (
              <div className="info">
                {t("runs.usageMissing")}
              </div>
            )}
            <pre>{detail.result ?? detail.error ?? t("runs.inProgress")}</pre>
            <p className="muted">{t("runs.noTools")}</p>
          </section>
        </div>
      )}
    </>
  );
}
