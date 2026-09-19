import type { components } from './generated';
// HTTP view shapes are generated from the backend OpenAPI contract.
type Schema = components['schemas'];
export type Brand = Schema['BrandView'];
export type Target = Schema['TargetView'];
export type Submission = Schema['SubmissionView'];
export type Attachment = Schema['ArtifactView'];
export type Note = Schema['NoteView'];
export type Decision = Schema['DecisionView'];
export type Job = Schema['JobView'];
export type Investigation = Schema['InvestigationView'];
export type Group = Schema['GroupView'];
export type Entity = Schema['EntityView'];
export type Relation = Schema['RelationView'];
export type Graph = Schema['GraphView'];
export type Evidence = Schema['EvidenceView'];
export type ModelStatus = Schema['ModelStatusView'];
export interface Collection<T> {
  items: T[];
  next_cursor: string | null;
  total_unique: number;
}
// Analysis output is an open object in the API; these are the supported display fields.
export type Analysis = Omit<Schema['AnalysisView'], 'output'> & {
  output: {
    summary?: string;
    evidence_ids?: string[];
    omitted_count?: number;
    analysis_scope?: 'submitted_targets' | 'provided_evidence';
    scope_excluded_count?: number;
    budget_omitted_count?: number;
    claims?: { text: string; evidence_ids: string[]; kind?: string }[];
    uncertainties?: string[];
    next_steps?: string[];
    [key: string]: unknown;
  };
};
export interface Health {
  status: string;
  mode: string;
  worker: unknown;
  model: ModelStatus;
}
