export type ModelRef = { provider: string; model: string } | null;
export type ReasoningMode = "auto" | "on" | "off";
export type ReasoningEffort = "inherit" | "low" | "medium" | "high" | "extra_high";
export type ReasoningConfig = { mode: ReasoningMode; effort: ReasoningEffort; budget: number | "auto" | null };
export type ReasoningOverride = { mode: ReasoningMode | null; effort: ReasoningEffort | null; budget: number | "auto" | "unset" | null };
export type GenerationConfig = { temperature: number | null; top_p: number | null; max_output_tokens: number | null };
export type ModelCapabilities = {
  supports_reasoning: boolean;
  supports_reasoning_effort: boolean;
  supports_reasoning_budget: boolean;
  supports_temperature: boolean;
  supports_top_p: boolean;
  supports_max_output_tokens: boolean;
};
export type ModelDefinition = {
  id: string;
  display_name: string | null;
  enabled: boolean;
  capabilities: ModelCapabilities;
  defaults: {
    reasoning: ReasoningConfig;
    generation: GenerationConfig;
    request_timeout: number | null;
    extra_params: Record<string, unknown>;
  };
};
export type StepConfig = {
  mode: "auto" | "fixed";
  fixed_steps: number | null;
  soft_limit: number | null;
  hard_limit: number | null;
  extension: number;
  loop_threshold: number;
};
export type TimeoutConfig = { model_request: number | null; tool_call: number | null; agent_task: number | null; sandbox_ttl: number | null };
export type TimeoutOverride = { model_request: number | null; tool_call: number | null; agent_task: number | null; sandbox_ttl: number | null };
export type AgentRuntimeOverride = {
  reasoning: ReasoningOverride;
  generation: GenerationConfig;
  steps: StepConfig | null;
  timeouts: TimeoutOverride;
};
export type ResolvedRuntime = {
  agent: string; provider: string; provider_name: string; provider_type: string; model: string; model_display_name: string;
  capabilities: ModelCapabilities; reasoning_mode: ReasoningMode; reasoning_effort: ReasoningEffort;
  reasoning_budget: number | "auto" | null; temperature: number | null; top_p: number | null; max_output_tokens: number | null;
  steps_mode: "auto" | "fixed"; soft_step_limit: number; hard_step_limit: number; step_extension: number; loop_threshold: number;
  model_timeout: number; tool_timeout: number; task_timeout: number; sandbox_ttl: number;
};
export type Provider = {
  id: string; name: string; type: "openai-compatible"; base_url: string; models: ModelDefinition[];
  has_key: boolean; api_key_masked: string;
};
export type Agent = {
  identifier: string; name: string; description: string; system_prompt: string; enabled: boolean; model: ModelRef | null;
  runtime: AgentRuntimeOverride;
};
export type Settings = {
  model: ModelRef; system_prompt: string; reasoning: ReasoningOverride; generation: GenerationConfig;
  steps: StepConfig; timeouts: TimeoutConfig;
};
export type Sandbox = { provider: "local" | "shipyard"; base_url: string; profile: string; has_key: boolean; api_key_masked: string };
export type Run = { id: string; started: number; ended: number | null; status: string; agent: string; model: string; result?: string; error?: string; usage_reported?: boolean; trigger: string; runtime_config?: ResolvedRuntime };
export type Dashboard = {
  tokens: Record<string, { total: number; input: number; output: number; reasoning: number; cached: number; models: Record<string, number> }>;
  counts: Record<string, number>;
  systems: Record<string, string>;
  automation: { repositories: number; issues: number; reviews: number; auto_merge: number };
  configuration_warnings: number;
  diagnostics: { timestamp: number; checks: Record<string, { ok: boolean; detail: string }> } | null;
};
export type SetupStatus = {
  version: string; schema: number; base_url: string; complete: boolean; repository_count: number;
  steps: Record<string, boolean>; checks: Record<string, { ok: boolean; detail: string }>;
};
export type GitHubConfig = { app_id: number; installation_id: number | null; api_url: string; has_private_key: boolean; private_key_masked: string; has_webhook_secret: boolean; webhook_secret_masked: string };
export type EmailConfig = { host: string; port: number; username: string; from_address: string; owner_email: string; mode: "starttls" | "ssl" | "plain"; enabled: boolean; has_password: boolean; password_masked: string };
export type Repository = { full_name: string; installation_id: number | null; enabled: boolean; auto_handle_issues: boolean; auto_review_prs: boolean; auto_merge: boolean; default_branch: string; install_command: string; test_command: string; lint_command: string; build_command: string; working_directory: string; additional_instructions: string };
export type Task = {
  id: string; kind: string; repository: string; number: number; event: string; status: string; created: number; updated: number; attempts: number;
  summary?: string; error?: string; failure?: { stage: string; exception_type: string; message: string; attempt: number; retry: number };
  triage?: { classification?: string; risk?: string; reason?: string; affected_components?: string[] };
  pull_url?: string; timeline?: { timestamp: number; kind: string; data: Record<string, unknown> }[];
};
export type PluginConfigField = { type: "string" | "boolean" | "integer" | "select" | "string_list" | "secret"; title: string; description: string; required: boolean; default: unknown; options: string[] };
export type Plugin = {
  id: string; name: string; version: string; publisher: string; license: string; description: string; api_version: number;
  capabilities: string[]; config_schema: Record<string, PluginConfigField>; config: Record<string, unknown>;
  enabled: boolean; runtime_status: "running" | "stopped" | "error"; error: string;
  connection_status: "connected" | "disconnected"; connected_instance: string; last_heartbeat: number | null;
  event_subscriptions: string[]; has_readme: boolean;
};

export const emptyCapabilities = (): ModelCapabilities => ({
  supports_reasoning: false, supports_reasoning_effort: false, supports_reasoning_budget: false,
  supports_temperature: false, supports_top_p: false, supports_max_output_tokens: false,
});
export const emptyModel = (): ModelDefinition => ({
  id: "", display_name: null, enabled: true, capabilities: emptyCapabilities(),
  defaults: { reasoning: { mode: "auto", effort: "inherit", budget: null }, generation: { temperature: null, top_p: null, max_output_tokens: null }, request_timeout: null, extra_params: {} },
});
export const emptyRuntime = (): AgentRuntimeOverride => ({
  reasoning: { mode: null, effort: null, budget: null }, generation: { temperature: null, top_p: null, max_output_tokens: null },
  steps: null, timeouts: { model_request: null, tool_call: null, agent_task: null, sandbox_ttl: null },
});
