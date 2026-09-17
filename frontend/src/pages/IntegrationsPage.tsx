import { useState } from "react";
import { api } from "../api";
import { Field } from "../components";
import { useI18n } from "../i18n";
import type { Repository } from "../types";
import type { ConsoleState } from "../useConsole";

const blankRepo: Repository = { full_name: "", installation_id: null, enabled: true, auto_handle_issues: true, auto_review_prs: true, auto_merge: false, default_branch: "main", install_command: "", test_command: "", lint_command: "", build_command: "", working_directory: ".", additional_instructions: "" };

export function IntegrationsPage({ c }: { c: ConsoleState }) {
  const { t } = useI18n();
  const { page, github, setGithub, email, setEmail, repositories, busy, act, load, setNotice } = c;
  const [privateKey, setPrivateKey] = useState(""), [webhookSecret, setWebhookSecret] = useState(""), [password, setPassword] = useState(""), [repo, setRepo] = useState(blankRepo);
  if (!["GitHub", "仓库", "系统设置"].includes(page) || !github || !email) return null;

  if (page === "GitHub") return <section><h2>GitHub App</h2><p className="muted">{t("integration.githubSecret")}</p>
    <form onSubmit={event => { event.preventDefault(); act(async () => { await api("/github", "PUT", { app_id: github.app_id, installation_id: github.installation_id, api_url: github.api_url, ...(privateKey ? { private_key: privateKey } : {}), ...(webhookSecret ? { webhook_secret: webhookSecret } : {}) }); setPrivateKey(""); setWebhookSecret(""); await load(); }, t("wizard.githubSaved")); }}>
      <Field title="App ID"><input required type="number" min={1} value={github.app_id || ""} onChange={event => setGithub({...github, app_id: Number(event.target.value)})}/></Field>
      <Field title={t("integration.installationDefault")} hint={t("integration.installationHint")}><input type="number" min={1} value={github.installation_id ?? ""} onChange={event => setGithub({...github, installation_id: event.target.value ? Number(event.target.value) : null})}/></Field>
      <Field title="Private key PEM"><textarea rows={5} autoComplete="off" placeholder={github.private_key_masked || "-----BEGIN RSA PRIVATE KEY-----"} value={privateKey} onChange={event => setPrivateKey(event.target.value)}/></Field>
      <Field title="Webhook Secret"><input type="password" autoComplete="off" placeholder={github.webhook_secret_masked} value={webhookSecret} onChange={event => setWebhookSecret(event.target.value)}/></Field>
      <div className="actions"><button disabled={busy} className="primary">{t("common.save")}</button><button type="button" disabled={busy} onClick={() => act(async () => { const result = await api<{installations:{id:number;account:string}[]}>("/github/test", "POST"); setNotice(t("integration.connected", {accounts: result.installations.map(item => `${item.account} (${item.id})`).join(", ")})); })}>{t("integration.testConnection")}</button></div>
    </form>
  </section>;

  if (page === "系统设置") return <section><h2>{t("integration.email")}</h2><p className="muted">{t("integration.emailHint")}</p>
    <form onSubmit={event => { event.preventDefault(); act(async () => { await api("/email", "PUT", {host:email.host,port:email.port,username:email.username,from_address:email.from_address,owner_email:email.owner_email,mode:email.mode,enabled:email.enabled,...(password ? {password} : {})}); setPassword(""); await load(); }, t("common.saved")); }}>
      <Field title="SMTP Host"><input required value={email.host} onChange={event => setEmail({...email, host:event.target.value})}/></Field>
      <div className="inline-fields"><Field title="Port"><input type="number" value={email.port} onChange={event => setEmail({...email, port:Number(event.target.value)})}/></Field><Field title={t("integration.encryption")}><select value={email.mode} onChange={event => setEmail({...email, mode:event.target.value as typeof email.mode})}><option value="starttls">STARTTLS</option><option value="ssl">SSL</option><option value="plain">Plain</option></select></Field></div>
      <Field title="Username"><input value={email.username} onChange={event => setEmail({...email, username:event.target.value})}/></Field><Field title="Password"><input type="password" autoComplete="off" placeholder={email.password_masked} value={password} onChange={event => setPassword(event.target.value)}/></Field>
      <Field title="From"><input required type="email" value={email.from_address} onChange={event => setEmail({...email, from_address:event.target.value})}/></Field><Field title="Owner email"><input required type="email" value={email.owner_email} onChange={event => setEmail({...email, owner_email:event.target.value})}/></Field>
      <label className="toggle"><input type="checkbox" checked={email.enabled} onChange={event => setEmail({...email, enabled:event.target.checked})}/> {t("integration.enableNotifications")}</label><button disabled={busy} className="primary">{t("integration.saveEmail")}</button>
    </form>
  </section>;

  return <section><div className="section-head"><div><h2>{t("integration.repositories")}</h2><p className="muted">{t("integration.repoHint")}</p></div></div>
    <form onSubmit={event => { event.preventDefault(); const parts=repo.full_name.split("/"); if(parts.length!==2) return; act(async()=>{await api(`/repositories/${encodeURIComponent(parts[0])}/${encodeURIComponent(parts[1])}`,"PUT",repo);setRepo(blankRepo);await load();},t("wizard.repoSaved"));}}>
      <div className="repo-form"><Field title="owner/repository"><input required value={repo.full_name} onChange={event=>setRepo({...repo,full_name:event.target.value})}/></Field><Field title="Installation ID"><input type="number" value={repo.installation_id??""} onChange={event=>setRepo({...repo,installation_id:event.target.value?Number(event.target.value):null})}/></Field><Field title={t("wizard.defaultBranch")}><input required value={repo.default_branch} onChange={event=>setRepo({...repo,default_branch:event.target.value})}/></Field><Field title={t("wizard.testCommand")}><input value={repo.test_command} onChange={event=>setRepo({...repo,test_command:event.target.value})}/></Field></div>
      <details><summary>{t("integration.commands")}</summary><div className="repo-form"><Field title={t("integration.installCommand")}><input value={repo.install_command} onChange={event=>setRepo({...repo,install_command:event.target.value})}/></Field><Field title={t("integration.lintCommand")}><input value={repo.lint_command} onChange={event=>setRepo({...repo,lint_command:event.target.value})}/></Field><Field title={t("integration.buildCommand")}><input value={repo.build_command} onChange={event=>setRepo({...repo,build_command:event.target.value})}/></Field><Field title={t("integration.workingDirectory")}><input value={repo.working_directory} onChange={event=>setRepo({...repo,working_directory:event.target.value})}/></Field></div><Field title={t("integration.constraints")}><textarea rows={4} value={repo.additional_instructions} onChange={event=>setRepo({...repo,additional_instructions:event.target.value})}/></Field></details>
      <div className="actions"><label className="toggle"><input type="checkbox" checked={repo.auto_handle_issues} onChange={event=>setRepo({...repo,auto_handle_issues:event.target.checked})}/>{t("integration.handleIssues")}</label><label className="toggle"><input type="checkbox" checked={repo.auto_review_prs} onChange={event=>setRepo({...repo,auto_review_prs:event.target.checked})}/>{t("integration.reviewPrs")}</label><label className="toggle"><input type="checkbox" checked={repo.auto_merge} onChange={event=>setRepo({...repo,auto_merge:event.target.checked})}/>{t("integration.autoMerge")}</label><button disabled={busy} className="primary">{t("integration.addUpdate")}</button></div>
    </form>
    <div className="table-wrap"><table><thead><tr><th>{t("integration.repository")}</th><th>{t("integration.branch")}</th><th>{t("integration.automation")}</th><th>{t("integration.tests")}</th><th/></tr></thead><tbody>{repositories.map(item=><tr key={item.full_name}><td><strong>{item.full_name}</strong><small>Installation {item.installation_id??t("common.default")}</small></td><td>{item.default_branch}</td><td>{item.auto_handle_issues?"Issue ":""}{item.auto_review_prs?"PR":""}</td><td>{item.test_command||t("common.notConfigured")}</td><td><button className="text" onClick={()=>setRepo(item)}>{t("common.edit")}</button><button className="text danger" onClick={()=>{const [owner,name]=item.full_name.split("/");act(async()=>{await api(`/repositories/${encodeURIComponent(owner)}/${encodeURIComponent(name)}`,"DELETE");await load();},t("integration.removed"));}}>{t("common.remove")}</button></td></tr>)}</tbody></table></div>
  </section>;
}
