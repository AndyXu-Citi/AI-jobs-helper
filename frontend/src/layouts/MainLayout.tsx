import { type ReactNode } from 'react';
import { Tabs } from '../components/ui';
import { useTabStore } from '../stores';
import type { TabId } from '../types';

interface MainLayoutProps {
  children: ReactNode;
}

const TABS: { id: TabId; label: string; icon?: React.ReactNode }[] = [
  { id: 'chat', label: 'AI 助手' },
  { id: 'jobs', label: '岗位库' },
  { id: 'report', label: '技能报表' },
];

export function MainLayout({ children }: MainLayoutProps) {
  const { activeTab, setActiveTab } = useTabStore();

  return (
    <div className="min-h-screen bg-surface-1">
      {/* Header */}
      <header className="bg-surface-0 border-b border-border-light shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-14">
            <h1 className="text-lg font-bold text-text-primary">
              AI 求职助手
            </h1>
          </div>
        </div>
      </header>

      {/* Tabs */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <Tabs tabs={TABS} activeTab={activeTab} onChange={setActiveTab} />
      </div>

      {/* Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-5">
        {children}
      </main>
    </div>
  );
}
