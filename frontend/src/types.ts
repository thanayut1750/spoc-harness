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
  message: string;
  kr_id?: string;
  [key: string]: unknown;
}
export interface Run {
  run_id: string;
  status: string;
  user_request: string;
  created_at?: string;
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
}
export interface Artifact {
  artifact_id: string;
  name: string;
  media_type: string;
  size?: number;
  kr_id?: string;
}
export interface RunInput {
  user_request: string;
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
