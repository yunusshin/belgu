import type { Investigation, Job } from './types';
import type { ResearchFilters } from '../features/researchState';
export type WorkbenchProps = {
  inv: Investigation;
  refresh: number;
  onChange: () => void;
  onJob: (job: Job) => void;
  onEvidence: (id: string, investigationId?: string) => void;
  onResearchFilter?: (filters: Partial<ResearchFilters>) => void;
};
export interface CaptureInput {
  tag?: string;
  type?: string;
  name?: string;
  id?: string;
  placeholder?: string;
  autocomplete?: string;
  required?: boolean;
  disabled?: boolean;
  visible?: boolean;
}
export interface CaptureForm {
  action?: string;
  method?: string;
  inputs?: CaptureInput[];
}
export interface Capture {
  profile?: 'desktop' | 'mobile';
  profile_label?: string;
  legacy_profile?: boolean;
  viewport?: { width: number; height: number };
  user_agent?: string | null;
  retrieved_at?: string;
  id: string;
  evidence_id: string;
  url: string;
  final_url: string;
  observed_at: string;
  artifact_id: string;
  image_url: string;
  text: string;
  ocr_text: string;
  ocr_status: string;
  forms: CaptureForm[];
  status_code: number | null;
  limitations?: string[];
  text_truncated?: boolean;
  forms_truncated?: boolean;
  inputs_truncated?: boolean;
  inputs?: CaptureInput[];
  ocr?: { engine?: string; languages?: string; source?: string; limitations?: string[] };
}
export interface Captures {
  failures?: {
    evidence_id: string;
    profile?: 'desktop' | 'mobile';
    profile_label?: string;
    reason: string;
    status: string;
    retrieved_at?: string;
  }[];
  items: Capture[];
  references: { id: string; image_url: string; created_at: string }[];
  capabilities: { status: string; message: string; browser_available?: boolean; ocr_available: boolean };
}
export interface Candidate {
  entity_id: string;
  domain: string;
  score: number;
  priority: 'high' | 'medium' | 'low';
  reasons: { label: string; strength: 'strong' | 'moderate' | 'weak'; evidence_ids: string[] }[];
  limitations: string[];
  evidence_ids: string[];
}
export interface Candidates {
  items: Candidate[];
  total_unique: number;
  next_cursor?: string | null;
}
export interface CollectionRun {
  id: string;
  created_at: string;
  status: string;
  evidence_count: number;
  approximate: boolean;
}
export interface Runs {
  items: CollectionRun[];
  total_unique: number;
}
export interface RunChanges {
  before: string | null;
  after: string | null;
  changes: {
    kind: 'new' | 'changed' | 'not_observed';
    subject: unknown;
    field: string;
    before: unknown;
    after: unknown;
    evidence_ids: string[];
    message: string;
  }[];
  counts: { new: number; changed: number; not_observed: number };
  limitations: string[];
}
export interface Grounding {
  analysis_id: string;
  summary: string;
  claims: {
    index: number;
    text: string;
    kind: string;
    support: {
      id: string;
      subject: unknown;
      provider: string;
      observed_at: string | null;
      retrieved_at: string | null;
      fields: { path: string; value: unknown }[];
    }[];
    warnings: string[];
  }[];
  limitations: string[];
}
export interface Watch {
  id: string;
  entity_id: string | null;
  target: string;
  enabled: boolean;
  interval_minutes: number;
  next_run_at: string | null;
  last_job_id: string | null;
  last_error: string | null;
}
export interface Watches {
  items: Watch[];
  alerts: {
    id: string;
    kind: string;
    message: string;
    job_id: string | null;
    read: boolean;
    created_at: string;
  }[];
}
export interface StoryRequest {
  evidence_ids: string[];
  redact: boolean;
}
export interface Story {
  preview_id: string;
  title: string;
  redacted: boolean;
  steps: {
    title: string;
    subtitle: string;
    body: string;
    fields: { label: string; value: unknown }[];
    image_url?: string;
  }[];
  created_at: string;
}

export interface VisualRanking {
  method_version: string;
  reference: { id: string; image_url?: string };
  items: (Capture & {
    score: number;
    evidence_ids: string[];
    components: { perceptual: number; structure: number; color: number };
  })[];
  unassessed: (Capture & { reason: string })[];
  coverage: { captures: number; assessed_unique: number; unassessed: number; duplicates: number };
  limitations: string[];
}
