export type Activity =
  | "idle"
  | "planning"
  | "reading"
  | "writing"
  | "executing"
  | "reviewing"
  | "waiting"
  | "completed"
  | "error";
export interface AgentActivity {
  seq?: number;
  agent_id: string;
  original_agent_id?: string;
  source?: string;
  activity: Activity;
  summary?: string;
  display_name?: string;
  name?: string;
  department?: string;
  run_id?: string;
  kr_id?: string;
  timestamp?: string;
  data?: Record<string, unknown>;
}
export interface ActivityEvent extends AgentActivity {
  event_id: string;
  seq: number;
  source: string;
  timestamp: string;
}
export interface KeyResult {
  kr_id: string;
  description: string;
  target_department: string;
  acceptance_criteria: string[];
  dependency_kr_ids: string[];
  version: number;
}
export interface Objective {
  objective_id: string;
  title: string;
  key_results: KeyResult[];
}
export interface Evaluation {
  score?: number;
  approved?: boolean;
  passed_constitution?: boolean;
  passed_kr_criteria?: boolean;
  criterion_results?: Record<string, boolean>;
  feedback?: string;
  reasoning?: string;
  [key: string]: unknown;
}
export interface Outcome {
  deliverable?: unknown;
  evaluation?: Evaluation;
  escalation?: unknown;
}
export interface Review {
  interrupt_id: string;
  kind: string;
  message?: string;
  reason?: string;
  kr_id?: string;
  kr_ids?: string[];
  allowed_actions?: ReviewAction[];
  context?: ReviewContext;
  [key: string]: unknown;
}
export interface ReviewAttempt {
  attempt_id: string;
  kr_id?: string;
  version?: number;
  epoch?: number;
  execution_attempt?: number;
  stage?: string;
  work_package_id?: string;
  role?: string;
  task?: string;
  acceptance_criteria?: string[];
  summary?: string;
  artifact_ids?: string[];
  evidence?: string[];
  evaluation?: Evaluation | null;
  reason?: string;
  approved?: boolean;
  timestamp?: string;
}
export interface ReviewKeyResult {
  kr_id: string;
  version?: number;
  epoch?: number;
  department?: string;
  description: string;
  acceptance_criteria: string[];
  status?: string;
  reason?: string;
  evaluation?: Evaluation | null;
  attempts?: ReviewAttempt[];
  history_complete?: boolean;
  summary?: string;
  artifact_ids?: string[];
  evidence?: string[];
}
export interface ReviewContext {
  mission?: string;
  constitution?: Run["constitution"];
  key_results?: ReviewKeyResult[];
  blockers?: {
    kr_id?: string;
    kind?: string;
    reason?: string;
    classification?: string;
  }[];
  retry_summary?: {
    automatic_replans_used?: number;
    automatic_replans_limit?: number;
    revision_limit?: number;
    attempts_recorded?: number;
  };
  action_implications?: Partial<Record<ReviewAction, string>>;
  truncated?: boolean;
}
export interface Run {
  run_id: string;
  status: string;
  user_request: string;
  created_at?: string;
  model_config?: ModelConfig;
  agent_model_configs?: Record<string, ModelConfig>;
  triage?: { mode: string; departments: string[]; reason: string };
  epochs?: Record<string, number>;
  objectives?: Objective[];
  constitution?: {
    mission_statement?: string;
    prohibited_actions?: string[];
    compliance_rules?: string[];
  };
  progress?: Record<string, string | { status: string }>;
  outcomes?: Record<string, Outcome>;
  review?: Review;
  report?: string;
  error?: string | null;
}
export interface Artifact {
  artifact_id: string;
  name: string;
  media_type: string;
  size?: number;
  kr_id?: string;
  kind?: string;
  epoch?: number;
  version?: number;
  created_at?: string;
  exit_code?: number;
}
export interface RunInput {
  user_request: string;
  model_config?: ModelConfig;
  agent_model_configs?: Record<string, ModelConfig>;
  workspace_path?: string;
  constitution?: {
    mission_statement: string;
    prohibited_actions: string[];
    compliance_rules: string[];
    max_revision_loops: number;
  };
}
export type ReviewAction =
  "provide_context" | "revise_kr" | "retry_operation" | "abort" | "continue";
export interface ResumeInput {
  interrupt_id: string;
  action: ReviewAction;
  context?: string;
  kr_id?: string;
  description?: string;
  acceptance_criteria?: string[];
}
export interface ModelConfig {
  provider: string;
  model: string;
  reasoning_effort: string;
}
export interface ProviderConfig {
  id: string;
  label: string;
  configured: boolean;
  default_model: string;
  reasoning_efforts: string[];
}
export interface WorkspaceSettings {
  defaults: ModelConfig;
  model_config: ModelConfig;
  agent_model_configs?: Record<string, ModelConfig>;
  providers: ProviderConfig[];
  triage: { model: string; configured: boolean };
  worker_timeout: number;
}
export interface RegenesisResult {
  status: "reset";
  settings: WorkspaceSettings;
  removed_runs: number;
}
