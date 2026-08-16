import { useEffect, useRef, useState, useCallback } from 'react';
import { chatApi, resumeApi, jobsApi, reportApi } from '../api';
import { useChatStore, useConversationStore } from '../stores';
import { Card, Tag, Spinner, EmptyState, Button } from '../components/ui';
import { Sidebar } from '../components/Sidebar';
import type { ChatMode, InterviewSubMode, UnifiedMessage, JobItem, MatchResult, FileAttachment } from '../types';

// ===== 模式配置 =====
const MODE_CONFIG: Record<ChatMode, { label: string; icon: string; desc: string }> = {
  assistant: { label: '求职助手', icon: '🤖', desc: '搜索岗位、简历匹配、简历诊断' },
  interviewer: { label: '面试官', icon: '👨‍💼', desc: '模拟面试，支持简历/JD/项目/知识点' },
};

const SUBMODE_CONFIG: Record<InterviewSubMode, { label: string; icon: string; needsContext: 'resume' | 'jd' | 'skills' | 'none' }> = {
  resume: { label: '简历面试', icon: '📄', needsContext: 'resume' },
  jd: { label: 'JD面试', icon: '📝', needsContext: 'jd' },
  project: { label: '项目拷问', icon: '💼', needsContext: 'none' },
  knowledge: { label: '知识点', icon: '📚', needsContext: 'skills' },
};

const INTENT_LABELS: Record<string, { text: string; color: string }> = {
  search: { text: '🔍 岗位搜索', color: 'bg-blue-100 text-blue-700' },
  match: { text: '📋 简历匹配', color: 'bg-green-100 text-green-700' },
  diagnose: { text: '🩺 简历诊断', color: 'bg-purple-100 text-purple-700' },
  interview: { text: '👨‍💼 面试问答', color: 'bg-orange-100 text-orange-700' },
  reject: { text: '🚫 超出能力范围', color: 'bg-gray-100 text-gray-600' },
  chat: { text: '💬 对话', color: 'bg-gray-100 text-gray-600' },
};

