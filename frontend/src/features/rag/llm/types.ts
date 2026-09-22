export type CheckResult = {
  models_ok: boolean;
  completion_ok: boolean;
  json_ok: boolean;
  error_code?: string;
  model: string;
  checked_at: number;
};
export type Config = {
  version: number;
  base_url: string;
  default_model: string;
  enabled: boolean;
  api_key_present: boolean;
  max_output_tokens: number;
  timeout_seconds: number;
  temperature: number | null;
  reasoning_effort: string | null;
  input_chars: number;
  last_check: CheckResult | null;
};
export type Prompt = {
  id: string;
  sequence: number;
  name: string;
  content: string;
  note: string;
  created_at: number;
  restored_from_id: string | null;
};
export type PromptList = {
  active_id: string;
  versions: Omit<Prompt, "content">[];
};
export type Codex = {
  installed: boolean;
  connected: boolean;
  account_count?: number;
  enabled_count?: number;
  selected_account_id?: string | null;
  revision?: string;
  accounts?: {
    id: string | null;
    email: string | null;
    status: "active" | "disabled" | "error" | "unavailable" | "unknown";
    enabled: boolean;
    manageable: boolean;
  }[];
  login_status?: string;
  error_code?: string;
};
export type Preview = {
  synthetic: boolean;
  model: string;
  messages: { role: string; content: string }[];
  elapsed_ms?: number;
  result?: { status: string; answer: string; citations: string[] };
};
