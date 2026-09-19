import type { Entity, Group } from '../api/types';
export type ResearchFilters = {
  q: string;
  kind: string;
  hasCapture: boolean;
  shared: string;
  recent: boolean;
  sort: string;
};
export type SavedResearchView = { name: string; filters: ResearchFilters; group: Group | null };
export type ResearchState = {
  filters: ResearchFilters;
  criterion: string;
  mode: 'groups' | 'focus';
  selected: Entity[];
  pins: Entity[];
  trail: Entity[];
  focus: Entity | null;
  group: Group | null;
  views: SavedResearchView[];
};
export const PIN_LIMIT = 20;
export const defaultFilters: ResearchFilters = {
  q: '',
  kind: 'domain',
  hasCapture: false,
  shared: '',
  recent: false,
  sort: 'name',
};
const key = (id: string) => `belgu:research:v1:${id}`;
const record = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === 'object' && !Array.isArray(value);
function filters(value: unknown): ResearchFilters {
  if (!record(value)) return { ...defaultFilters };
  return {
    q: typeof value.q === 'string' ? value.q.slice(0, 300) : '',
    kind: ['domain', 'ip', 'url'].includes(String(value.kind)) ? String(value.kind) : 'domain',
    hasCapture: value.hasCapture === true,
    recent: value.recent === true,
    shared: ['javascript', 'certificate'].includes(String(value.shared)) ? String(value.shared) : '',
    sort: ['name', 'latest', 'priority'].includes(String(value.sort)) ? String(value.sort) : 'name',
  };
}
function entity(value: unknown): Entity | null {
  if (
    !record(value) ||
    typeof value.id !== 'string' ||
    !value.id ||
    value.id.length > 200 ||
    typeof value.canonical_value !== 'string' ||
    !value.canonical_value ||
    value.canonical_value.length > 4096 ||
    !['domain', 'ip', 'url', 'cert', 'js_hash', 'favicon_hash'].includes(String(value.kind))
  )
    return null;
  return {
    id: value.id,
    kind: value.kind,
    canonical_value: value.canonical_value,
    evidence_count: typeof value.evidence_count === 'number' ? value.evidence_count : 0,
    last_seen: typeof value.last_seen === 'string' ? value.last_seen : null,
  } as Entity;
}
function entities(value: unknown) {
  return Array.isArray(value)
    ? [
        ...new Map(
          value
            .map(entity)
            .filter((item): item is Entity => !!item)
            .map((item) => [item.id, item]),
        ).values(),
      ].slice(0, PIN_LIMIT)
    : [];
}
function group(value: unknown): Group | null {
  if (
    !record(value) ||
    typeof value.key !== 'string' ||
    typeof value.label !== 'string' ||
    !['js_sha256', 'cert_sha256', 'observed_ip'].includes(String(value.criterion)) ||
    !Array.isArray(value.evidence_ids)
  )
    return null;
  return {
    key: value.key.slice(0, 500),
    label: value.label.slice(0, 500),
    criterion: value.criterion,
    entity_count: typeof value.entity_count === 'number' ? value.entity_count : 0,
    evidence_ids: value.evidence_ids.filter((id): id is string => typeof id === 'string').slice(0, 200),
  } as Group;
}
export function loadResearchState(id: string): ResearchState {
  let raw: unknown;
  try {
    raw = JSON.parse(localStorage.getItem(key(id)) || 'null');
  } catch {
    raw = null;
  }
  const value = record(raw) ? raw : {};
  const views = Array.isArray(value.views)
    ? value.views
        .filter(record)
        .filter((view) => typeof view.name === 'string' && view.name.trim())
        .slice(0, 12)
        .map((view) => ({
          name: String(view.name).slice(0, 60),
          filters: filters(view.filters),
          group: group(view.group),
        }))
    : [];
  return {
    filters: filters(value.filters),
    criterion: ['js_sha256', 'cert_sha256', 'observed_ip'].includes(String(value.criterion))
      ? String(value.criterion)
      : 'js_sha256',
    mode: value.mode === 'focus' ? 'focus' : 'groups',
    selected: entities(value.selected),
    pins: entities(value.pins),
    trail: entities(value.trail),
    focus: entity(value.focus),
    group: group(value.group),
    views,
  };
}
export function saveResearchState(id: string, state: ResearchState) {
  try {
    localStorage.setItem(key(id), JSON.stringify(state));
    return true;
  } catch {
    return false;
  }
}
