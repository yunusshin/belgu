import { useState } from 'react';
import { useCaseStoredState } from '../workspaceState';
import {
  Camera,
  GitCompareArrows,
  Radar,
  Presentation,
  ListFilter,
  Brain,
  MessageSquare,
  History,
} from 'lucide-react';
import type { WorkbenchProps } from '../../api/workbench';
import { VisualDesk } from './VisualDesk';
import { CandidateDesk, ChangesDesk } from './InsightsDesk';
import { WatchDesk } from './WatchDesk';
import { StoryDesk } from './StoryDesk';
import { MemoryDesk } from './MemoryDesk';
import { AssistantDesk } from './AssistantDesk';
import { ReplayDesk } from './ReplayDesk';
const tabs = [
  ['visual', 'Görsel kanıt', Camera],
  ['candidates', 'Adaylar', ListFilter],
  ['memory', 'İnceleme hafızası', Brain],
  ['assistant', 'Araştırma asistanı', MessageSquare],
  ['changes', 'Değişimler', GitCompareArrows],
  ['watches', 'İzleme', Radar],
  ['story', 'Paylaşım', Presentation],
  ['replay', 'Tekrar oynat', History],
] as const;
export function Workbench(props: WorkbenchProps) {
  const [tab, storeTab] = useCaseStoredState<string>(
    props.inv.id,
    'workbench-tab',
    'visual',
    (value): value is string => typeof value === 'string' && tabs.some(([key]) => key === value),
  );
  const [visited, setVisited] = useState<string[]>([tab]);
  function setTab(value: string) {
    storeTab(value);
    setVisited((prev) => (prev.includes(value) ? prev : [...prev, value]));
  }
  return (
    <section className="workbench" aria-label="Çalışma masası">
      <div className="desk-nav" role="tablist" aria-label="Çalışma masası araçları">
        {tabs.map(([key, label, Icon]) => (
          <button
            key={key}
            id={`desk-tab-${key}`}
            role="tab"
            aria-selected={tab === key}
            aria-controls={`desk-panel-${key}`}
            onClick={() => setTab(key)}
          >
            <Icon size={15} />
            {label}
          </button>
        ))}
      </div>
      {visited.map((key) => (
        <div
          key={key}
          id={`desk-panel-${key}`}
          role="tabpanel"
          aria-labelledby={`desk-tab-${key}`}
          hidden={tab !== key}
        >
          {key === 'visual' ? (
            <VisualDesk {...props} />
          ) : key === 'candidates' ? (
            <CandidateDesk {...props} />
          ) : key === 'changes' ? (
            <ChangesDesk {...props} />
          ) : key === 'watches' ? (
            <WatchDesk {...props} />
          ) : key === 'memory' ? (
            <MemoryDesk {...props} />
          ) : key === 'assistant' ? (
            <AssistantDesk {...props} />
          ) : key === 'replay' ? (
            <ReplayDesk {...props} />
          ) : (
            <StoryDesk {...props} />
          )}
        </div>
      ))}
    </section>
  );
}
