import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from 'react';

export const EVIDENCE_LIMIT = 12;
export function evidenceIds(value: unknown): value is string[] {
  return (
    Array.isArray(value) &&
    value.length <= EVIDENCE_LIMIT &&
    value.every((id) => typeof id === 'string' && id.length > 0 && id.length <= 256) &&
    new Set(value).size === value.length
  );
}
export function normalizeEvidenceIds(ids: string[]) {
  return [...new Set(ids.filter((id) => typeof id === 'string' && id.length > 0 && id.length <= 256))].slice(
    0,
    EVIDENCE_LIMIT,
  );
}
export function useCaseStoredState<T>(
  caseId: string,
  field: string,
  fallback: T,
  valid: (value: unknown) => value is T,
): [T, Dispatch<SetStateAction<T>>] {
  const key = `belgu:case-workspace:v1:${caseId}:${field}`;
  const [value, setValue] = useState<T>(() => {
    try {
      const stored: unknown = JSON.parse(localStorage.getItem(key) || 'null');
      return valid(stored) ? stored : fallback;
    } catch {
      return fallback;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* Storage is optional; keep this session usable. */
    }
  }, [key, value]);
  return [value, setValue];
}
type CaseWorkspace = {
  pinnedEvidence: string[];
  toggleEvidence: (id: string) => void;
  setPinnedEvidence: (ids: string[]) => void;
};
const Context = createContext<CaseWorkspace>({
  pinnedEvidence: [],
  toggleEvidence: () => {},
  setPinnedEvidence: () => {},
});
export function CaseWorkspaceProvider({
  investigationId,
  children,
}: {
  investigationId: string;
  children: ReactNode;
}) {
  const [pinnedEvidence, setPinned] = useCaseStoredState<string[]>(
    investigationId,
    'evidence-board',
    [],
    evidenceIds,
  );
  const value = useMemo(
    () => ({
      pinnedEvidence,
      toggleEvidence: (id: string) =>
        setPinned((prev) =>
          prev.includes(id) ? prev.filter((item) => item !== id) : normalizeEvidenceIds([...prev, id]),
        ),
      setPinnedEvidence: (ids: string[]) => setPinned(normalizeEvidenceIds(ids)),
    }),
    [pinnedEvidence, setPinned],
  );
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
export function useCaseWorkspace() {
  return useContext(Context);
}
