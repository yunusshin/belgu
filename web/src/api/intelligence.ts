import type { ResearchFilters } from '../features/researchState';
export interface ScopedEvidenceRef {
  investigation_id: string;
  evidence_id: string;
  subject: { kind: string; value: string };
  kind: string;
  provider: string;
  source_ref: string;
  observed_at: string | null;
  retrieved_at: string;
  payload?: Record<string, unknown>;
  projection_truncated?: boolean;
}
export interface MemoryItem {
  investigation_id: string;
  title: string;
  brand_name: string;
  workflow: string;
  disposition: string;
  decision: { value: string; note: string; created_at: string } | null;
  score: number;
  priority: 'high' | 'medium' | 'low';
  reasons: {
    kind: string;
    value: string;
    label: string;
    weight: number;
    discounted: boolean;
    detail: string;
    evidence_refs: ScopedEvidenceRef[];
  }[];
  evidence_refs: ScopedEvidenceRef[];
}
export interface MemoryResponse {
  items: MemoryItem[];
  total_unique: number;
  next_cursor: string | null;
  coverage: {
    truncated: boolean;
    cases_scanned: number;
    current_observations_scanned: number;
    foreign_observations_scanned: number;
  };
  limitations: string[];
}
export type AssistantAction =
  | { type: 'apply_filters'; label: string; filters: Partial<ResearchFilters> }
  | { type: 'open_evidence'; label: string; investigation_id: string; evidence_id: string };
export interface AssistantTurn {
  id: string;
  investigation_id: string;
  message: string;
  created_at: string;
  answer: string;
  claims: { text: string; kind: 'observation' | 'hypothesis'; evidence_refs: ScopedEvidenceRef[] }[];
  actions: AssistantAction[];
  uncertainties: string[];
  model: {
    id: string;
    recorded_demo: boolean;
    prompt_version: string;
    runtime_version: string | null;
    input_tokens: number | null;
    output_tokens: number | null;
  };
  snapshot: {
    id: string;
    evidence_refs: ScopedEvidenceRef[];
    omissions: {
      retrieval_capped: boolean;
      context_evidence: number;
      history_capped: boolean;
      token_budget_evidence: number;
      token_budget_history: number;
      memory_cases_omitted: number;
      candidates_omitted?: number;
      candidates_retrieval_capped?: boolean;
    };
  };
}
export interface AssistantHistory {
  items: AssistantTurn[];
  next_cursor: string | null;
}
