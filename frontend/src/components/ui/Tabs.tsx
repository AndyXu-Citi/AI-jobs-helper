import type { TabId } from '../../types';

interface TabsProps {
  tabs: { id: TabId; label: string; icon?: React.ReactNode }[];
  activeTab: TabId;
  onChange: (tab: TabId) => void;
}

export function Tabs({ tabs, activeTab, onChange }: TabsProps) {
  return (
    <div className="flex border-b border-border-light bg-surface-0">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          onClick={() => onChange(tab.id)}
          className={`
            relative flex items-center gap-2 px-5 py-3 text-sm font-medium
            transition-colors duration-150 cursor-pointer
            ${
              activeTab === tab.id
                ? 'text-brand-600'
                : 'text-text-muted hover:text-text-secondary hover:bg-surface-1'
            }
          `}
        >
          {tab.icon}
          {tab.label}
          {activeTab === tab.id && (
            <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-brand-500 rounded-t" />
          )}
        </button>
      ))}
    </div>
  );
}
