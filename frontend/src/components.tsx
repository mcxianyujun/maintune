import type { ReactNode } from "react";
import type { ModelRef, Provider } from "./types";
import { useI18n } from "./i18n";
import type { MessageKey } from "./i18n/resources";
export const statusKeys: Record<string, MessageKey> = {
  completed: "status.completed", failed: "status.failed", running: "status.running", interrupted: "status.interrupted",
  waiting_for_owner: "status.waiting_for_owner", waiting_for_contributor: "status.waiting_for_contributor", non_actionable: "status.non_actionable", already_resolved: "status.already_resolved", closed_without_change: "status.closed_without_change",
  reviewed: "status.reviewed", pr_created: "status.pr_created", merged: "status.merged", queued: "status.queued", failed_agent: "status.failed_agent",
  failed_environment: "status.failed_environment", failed_tests: "status.failed_tests", failed_review: "status.failed_review",
  bot_merge_deferred: "status.bot_merge_deferred", bot_merged: "status.bot_merged", draft_skipped: "status.draft_skipped", unsupported: "status.unsupported",
};
export function Field({
  title,
  children,
  hint,
}: {
  title: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <label className="field">
      <span>{title}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}
export function ModelSelect({
  value,
  onChange,
  providers,
  inherit = false,
}: {
  value: ModelRef;
  onChange: (v: ModelRef) => void;
  providers: Provider[];
  inherit?: boolean;
}) {
  const { t } = useI18n();
  return (
    <select
      aria-label={t("common.model")}
      value={value ? JSON.stringify(value) : ""}
      onChange={(e) =>
        onChange(e.target.value ? JSON.parse(e.target.value) : null)
      }
    >
      <option value="">
        {inherit ? t("model.followMain") : t("model.select")}
      </option>
      {providers.map((p) => (
        <optgroup key={p.id} label={p.name}>
          {p.models.filter((m) => m.enabled).map((m) => (
            <option
              key={m.id}
              value={JSON.stringify({ provider: p.id, model: m.id })}
            >
              {p.name} / {m.display_name || m.id}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}
