import { api, casePath } from './client';

export interface ReplayNode {
  id: string;
  kind: string;
  label: string;
}

export interface ReplayEdge {
  id: string;
  src_id: string;
  dst_id: string;
  kind: string;
  evidence_refs: string[];
}

export interface ReplayEvent {
  id: string;
  kind: 'submission' | 'observation' | 'relation' | 'job' | 'analysis' | 'decision';
  title: string;
  known_at: string;
  observed_at: string | null;
  scope: string;
  status: string;
  evidence_refs: string[];
  detail: string;
  record_ref?: string;
  graph_additions: { nodes: ReplayNode[]; edges: ReplayEdge[] };
}

export interface ReplayCoverage {
  available_events: number;
  included_events: number;
  omitted_events: number;
  event_limit: number;
  available_graph_nodes: number;
  included_graph_nodes: number;
  omitted_graph_nodes: number;
  graph_node_limit: number;
  relation_records: number;
  supported_relation_events: number;
  included_relation_events: number;
  rendered_graph_edges: number;
  omitted_graph_edges: number;
  included_relations: number;
  unsupported_relations: number;
  omitted_evidence_lifecycle_events: number;
  events_truncated: boolean;
  graph_truncated: boolean;
}

export interface Replay {
  preview_id: string;
  title: string;
  redacted: boolean;
  recorded: true;
  timing_basis: 'known_at';
  created_at: string;
  events: ReplayEvent[];
  graph: { nodes: ReplayNode[]; edges: ReplayEdge[] };
  counts: { available: Record<string, number>; included: Record<string, number> };
  coverage: ReplayCoverage;
  limitations: string[];
}

export function previewReplay(investigationId: string, redact = true) {
  return api.post<Replay>(`${casePath(investigationId)}/replay/preview`, { redact });
}

export async function downloadReplay(investigationId: string, previewId: string, redact: boolean) {
  const response = await fetch(`/api${casePath(investigationId)}/replay/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ preview_id: previewId, redact }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error?.message || 'Kayıtlı inceleme indirilemedi.');
  }
  return response.blob();
}
