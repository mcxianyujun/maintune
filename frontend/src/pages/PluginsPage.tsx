import { useState } from "react";
import { api } from "../api";
import type { ConsoleState } from "../useConsole";
import { MascotScene } from "../assets/theme/ThemeArt";
import { useI18n } from "../i18n";
import type { Plugin } from "../types";
export function PluginsPage({ c }: { c: ConsoleState }) {
  const { t } = useI18n();
  const { page, plugins } = c;
  const [filename, setFilename] = useState("");
  const [editing, setEditing] = useState<Record<string, Record<string, unknown>>>({});
  const [revealed, setRevealed] = useState<Record<string, string>>( {} );
  const update = (plugin: Plugin, key: string, value: unknown) => setEditing((current) => ({ ...current, [plugin.id]: { ...plugin.config, ...current[plugin.id], [key]: value } }));
  const refresh = () => c.load();
  return (
    <>
      {page === "扩展" && (
        <div className="plugin-page">
          <section className="experimental-panel">
            <p className="eyebrow">PLUGIN API V1 · EXPERIMENTAL</p>
            <h2>{t("plugins.title")}</h2>
            <p>{t("plugins.description")}</p>
            <span className="badge warning-badge">{t("plugins.warning")}</span>
            <div className="actions">
              <input aria-label={t("plugins.packageFile")} value={filename} onChange={(event) => setFilename(event.target.value)} placeholder="example.mtp" />
              <button disabled={!filename} onClick={() => c.act(async () => { await api(`/plugins/install/${encodeURIComponent(filename)}`, "POST"); setFilename(""); await refresh(); }, t("plugins.installed"))}>{t("plugins.install")}</button>
              <button className="secondary" onClick={() => c.act(async () => { await api("/plugins/scan"); await refresh(); }, t("plugins.scanned"))}>{t("plugins.rescan")}</button>
            </div>
            <small>{t("plugins.inboxHint")}</small>
          </section>
          {!plugins.length && <section className="empty"><MascotScene variant="empty" compact/><h3>{t("plugins.empty")}</h3><p>{t("plugins.emptyHint")}</p></section>}
          <div className="plugin-list">
            {plugins.map((plugin) => {
              const values = { ...plugin.config, ...editing[plugin.id] };
              return <section key={plugin.id} className="plugin-card">
                <div className="section-head"><div><p className="eyebrow">{plugin.id}</p><h2>{plugin.name}</h2><p>{plugin.description}</p></div><div className="actions"><span className={`badge ${plugin.runtime_status}`}>{plugin.runtime_status}</span><span className={`badge ${plugin.connection_status === "connected" ? "completed" : "pending"}`}>{plugin.connection_status}</span></div></div>
                <div className="plugin-meta"><span>v{plugin.version}</span><span>API v{plugin.api_version}</span><span>{plugin.publisher}</span></div>
                {plugin.error && <div className="alert error">{plugin.error}</div>}
                <div className="status-grid"><div><strong>{t("plugins.instance")}</strong><small>{plugin.connected_instance || "—"}</small></div><div><strong>{t("plugins.heartbeat")}</strong><small>{plugin.last_heartbeat ? new Date(plugin.last_heartbeat * 1000).toLocaleString() : "—"}</small></div></div>
                <h3>{t("plugins.config")}</h3>
                <div className="repo-form">
                  {Object.entries(plugin.config_schema).map(([key, field]) => <label className="field" key={key}><span>{field.title}{field.required ? " *" : ""}</span>
                    {field.type === "boolean" ? <input type="checkbox" checked={Boolean(values[key])} onChange={(event) => update(plugin, key, event.target.checked)} /> : field.type === "select" ? <select value={String(values[key] ?? "")} onChange={(event) => update(plugin, key, event.target.value)}>{field.options.map((option) => <option key={option}>{option}</option>)}</select> : <input type={field.type === "secret" ? "password" : field.type === "integer" ? "number" : "text"} value={field.type === "string_list" ? (Array.isArray(values[key]) ? values[key].join(", ") : "") : String(values[key] ?? "")} onChange={(event) => update(plugin, key, field.type === "string_list" ? event.target.value.split(",").map((item) => item.trim()).filter(Boolean) : field.type === "integer" ? Number(event.target.value) : event.target.value)} />}
                    {field.description && <small>{field.description}</small>}
                  </label>)}
                </div>
                {revealed[plugin.id] && <div className="alert"><strong>{t("plugins.newToken")}</strong><code>{revealed[plugin.id]}</code></div>}
                <div className="actions"><button onClick={() => c.act(async () => { await api(`/plugins/${plugin.id}/config`, "PUT", values); setEditing((current) => ({ ...current, [plugin.id]: {} })); await refresh(); }, t("common.saved"))}>{t("common.save")}</button>
                  {plugin.config_schema.bridge_token?.type === "secret" && <button className="secondary" onClick={() => c.act(async () => { const result = await api<{value:string}>(`/plugins/${plugin.id}/secrets/bridge_token/regenerate`, "POST"); setRevealed((current) => ({ ...current, [plugin.id]: result.value })); await refresh(); })}>{t("plugins.regenerate")}</button>}
                  <button className="secondary" onClick={() => c.act(async () => { await api(`/plugins/${plugin.id}/${plugin.enabled ? "disable" : "enable"}`, "POST"); await refresh(); })}>{plugin.enabled ? t("common.disable") : t("common.enable")}</button>
                </div>
                <small>{t("plugins.capabilities")}: {plugin.capabilities.join(", ") || "—"}</small>
              </section>;
            })}
          </div>
        </div>
      )}
    </>
  );
}