export function ChatPage() {
  const {
    mode,
    interviewSubMode,
    sessionId,
    resume,
    jdText,
    selectedSkillTopic,
    messages,
    isStreaming,
    streamingContent,
    setMode,
    setInterviewSubMode,
    setSessionId,
    setResume,
    setJdText,
    setSelectedSkillTopic,
    addMessage,
    setStreaming,
    appendStreamContent,
    finalizeStream,
    clearMessages,
  } = useChatStore();

  const { createConversation, updateConversationTitle, updateConversationMeta, activeConversationId } = useConversationStore();

  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  // JD 选择器状态
  const [showJobPicker, setShowJobPicker] = useState(false);
  const [jobList, setJobList] = useState<JobItem[]>([]);
  const [jobLoading, setJobLoading] = useState(false);
  const [selectedJobForInterview, setSelectedJobForInterview] = useState<JobItem | null>(null);

  // Skills 选择器状态
  const [showSkillPicker, setShowSkillPicker] = useState(false);
  const [skillList, setSkillList] = useState<{ name: string; count: number }[]>([]);
  const [skillLoading, setSkillLoading] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent]);

  // textarea 自适应高度
  useEffect(() => {
    const ta = textareaRef.current;
    if (ta) {
      ta.style.height = 'auto';
      ta.style.height = Math.min(ta.scrollHeight, 120) + 'px';
    }
  }, [input]);

  // ===== 新建对话 =====
  const handleNewChat = useCallback(() => {
    clearMessages();
    const convId = createConversation(mode, interviewSubMode);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, interviewSubMode, clearMessages, createConversation]);

  // ===== 欢迎消息（仅首次进入）=====
  useEffect(() => {
    if (messages.length === 0) {
      addMessage({
        id: 'welcome',
        role: 'assistant',
        content: mode === 'assistant'
          ? '你好！我是你的 AI 求职助手 🤖\n\n我可以帮你：\n• 搜索匹配的岗位（如"帮我找杭州的 Agent 开发岗位"）\n• 上传简历后匹配岗位（说"帮我匹配岗位"）\n• 诊断简历（说"诊断我的简历"）\n\n有什么可以帮你的？'
          : '你好！我是你的 AI 面试官 👨‍💼\n\n选择面试模式后开始：\n• 📄 简历面试 — 上传简历，我深挖你的经历\n• 📝 JD面试 — 选择或粘贴岗位 JD\n• 💼 项目拷问 — 描述项目，全方位技术拷问\n• 📚 知识点 — 选择技术领域，系统性考核\n\n准备好了就开始吧！',
        intent: 'chat',
        timestamp: Date.now(),
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  // ===== PDF 上传 =====
  const handleFileUpload = useCallback(async (file: File) => {
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      alert('请上传 PDF 文件');
      return;
    }
    setUploading(true);
    try {
      const result = await resumeApi.upload(file);
      const attachment: FileAttachment = {
        id: `resume-${Date.now()}`,
        name: result.filename,
        type: 'pdf',
        size: result.size,
        content: result.text,
      };
      setResume(attachment);
      addMessage({
        id: `upload-${Date.now()}`,
        role: 'user',
        content: `📎 已上传简历：${result.filename}（${result.char_count} 字）`,
        timestamp: Date.now(),
        attachments: [attachment],
      });
    } catch (err) {
      alert(err instanceof Error ? err.message : '上传失败');
    } finally {
      setUploading(false);
    }
  }, [setResume, addMessage]);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFileUpload(file);
    e.target.value = '';
  };

  // ===== 加载 JD 列表 =====
  const loadJobList = useCallback(async () => {
    setJobLoading(true);
    try {
      const jobs = await jobsApi.list();
      setJobList(jobs.slice(0, 50)); // 最多展示50个
    } catch (err) {
      console.error('加载岗位列表失败:', err);
    } finally {
      setJobLoading(false);
    }
  }, []);

  const openJobPicker = () => {
    setShowJobPicker(true);
    if (jobList.length === 0) loadJobList();
  };

  // ===== 加载 Skills 列表 =====
  const loadSkillList = useCallback(async () => {
    setSkillLoading(true);
    try {
      const report = await reportApi.get();
      setSkillList(report.skills.map((s) => ({ name: s.name, count: s.count })));
    } catch (err) {
      console.error('加载技能列表失败:', err);
    } finally {
      setSkillLoading(false);
    }
  }, []);

  const openSkillPicker = () => {
    setShowSkillPicker(true);
    if (skillList.length === 0) loadSkillList();
  };

  // ===== 发送消息 =====
  const handleSend = async () => {
    const message = input.trim();
    if (!message || sending || isStreaming) return;

    // 面试官模式：检查上下文
    if (mode === 'interviewer') {
      const cfg = SUBMODE_CONFIG[interviewSubMode];
      if (cfg.needsContext === 'resume' && !resume?.content) {
        alert('请先上传简历 PDF');
        return;
      }
      if (cfg.needsContext === 'jd' && !jdText && !selectedJobForInterview) {
        openJobPicker();
        return;
      }
      if (cfg.needsContext === 'skills' && !selectedSkillTopic) {
        openSkillPicker();
        return;
      }
    }

    setInput('');
    setSending(true);

    // 自动生成对话标题（首条用户消息）
    if (messages.length <= 1 && activeConversationId) {
      const title = message.length > 20 ? message.slice(0, 20) + '...' : message;
      updateConversationTitle(activeConversationId, title);
    }

    addMessage({
      id: `user-${Date.now()}`,
      role: 'user',
      content: message,
      timestamp: Date.now(),
    });

    setStreaming(true);

    try {
      const response = await chatApi.unified({
        message,
        mode,
        session_id: sessionId || undefined,
        resume_text: resume?.content || undefined,
        jd_text: jdText || selectedJobForInterview?.description || undefined,
        interview_submode: mode === 'interviewer' ? interviewSubMode : undefined,
        skill_topic: selectedSkillTopic || undefined,
      });

      if (response.session_id) {
        setSessionId(response.session_id);
      }

      let jobCards: JobItem[] | undefined;
      if (response.job_cards && response.job_cards.length > 0) {
        jobCards = response.job_cards.map((raw: any, i: number) => ({
          id: `card-${i}-${raw.title?.slice(0, 8) || ''}`,
          title: raw.title || '',
          company: raw.brand || '',
          salary: raw.salary_desc || '',
          city: raw.city || '',
          experience: raw.experience || '',
          education: raw.degree || '',
          skills: raw.skills || [],
          description: raw.post_description || '',
          url: raw.url || '',
        }));
      }

      finalizeStream(response.intent, {
        sources: response.sources,
        jobCards,
        matchResults: response.match_results,
      });

      setStreaming(true, response.reply);
      setTimeout(() => {
        finalizeStream(response.intent, {
          sources: response.sources,
          jobCards,
          matchResults: response.match_results,
        });
      }, 100);

      // 更新对话元信息
      if (activeConversationId) {
        updateConversationMeta(activeConversationId, {
          messageCount: messages.length + 2,
        });
      }
    } catch (err) {
      setStreaming(false);
      addMessage({
        id: `error-${Date.now()}`,
        role: 'assistant',
        content: `❌ ${err instanceof Error ? err.message : '请求失败'}`,
        intent: 'chat',
        timestamp: Date.now(),
      });
    } finally {
      setSending(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // ===== 是否显示欢迎界面（无真实对话时）=====
  const hasRealMessages = messages.some((m) => m.id !== 'welcome');

  return (
    <div className="flex h-full" style={{ height: 'calc(100vh - 64px)' }}>
      {/* ===== 左侧边栏（可折叠）===== */}
      {sidebarOpen && (
        <Sidebar onNewChat={handleNewChat} />
      )}

      {/* ===== 主区域 ===== */}
      <main className="flex-1 flex flex-col min-w-0 bg-surface-0">
        {/* 顶部工具栏 */}
        <header className="flex items-center gap-3 px-4 py-2.5 border-b border-border-light bg-surface-0">
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="w-8 h-8 rounded flex items-center justify-center hover:bg-surface-1 transition-colors text-text-secondary"
            title={sidebarOpen ? '收起侧栏' : '展开侧栏'}
          >
            {sidebarOpen ? '☰' : '☰'}
          </button>

          {/* 当前模式指示 */}
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-text-primary">
              {MODE_CONFIG[mode].icon} {MODE_CONFIG[mode].label}
            </span>
            {mode === 'interviewer' && (
              <span className="text-xs text-text-muted">
                / {SUBMODE_CONFIG[interviewSubMode].label}
              </span>
            )}
          </div>

          {/* 简历上传状态 */}
          {resume && (
            <div className="ml-auto flex items-center gap-2 text-xs bg-green-50 text-green-700 px-3 py-1 rounded-full">
              <span>📎 {resume.name}</span>
              <button
                onClick={() => setResume(null)}
                className="text-green-600 hover:text-green-800 font-bold"
              >
                ✕
              </button>
            </div>
          )}

          {/* 新建对话按钮 */}
          <Button size="sm" variant="outline" onClick={handleNewChat}>
            ⊕ 新对话
          </Button>
        </header>

        {/* ===== 内容区 ===== */}
        <div className="flex-1 overflow-y-auto">
          {!hasRealMessages ? (
            /* ---- 欢迎界面（模式切换居中）---- */
            <WelcomeScreen
              mode={mode}
              interviewSubMode={interviewSubMode}
              onModeChange={setMode}
              onSubModeChange={(sub) => {
                setInterviewSubMode(sub);
                clearMessages();
              }}
              onResumeUpload={() => fileInputRef.current?.click()}
              onJDPick={openJobPicker}
              onSkillPick={openSkillPicker}
              resumeLoaded={!!resume}
              jdSet={!!jdText || !!selectedJobForInterview}
              skillSet={!!selectedSkillTopic}
            />
          ) : (
            /* ---- 对话消息区 ---- */
            <div className="p-4 space-y-4">
              {messages.map((msg) => (
                <MessageBubble key={msg.id} message={msg} currentMode={mode} />
              ))}

              {isStreaming && streamingContent && (
                <div className="flex gap-3">
                  <div className="w-8 h-8 rounded-full bg-brand-100 flex items-center justify-center text-sm flex-shrink-0">
                    {mode === 'assistant' ? '🤖' : '👨‍💼'}
                  </div>
                  <div className="bg-surface-1 rounded-2xl rounded-tl-sm px-4 py-3 max-w-[75%]">
                    <div className="text-sm text-text-primary whitespace-pre-wrap leading-relaxed">
                      {streamingContent}
                      <span className="inline-block w-1.5 h-4 bg-brand-400 ml-0.5 animate-pulse" />
                    </div>
                  </div>
                </div>
              )}

              {sending && !isStreaming && (
                <div className="flex gap-3">
                  <div className="w-8 h-8 rounded-full bg-brand-100 flex items-center justify-center text-sm flex-shrink-0">
                    {mode === 'assistant' ? '🤖' : '👨‍💼'}
                  </div>
                  <div className="bg-surface-1 rounded-2xl rounded-tl-sm px-4 py-3">
                    <Spinner size="sm" />
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* ===== 输入区域（始终固定在底部，DeepSeek 风格）===== */}
            <div className="border-t border-border-light p-4 bg-surface-0">
              <div className="max-w-3xl mx-auto">
                <div className="relative flex items-end gap-2 bg-white rounded-2xl border border-border-light shadow-sm focus-within:border-brand-400 focus-within:ring-2 focus-within:ring-brand-100 transition-all p-2">
                  {/* 左侧：文本输入 */}
                  <textarea
                    ref={textareaRef}
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder={
                      mode === 'assistant'
                        ? '给 AI 求职助手发送消息...'
                        : '回复面试官...'
                    }
                    className="flex-1 text-sm bg-transparent px-3 py-2 resize-none min-h-[40px] max-h-[120px] focus:outline-none leading-relaxed"
                    rows={1}
                  />

                  {/* 右下角操作区 */}
                  <div className="flex items-center gap-1 pb-1 flex-shrink-0">
                    {/* 附件上传（右下角位置） */}
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept=".pdf"
                      onChange={handleFileSelect}
                      className="hidden"
                    />
                    <button
                      onClick={() => fileInputRef.current?.click()}
                      disabled={uploading}
                      title="上传 PDF 简历"
                      className="w-9 h-9 rounded-lg flex items-center justify-center text-text-muted hover:text-brand-600 hover:bg-brand-50 transition-colors disabled:opacity-50"
                    >
                      {uploading ? <Spinner size="sm" /> : '📎'}
                    </button>

                    {/* 发送按钮 */}
                    <button
                      onClick={handleSend}
                      disabled={!input.trim() || sending || isStreaming}
                      className="w-9 h-9 rounded-lg flex items-center justify-center bg-brand-500 text-white hover:bg-brand-600 disabled:opacity-40 disabled:hover:bg-brand-500 transition-colors"
                      title="发送"
                    >
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M22 2L11 13" /><path d="M22 2L15 22L11 13L2 9L22 2Z" />
                      </svg>
                    </button>
                  </div>
                </div>

                {/* 底部提示 */}
                <div className="flex items-center justify-between mt-2 px-1">
                  <span className="text-xs text-text-muted">Enter 发送 · Shift+Enter 换行</span>
                  {messages.length > 1 && (
                    <button
                      onClick={clearMessages}
                      className="text-xs text-text-muted hover:text-red-500 transition-colors"
                    >
                      🗑 清空对话
                    </button>
                  )}
                </div>
              </div>
            </div>
      </main>

      {/* ===== JD 选择弹窗 ===== */}
      {showJobPicker && (
        <JobPickerModal
          jobs={jobList}
          loading={jobLoading}
          selected={selectedJobForInterview}
          onSelect={(job) => {
            setSelectedJobForInterview(job);
            setJdText(job.description || '');
            setShowJobPicker(false);
            addMessage({
              id: `jd-${Date.now()}`,
              role: 'user',
              content: `📝 已选择岗位：${job.title}（${job.company}）`,
              timestamp: Date.now(),
            });
          }}
          onClose={() => setShowJobPicker(false)}
          onRefresh={loadJobList}
        />
      )}

      {/* ===== Skills 选择弹窗 ===== */}
      {showSkillPicker && (
        <SkillPickerModal
          skills={skillList}
          loading={skillLoading}
          selected={selectedSkillTopic}
          onSelect={(skillName) => {
            setSelectedSkillTopic(skillName);
            setShowSkillPicker(false);
            addMessage({
              id: `skill-${Date.now()}`,
              role: 'user',
              content: `📚 已选择知识领域：${skillName}`,
              timestamp: Date.now(),
            });
          }}
          onClose={() => setShowSkillPicker(false)}
          onRefresh={loadSkillList}
        />
      )}
    </div>
  );
}

// ============================================================
// 欢迎界面（DeepSeek 风格：模式切换居中）
// ============================================================
function WelcomeScreen({
  mode,
  interviewSubMode,
  onModeChange,
  onSubModeChange,
  onResumeUpload,
  onJDPick,
  onSkillPick,
  resumeLoaded,
  jdSet,
  skillSet,
}: {
  mode: ChatMode;
  interviewSubMode: InterviewSubMode;
  onModeChange: (m: ChatMode) => void;
  onSubModeChange: (s: InterviewSubMode) => void;
  onResumeUpload: () => void;
  onJDPick: () => void;
  onSkillPick: () => void;
  resumeLoaded: boolean;
  jdSet: boolean;
  skillSet: boolean;
}) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center px-4 py-8">
      {/* Logo & 标题 */}
      <div className="text-center mb-8">
        <div className="text-4xl mb-3">{mode === 'assistant' ? '🤖' : '👨‍💼'}</div>
        <h1 className="text-xl font-semibold text-text-primary">
          使用{MODE_CONFIG[mode].label}开始对话
        </h1>
        <p className="text-sm text-text-muted mt-2">{MODE_CONFIG[mode].desc}</p>
      </div>

      {/* 主模式切换（居中，DeepSeek 风格胶囊按钮） */}
      <div className="flex items-center gap-3 mb-6">
        {(Object.keys(MODE_CONFIG) as ChatMode[]).map((m) => {
          const cfg = MODE_CONFIG[m];
          const active = mode === m;
          return (
            <button
              key={m}
              onClick={() => onModeChange(m)}
              className={`px-5 py-2.5 rounded-full text-sm font-medium transition-all ${
                active
                  ? 'bg-brand-500 text-white shadow-md shadow-brand-200'
                  : 'bg-surface-1 text-text-secondary hover:bg-surface-2 border border-border-light'
              }`}
            >
              {cfg.icon} {cfg.label}
            </button>
          );
        })}
      </div>

      {/* 面试官子模式 */}
      {mode === 'interviewer' && (
        <>
          <div className="flex items-center gap-2 mb-6">
            {(Object.keys(SUBMODE_CONFIG) as InterviewSubMode[]).map((s) => {
              const cfg = SUBMODE_CONFIG[s];
              const active = interviewSubMode === s;
              return (
                <button
                  key={s}
                  onClick={() => onSubModeChange(s)}
                  className={`px-4 py-2 rounded-full text-sm font-medium transition-all ${
                    active
                      ? 'bg-brand-100 text-brand-700 border border-brand-300'
                      : 'bg-surface-1 text-text-secondary hover:bg-surface-2 border border-border-light'
                  }`}
                >
                  {cfg.icon} {cfg.label}
                </button>
              );
            })}
          </div>

          {/* 上下文快捷操作 */}
          <div className="flex flex-wrap items-center justify-center gap-3 mt-2">
            {/* 简历上传 */}
            <button
              onClick={onResumeUpload}
              className={`px-4 py-2 rounded-lg text-sm border transition-all ${
                resumeLoaded
                  ? 'bg-green-50 text-green-700 border-green-300'
                  : 'bg-surface-0 text-text-secondary border-border-light hover:border-brand-300'
              }`}
            >
              {resumeLoaded ? '✓ 简历已上传' : '📄 上传简历'}
            </button>

            {/* JD 选择 */}
            {interviewSubMode === 'jd' && (
              <button
                onClick={onJDPick}
                className={`px-4 py-2 rounded-lg text-sm border transition-all ${
                  jdSet
                    ? 'bg-green-50 text-green-700 border-green-300'
                    : 'bg-surface-0 text-text-secondary border-border-light hover:border-brand-300'
                }`}
              >
                {jdSet ? '✓ JD 已设置' : '📝 选择岗位 JD'}
              </button>
            )}

            {/* 技能选择 */}
            {interviewSubMode === 'knowledge' && (
              <button
                onClick={onSkillPick}
                className={`px-4 py-2 rounded-lg text-sm border transition-all ${
                  skillSet
                    ? 'bg-green-50 text-green-700 border-green-300'
                    : 'bg-surface-0 text-text-secondary border-border-light hover:border-brand-300'
                }`}
              >
                {skillSet ? `✓ ${skillSet}` : '📚 选择知识领域'}
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}

// ============================================================
// JD 选择弹窗
// ============================================================
function JobPickerModal({
  jobs,
  loading,
  selected,
  onSelect,
  onClose,
  onRefresh,
}: {
  jobs: JobItem[];
  loading: boolean;
  selected: JobItem | null;
  onSelect: (job: JobItem) => void;
  onClose: () => void;
  onRefresh: () => void;
}) {
  const [filter, setFilter] = useState('');

  const filtered = filter
    ? jobs.filter((j) =>
        j.title.toLowerCase().includes(filter.toLowerCase()) ||
        j.company.toLowerCase().includes(filter.toLowerCase())
      )
    : jobs;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-xl w-[560px] max-h-[70vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border-light">
          <div>
            <h3 className="font-semibold text-text-primary">选择岗位 JD</h3>
            <p className="text-xs text-text-muted mt-0.5">从数据库中选择一个岗位作为面试依据，或直接在输入框中粘贴 JD 文本</p>
          </div>
          <button onClick={onClose} className="w-8 h-8 rounded-lg flex items-center justify-center hover:bg-surface-1 text-text-muted">✕</button>
        </div>

        {/* 搜索框 */}
        <div className="px-5 py-3 border-b border-border-light">
          <div className="flex gap-2">
            <input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="搜索岗位名称或公司..."
              className="flex-1 text-sm rounded-lg border border-border-light bg-surface-0 px-3 py-2 focus:outline-none focus:border-brand-400"
            />
            <Button size="sm" variant="outline" onClick={onRefresh}>刷新</Button>
          </div>
        </div>

        {/* Job List */}
        <div className="flex-1 overflow-y-auto p-2">
          {loading ? (
            <div className="flex items-center justify-center py-12"><Spinner /></div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-12 text-text-muted text-sm">暂无匹配的岗位</div>
          ) : (
            filtered.map((job) => (
              <button
                key={job.id}
                onClick={() => onSelect(job)}
                className={`w-full text-left px-4 py-3 rounded-lg transition-colors mb-1 ${
                  selected?.id === job.id
                    ? 'bg-brand-50 border border-brand-300'
                    : 'hover:bg-surface-1 border border-transparent'
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-sm text-text-primary truncate">{job.title}</div>
                    <div className="text-xs text-text-secondary mt-0.5">{job.company} · {job.city}</div>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-xs font-semibold text-success">{job.salary}</span>
                      <span className="text-xs text-text-muted">{job.experience}</span>
                    </div>
                  </div>
                  {selected?.id === job.id && (
                    <span className="text-brand-500 text-lg flex-shrink-0">✓</span>
                  )}
                </div>
                {job.skills && job.skills.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-2">
                    {job.skills.slice(0, 4).map((s) => (
                      <Tag key={s} size="sm" variant="info">{s}</Tag>
                    ))}
                    {job.skills.length > 4 && (
                      <Tag size="sm">+{job.skills.length - 4}</Tag>
                    )}
                  </div>
                )}
              </button>
            ))
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-border-light flex justify-between items-center">
          <span className="text-xs text-text-muted">共 {jobs.length} 个岗位可选</span>
          <div className="flex gap-2">
            <Button size="sm" variant="ghost" onClick={onClose}>取消</Button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ============================================================
// Skills 选择弹窗
// ============================================================
function SkillPickerModal({
  skills,
  loading,
  selected,
  onSelect,
  onClose,
  onRefresh,
}: {
  skills: { name: string; count: number }[];
  loading: boolean;
  selected: string | null;
  onSelect: (name: string) => void;
  onClose: () => void;
  onRefresh: () => void;
}) {
  const [filter, setFilter] = useState('');

  const filtered = filter
    ? skills.filter((s) => s.name.toLowerCase().includes(filter.toLowerCase()))
    : skills;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-xl w-[480px] max-h-[60vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border-light">
          <div>
            <h3 className="font-semibold text-text-primary">选择知识领域</h3>
            <p className="text-xs text-text-muted mt-0.5">从技能列表中选择一个领域进行面试考核</p>
          </div>
          <button onClick={onClose} className="w-8 h-8 rounded-lg flex items-center justify-center hover:bg-surface-1 text-text-muted">✕</button>
        </div>

        {/* 搜索框 */}
        <div className="px-5 py-3 border-b border-border-light">
          <div className="flex gap-2">
            <input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="搜索技能..."
              className="flex-1 text-sm rounded-lg border border-border-light bg-surface-0 px-3 py-2 focus:outline-none focus:border-brand-400"
            />
            <Button size="sm" variant="outline" onClick={onRefresh}>刷新</Button>
          </div>
        </div>

        {/* Skill List */}
        <div className="flex-1 overflow-y-auto p-2">
          {loading ? (
            <div className="flex items-center justify-center py-12"><Spinner /></div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-12 text-text-muted text-sm">暂无技能数据</div>
          ) : (
            <div className="grid grid-cols-2 gap-2 p-1">
              {filtered.map((s) => (
                <button
                  key={s.name}
                  onClick={() => onSelect(s.name)}
                  className={`text-left px-3 py-2.5 rounded-lg transition-colors text-sm ${
                    selected === s.name
                      ? 'bg-brand-50 border border-brand-300 text-brand-700 font-medium'
                      : 'hover:bg-surface-1 border border-transparent text-text-primary'
                  }`}
                >
                  <div className="truncate">{s.name}</div>
                  <div className="text-[11px] text-text-muted mt-0.5">{s.count} 个岗位涉及</div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-border-light flex justify-between items-center">
          <span className="text-xs text-text-muted">共 {skills.length} 个技能</span>
          <Button size="sm" variant="ghost" onClick={onClose}>取消</Button>
        </div>
      </div>
    </div>
  );
}

// ============================================================
// 消息气泡（复用原有逻辑）
// ============================================================
function MessageBubble({ message, currentMode }: { message: UnifiedMessage; currentMode: ChatMode }) {
  const isUser = message.role === 'user';

  if (isUser) {
    return (
      <div className="flex gap-3 flex-row-reverse">
        <div className="w-8 h-8 rounded-full bg-brand-500 flex items-center justify-center text-sm text-white flex-shrink-0">
          我
        </div>
        <div className="bg-brand-500 text-white rounded-2xl rounded-tr-sm px-4 py-3 max-w-[75%]">
          <div className="text-sm whitespace-pre-wrap leading-relaxed">{message.content}</div>
        </div>
      </div>
    );
  }

  const intentLabel = message.intent ? INTENT_LABELS[message.intent] : null;

  return (
    <div className="flex gap-3">
      <div className="w-8 h-8 rounded-full bg-brand-100 flex items-center justify-center text-sm flex-shrink-0">
        {message.intent === 'interview' ? '👨‍💼' : '🤖'}
      </div>
      <div className="max-w-[75%] space-y-2">
        {intentLabel && (
          <span className={`inline-block text-xs px-2 py-0.5 rounded-full ${intentLabel.color}`}>
            {intentLabel.text}
          </span>
        )}
        <div className="bg-surface-1 rounded-2xl rounded-tl-sm px-4 py-3">
          <div className="text-sm text-text-primary whitespace-pre-wrap leading-relaxed">
            {message.content}
          </div>
        </div>
        {message.jobCards && message.jobCards.length > 0 && (
          <div className="space-y-2">
            {message.jobCards.slice(0, 5).map((job, i) => (
              <JobCard key={i} job={job} />
            ))}
            {message.jobCards.length > 5 && (
              <div className="text-xs text-text-muted px-2">
                还有 {message.jobCards.length - 5} 个岗位...
              </div>
            )}
          </div>
        )}
        {message.matchResults && message.matchResults.length > 0 && (
          <div className="space-y-2">
            {message.matchResults.map((m, i) => (
              <MatchCard key={i} match={m} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ===== 岗位卡片 =====
function JobCard({ job }: { job: JobItem }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div
      className="bg-surface-0 border border-border-light rounded-lg p-3 hover:border-brand-300 transition-colors cursor-pointer"
      onClick={() => setExpanded(!expanded)}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="font-medium text-sm text-text-primary truncate">{job.title}</div>
          <div className="text-xs text-text-secondary mt-0.5">{job.company} · {job.city}</div>
          <div className="flex items-center gap-2 mt-1">
            <span className="text-xs font-semibold text-success">{job.salary}</span>
            <span className="text-xs text-text-muted">{job.experience}</span>
          </div>
        </div>
        {job.skills && job.skills.length > 0 && (
          <div className="flex flex-wrap gap-1 justify-end max-w-[50%]">
            {job.skills.slice(0, 3).map((s) => (
              <Tag key={s} size="sm" variant="info">{s}</Tag>
            ))}
          </div>
        )}
      </div>
      {expanded && job.description && (
        <div className="mt-2 pt-2 border-t border-border-light text-xs text-text-secondary whitespace-pre-wrap leading-relaxed">
          {job.description}
        </div>
      )}
    </div>
  );
}

// ===== 匹配结果卡片 =====
function MatchCard({ match }: { match: MatchResult }) {
  const scoreColor =
    match.match_score >= 70 ? 'text-green-600' :
    match.match_score >= 40 ? 'text-orange-500' :
    'text-red-500';

  return (
    <div className="bg-surface-0 border border-border-light rounded-lg p-3">
      <div className="flex items-center justify-between">
        <div className="flex-1 min-w-0">
          <div className="font-medium text-sm text-text-primary truncate">{match.job_title}</div>
          <div className="text-xs text-text-secondary mt-0.5">{match.company}</div>
        </div>
        <div className={`text-lg font-bold ${scoreColor}`}>{match.match_score}%</div>
      </div>
      <div className="flex flex-wrap gap-1 mt-2">
        {match.matched_skills?.slice(0, 5).map((s) => (
          <Tag key={s} size="sm" variant="success">✓ {s}</Tag>
        ))}
        {match.missing_skills?.slice(0, 3).map((s) => (
          <Tag key={s} size="sm" variant="danger">✗ {s}</Tag>
        ))}
      </div>
      {match.gap_analysis && (
        <div className="text-xs text-text-secondary mt-2 leading-relaxed">{match.gap_analysis}</div>
      )}
    </div>
  );
}
