import { useTabStore } from './stores';
import { ChatPage, JobLibraryPage, SkillReportPage } from './pages';
import { MainLayout } from './layouts/MainLayout';

function App() {
  const { activeTab } = useTabStore();

  return (
    <MainLayout>
      {activeTab === 'chat' && <ChatPage />}
      {activeTab === 'jobs' && <JobLibraryPage />}
      {activeTab === 'report' && <SkillReportPage />}
    </MainLayout>
  );
}

export default App;
