import { useEffect, useRef, useState, useCallback } from 'react';
import { chatApi, resumeApi, jobsApi, reportApi } from '../api';
import { useChatStore, useConversationStore } from '../stores';
import { Sidebar } from '../components/Sidebar';
import type { ChatMode, InterviewSubMode, UnifiedMessage, JobItem, MatchResult, FileAttachment } from '../types';

/* ============================================================
 * 线性图标（统一描边，随 currentColor 着色，替代 emoji）
 * ========================================================== */
type IconProps = { size?: number; className?: string };
const S = (p: IconProps) => ({ width: p.size ?? 18, height: p.size ?? 18, className: p.className, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.6, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const });

const IconAssistant = (p: IconProps) => (
  <svg {...S(p)}><path d="M12 3a6 6 0 0 1 4.5 10v3.5a1.5 1.5 0 0 1-1.5 1.5h-6A1.5 1.5 0 0 1 7.5 16.5V13A6 6 0 0 1 12 3Z" /><path d="M9.5 21h5" /><path d="M10 18v3M14 18v3" /><circle cx="9.5" cy="11" r="1" /><circle cx="14.5" cy="11" r="1" /></svg>
);
const IconInterviewer = (p: IconProps) => (
  <svg {...S(p)}><circle cx="12" cy="8" r="3.4" /><path d="M5.5 20a6.5 6.5 0 0 1 13 0" /></svg>
);
const IconBriefcase = (p: IconProps) => (
  <svg {...S(p)}><rect x="3" y="7.5" width="18" height="12" rx="2" /><path d="M8.5 7.5V6a2 2 0 0 1 2-2h3a2 2 0 0 1 2 2v1.5" /><path d="M3 12.5h18" /></svg>
);
const IconResume = (p: IconProps) => (
  <svg {...S(p)}><path d="M7 3h7l4 4v14H7z" /><path d="M14 3v4h4" /><path d="M9.5 13h5M9.5 16.5h5M9.5 9.5h2" /></svg>
);
const IconClipboard = (p: IconProps) => (
  <svg {...S(p)}><rect x="5" y="4" width="14" height="17" rx="2" /><path d="M9 4V3a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v1" /><path d="M9 11h6M9 15h6M9 19h4" /></svg>
);
const IconProject = (p: IconProps) => (
  <svg {...S(p)}><path d="M3 7l9-4 9 4-9 4-9-4Z" /><path d="M3 7v10l9 4 9-4V7" /><path d="M12 11v10" /></svg>
);
const IconBook = (p: IconProps) => (
  <svg {...S(p)}><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5z" /><path d="M4 5.5V20.5" /></svg>
);
const IconPaperclip = (p: IconProps) => (
  <svg {...S(p)}><path d="M20 11.5 12 19.5a4.5 4.5 0 0 1-6.4-6.4l8-8a3 3 0 0 1 4.2 4.2l-8 8a1.5 1.5 0 0 1-2.1-2.1l7.4-7.4" /></svg>
);
const IconSend = (p: IconProps) => (
  <svg {...S(p)}><path d="M20 4 4 12l5 2 2 5 9-15Z" /><path d="M9 14l4-4" /></svg>
);
const IconPlus = (p: IconProps) => (
  <svg {...S(p)}><path d="M12 5v14M5 12h14" /></svg>
);
const IconClose = (p: IconProps) => (
  <svg {...S(p)}><path d="M6 6l12 12M18 6 6 18" /></svg>
);
const IconTrash = (p: IconProps) => (
  <svg {...S(p)}><path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13" /></svg>
);
const IconSearch = (p: IconProps) => (
  <svg {...S(p)}><circle cx="11" cy="11" r="6.5" /><path d="m20 20-3.5-3.5" /></svg>
);
const IconMenu = (p: IconProps) => (
  <svg {...S(p)}><path d="M4 7h16M4 12h16M4 17h16" /></svg>
);
const IconSpark = (p: IconProps) => (
  <svg {...S(p)}><path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M18 6l-2.5 2.5M8.5 15.5 6 18" /></svg>
);
const IconCheck = (p: IconProps) => (
  <svg {...S(p)}><path d="M5 12.5 10 17l9-10" /></svg>
);
const IconBolt = (p: IconProps) => (
  <svg {...S(p)}><path d="M13 3 5 13h5l-1 8 8-10h-5l1-8Z" /></svg>
);
const IconStethoscope = (p: IconProps) => (
  <svg {...S(p)}><path d="M6 3v5a4 4 0 0 0 8 0V3" /><path d="M10 16a5 5 0 0 0 10 0v-2" /><circle cx="20" cy="11" r="2" /></svg>
);
const IconCompass = (p: IconProps) => (
  <svg {...S(p)}><circle cx="12" cy="12" r="9" /><path d="m15.5 8.5-2 5-5 2 2-5 5-2Z" /></svg>
);

const MODE_ICON: Record<ChatMode, (p: IconProps) => JSX.Element> = {
  assistant: IconAssistant,
  interviewer: IconInterviewer,
};

// ===== 模式配置 =====
const MODE_CONFIG: Record<ChatMode, { label: string; desc: string; accent: string }> = {
  assistant: { label: '求职助手', desc: '找岗位、匹配简历、诊断短板', accent: 'text-indigo-600' },
  interviewer: { label: '面试官', desc: '模拟真实面试，查漏补缺', accent: 'text-violet-600' },
};

const SUBMODE_CONFIG: Record<InterviewSubMode, { label: string; icon: (p: IconProps) => JSX.Element; needsContext: 'resume' | 'jd' | 'skills' | 'none'; hint: string }> = {
  resume: { label: '简历面试', icon: IconResume, needsContext: 'resume', hint: '基于你的简历深挖经历' },
  jd: { label: 'JD 面试', icon: IconClipboard, needsContext: 'jd', hint: '围绕具体岗位要求提问' },
  project: { label: '项目拷问', icon: IconProject, needsContext: 'none', hint: '对技术细节步步追问' },
  knowledge: { label: '知识点', icon: IconBook, needsContext: 'skills', hint: '系统性考核知识盲区' },
};

// 意图标签：中性描边 + 小色点，不再用饱和彩色 pill
const INTENT_LABELS: Record<string, { text: string; dot: string }> = {
  search: { text: '岗位搜索', dot: 'bg-indigo-500' },
  match: { text: '简历匹配', dot: 'bg-emerald-500' },
  diagnose: { text: '简历诊断', dot: 'bg-violet-500' },
  interview: { text: '面试问答', dot: 'bg-amber-500' },
  reject: { text: '超出范围', dot: 'bg-stone-400' },
  chat: { text: '对话', dot: 'bg-stone-400' },
};

// 示例开场白（空状态引导，点击即发送）
const SUGGESTIONS: { icon: (p: IconProps) => JSX.Element; text: string; mode: ChatMode }[] = [
  { icon: IconCompass, text: '帮我找杭州的 Agent 开发岗位', mode: 'assistant' },
  { icon: IconStethoscope, text: '诊断一下我的简历，指出短板', mode: 'assistant' },
  { icon: IconInterviewer, text: '用我的简历模拟一场后端面试', mode: 'interviewer' },
  { icon: IconBolt, text: '我简历和这些岗位匹配度如何？', mode: 'assistant' },
];

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

  const [showJobPicker, setShowJobPicker] = useState(false);
  const [jobList, setJobList] = useState<JobItem[]>([]);
  const [jobLoading, setJobLoading] = useState(false);
  const [selectedJobForInterview, setSelectedJobForInterview] = useState<JobItem | null>(null);

  const [showSkillPicker, setShowSkillPicker] = useState(false);
  const [skillList, setSkillList] = useState<{ name: string; count: number }[]>([]);
  const [skillLoading, setSkillLoading] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent]);

  useEffect(() => {
    const ta = textareaRef.current;
    if (ta) {
      ta.style.height = 'auto';
      ta.style.height = Math.min(ta.scrollHeight, 140) + 'px';
    }
  }, [input]);

  const handleNewChat = useCallback(() => {
    clearMessages();
    createConversation(mode, interviewSubMode);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, interviewSubMode, clearMessages, createConversation]);

  // 欢迎消息（仅首次）
  useEffect(() => {
    if (messages.length === 0) {
      addMessage({
        id: 'welcome',
        role: 'assistant',
        content:
          mode === 'assistant'
            ? '我是你的求职助手。可以帮你搜索匹配的岗位、用简历匹配机会，或诊断简历短板。想从哪开始？'
            : '我是你的面试官。选好面试模式后，我们可以开始一场真实的模拟面试。',
        intent: 'chat',
        timestamp: Date.now(),
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

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
        content: `已上传简历：${result.filename}（${result.char_count} 字）`,
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

  const loadJobList = useCallback(async () => {
    setJobLoading(true);
    try {
      const jobs = await jobsApi.list();
      setJobList(jobs.slice(0, 50));
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

  const handleSend = async (preset?: string) => {
    const message = (preset ?? input).trim();
    if (!message || sending || isStreaming) return;

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

    if (messages.length <= 1 && activeConversationId) {
      const title = message.length > 20 ? message.slice(0, 20) + '…' : message;
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

      if (response.session_id) setSessionId(response.session_id);

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

      if (activeConversationId) {
        updateConversationMeta(activeConversationId, { messageCount: messages.length + 2 });
      }
    } catch (err) {
      setStreaming(false);
      addMessage({
        id: `error-${Date.now()}`,
        role: 'assistant',
        content: `出错了：${err instanceof Error ? err.message : '请求失败'}`,
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

  const hasRealMessages = messages.some((m) => m.id !== 'welcome');

  return (
    <div className="flex h-full bg-stone-50" style={{ height: 'calc(100vh - 64px)' }}>
      {sidebarOpen && <Sidebar onNewChat={handleNewChat} />}

      <main className="flex-1 flex flex-col min-w-0">
        {/* 顶部细栏 */}
        <header className="flex items-center gap-3 h-14 px-5 border-b border-stone-200/80 bg-white/80 backdrop-blur">
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-stone-400 hover:text-stone-700 hover:bg-stone-100 transition-colors"
            title={sidebarOpen ? '收起会话' : '展开会话'}
          >
            <IconMenu size={18} />
          </button>

          <div className="flex items-center gap-2 min-w-0">
            {(() => {
              const Icon = MODE_ICON[mode];
              return <Icon size={18} className={MODE_CONFIG[mode].accent} />;
            })()}
            <span className="text-[15px] font-semibold text-stone-800 tracking-tight">{MODE_CONFIG[mode].label}</span>
            {mode === 'interviewer' && (
              <span className="text-[13px] text-stone-400">/ {SUBMODE_CONFIG[interviewSubMode].label}</span>
            )}
          </div>

          <div className="ml-auto flex items-center gap-2">
            {resume && (
              <span className="inline-flex items-center gap-1.5 text-[13px] text-emerald-700 bg-emerald-50 border border-emerald-100 px-2.5 py-1 rounded-full">
                <IconResume size={14} />
                {resume.name}
                <button onClick={() => setResume(null)} className="text-emerald-500 hover:text-emerald-700 transition-colors" title="移除简历">
                  <IconClose size={13} />
                </button>
              </span>
            )}
            <button
              onClick={handleNewChat}
              className="inline-flex items-center gap-1.5 text-[13px] font-medium text-stone-600 border border-stone-200 px-3 py-1.5 rounded-lg hover:bg-stone-100 hover:text-stone-900 transition-colors"
            >
              <IconPlus size={15} />
              新对话
            </button>
          </div>
        </header>

        {/* 内容区 */}
        <div className="flex-1 overflow-y-auto">
          {!hasRealMessages ? (
            <WelcomeScreen
              mode={mode}
              interviewSubMode={interviewSubMode}
              onModeChange={(m) => { setMode(m); clearMessages(); }}
              onSubModeChange={(sub) => { setInterviewSubMode(sub); clearMessages(); }}
              onResumeUpload={() => fileInputRef.current?.click()}
              onJDPick={openJobPicker}
              onSkillPick={openSkillPicker}
              onSuggestion={(text) => { setMode('assistant'); handleSend(text); }}
              resumeLoaded={!!resume}
              jdSet={!!jdText || !!selectedJobForInterview}
              skillSet={!!selectedSkillTopic}
            />
          ) : (
            <div className="mx-auto max-w-3xl px-4 py-6 space-y-5">
              {messages.map((msg) => (
                <MessageBubble key={msg.id} message={msg} currentMode={mode} />
              ))}

              {isStreaming && streamingContent && (
                <div className="msg-in flex gap-3">
                  <div className="w-8 h-8 rounded-full bg-white border border-stone-200 flex items-center justify-center text-indigo-600 flex-shrink-0">
                    {(() => { const Icon = MODE_ICON[mode]; return <Icon size={17} />; })()}
                  </div>
                  <div className="bg-white border border-stone-200 rounded-2xl rounded-tl-md px-4 py-3 max-w-[78%]">
                    <div className="text-[14px] text-stone-700 whitespace-pre-wrap leading-relaxed">
                      {streamingContent}
                      <span className="caret text-indigo-500" />
                    </div>
                  </div>
                </div>
              )}

              {sending && !isStreaming && (
                <div className="flex gap-3">
                  <div className="w-8 h-8 rounded-full bg-white border border-stone-200 flex items-center justify-center text-indigo-600 flex-shrink-0">
                    {(() => { const Icon = MODE_ICON[mode]; return <Icon size={17} />; })()}
                  </div>
                  <div className="bg-white border border-stone-200 rounded-2xl rounded-tl-md px-4 py-3.5 flex items-center">
                    <span className="flex gap-1">
                      <i className="w-1.5 h-1.5 rounded-full bg-stone-300 animate-bounce" style={{ animationDelay: '0ms' }} />
                      <i className="w-1.5 h-1.5 rounded-full bg-stone-300 animate-bounce" style={{ animationDelay: '150ms' }} />
                      <i className="w-1.5 h-1.5 rounded-full bg-stone-300 animate-bounce" style={{ animationDelay: '300ms' }} />
                    </span>
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* 输入区 */}
        <div className="border-t border-stone-200/80 bg-white/80 backdrop-blur px-4 py-3.5">
          <div className="mx-auto max-w-3xl">
            <div className="focus-ring flex items-end gap-2 bg-white rounded-2xl border border-stone-200 px-3 py-2 transition-all">
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={mode === 'assistant' ? '说说你想找的岗位，或粘贴简历…' : '回答面试官的问题…'}
                className="flex-1 text-[14px] text-stone-800 bg-transparent px-2 py-2 resize-none min-h-[40px] max-h-[140px] placeholder:text-stone-400 focus:outline-none leading-relaxed"
                rows={1}
              />
              <div className="flex items-center gap-1 pb-1 flex-shrink-0">
                <input ref={fileInputRef} type="file" accept=".pdf" onChange={handleFileSelect} className="hidden" />
                <button
                  onClick={() => fileInputRef.current?.click()}
                  disabled={uploading}
                  title="上传 PDF 简历"
                  className="w-9 h-9 rounded-lg flex items-center justify-center text-stone-400 hover:text-indigo-600 hover:bg-indigo-50 transition-colors disabled:opacity-50"
                >
                  <IconPaperclip size={18} />
                </button>
                <button
                  onClick={() => handleSend()}
                  disabled={!input.trim() || sending || isStreaming}
                  title="发送"
                  className="w-9 h-9 rounded-lg flex items-center justify-center bg-indigo-600 text-white hover:bg-indigo-700 active:bg-indigo-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <IconSend size={17} />
                </button>
              </div>
            </div>
            <div className="flex items-center justify-between mt-2 px-1.5">
              <span className="text-[12px] text-stone-400">Enter 发送 · Shift + Enter 换行</span>
              {messages.length > 1 && (
                <button onClick={clearMessages} className="inline-flex items-center gap-1 text-[12px] text-stone-400 hover:text-rose-500 transition-colors">
                  <IconTrash size={13} />
                  清空对话
                </button>
              )}
            </div>
          </div>
        </div>
      </main>

      {/* JD 选择弹窗 */}
      {showJobPicker && (
        <JobPickerModal
          jobs={jobList}
          loading={jobLoading}
          selected={selectedJobForInterview}
          onSelect={(job) => {
            setSelectedJobForInterview(job);
            setJdText(job.description || '');
            setShowJobPicker(false);
            addMessage({ id: `jd-${Date.now()}`, role: 'user', content: `已选择岗位：${job.title}（${job.company}）`, timestamp: Date.now() });
          }}
          onClose={() => setShowJobPicker(false)}
          onRefresh={loadJobList}
        />
      )}

      {/* Skills 选择弹窗 */}
      {showSkillPicker && (
        <SkillPickerModal
          skills={skillList}
          loading={skillLoading}
          selected={selectedSkillTopic}
          onSelect={(skillName) => {
            setSelectedSkillTopic(skillName);
            setShowSkillPicker(false);
            addMessage({ id: `skill-${Date.now()}`, role: 'user', content: `已选择知识领域：${skillName}`, timestamp: Date.now() });
          }}
          onClose={() => setShowSkillPicker(false)}
          onRefresh={loadSkillList}
        />
      )}
    </div>
  );
}

/* ============================================================
 * 欢迎界面：克制引导 + 示例开场白，去除大 emoji 与胶囊按钮
 * ========================================================== */
function WelcomeScreen({
  mode,
  interviewSubMode,
  onModeChange,
  onSubModeChange,
  onResumeUpload,
  onJDPick,
  onSkillPick,
  onSuggestion,
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
  onSuggestion: (text: string) => void;
  resumeLoaded: boolean;
  jdSet: boolean;
  skillSet: boolean;
}) {
  return (
    <div className="h-full flex flex-col items-center justify-center px-6 py-10 fade-in">
      <div className="w-full max-w-2xl">
        {/* 模式分段控件（细滑块 + 白高亮） */}
        <div className="flex justify-center mb-7">
          <div className="relative inline-flex p-1 bg-stone-100 rounded-full">
            {(Object.keys(MODE_CONFIG) as ChatMode[]).map((m) => {
              const cfg = MODE_CONFIG[m];
              const active = mode === m;
              return (
                <button
                  key={m}
                  onClick={() => onModeChange(m)}
                  className={`relative z-10 inline-flex items-center gap-1.5 px-5 py-2 rounded-full text-[13px] font-medium transition-colors duration-200 ${
                    active ? 'text-stone-900' : 'text-stone-500 hover:text-stone-700'
                  }`}
                >
                  {active && <span className="absolute inset-0 -z-10 bg-white rounded-full shadow-sm ring-1 ring-stone-900/5" />}
                  {(() => { const Icon = MODE_ICON[m]; return <Icon size={16} className={active ? cfg.accent : ''} />; })()}
                  {cfg.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* 标题区 */}
        <div className="text-center mb-8">
          <h1 className="text-[26px] font-semibold text-stone-900 tracking-tight">
            {mode === 'assistant' ? '让求职这件事更轻一点' : '来一场真实的模拟面试'}
          </h1>
          <p className="text-[14px] text-stone-500 mt-2">{MODE_CONFIG[mode].desc}</p>
        </div>

        {/* 面试官子模式卡片 */}
        {mode === 'interviewer' ? (
          <div className="grid grid-cols-2 gap-3 mb-7">
            {(Object.keys(SUBMODE_CONFIG) as InterviewSubMode[]).map((s) => {
              const cfg = SUBMODE_CONFIG[s];
              const active = interviewSubMode === s;
              const Icon = cfg.icon;
              return (
                <button
                  key={s}
                  onClick={() => onSubModeChange(s)}
                  className={`text-left px-4 py-3.5 rounded-xl border transition-all duration-200 ${
                    active ? 'bg-white border-indigo-300 shadow-sm' : 'bg-white/60 border-stone-200 hover:border-stone-300 hover:bg-white'
                  }`}
                >
                  <div className={`inline-flex items-center justify-center w-9 h-9 rounded-lg mb-2.5 ${active ? 'bg-indigo-50 text-indigo-600' : 'bg-stone-100 text-stone-500'}`}>
                    <Icon size={18} />
                  </div>
                  <div className="text-[14px] font-medium text-stone-800">{cfg.label}</div>
                  <div className="text-[12px] text-stone-400 mt-0.5">{cfg.hint}</div>
                </button>
              );
            })}
          </div>
        ) : (
          /* 助手模式：示例开场白 */
          <div className="grid grid-cols-2 gap-3 mb-7">
            {SUGGESTIONS.map((s, i) => {
              const Icon = s.icon;
              return (
                <button
                  key={i}
                  onClick={() => onSuggestion(s.text)}
                  className="group text-left px-4 py-3.5 rounded-xl bg-white border border-stone-200 hover:border-indigo-300 hover:shadow-sm transition-all duration-200"
                >
                  <div className="inline-flex items-center justify-center w-8 h-8 rounded-lg bg-stone-100 text-stone-500 group-hover:bg-indigo-50 group-hover:text-indigo-600 transition-colors mb-2.5">
                    <Icon size={16} />
                  </div>
                  <div className="text-[13px] text-stone-700 leading-snug">{s.text}</div>
                </button>
              );
            })}
          </div>
        )}

        {/* 上下文状态（面试官模式） */}
        {mode === 'interviewer' && (
          <div className="flex flex-wrap items-center justify-center gap-2.5">
            <ContextChip
              icon={IconResume}
              label={resumeLoaded ? '简历已就绪' : '上传简历'}
              ready={resumeLoaded}
              onClick={onResumeUpload}
            />
            {interviewSubMode === 'jd' && (
              <ContextChip icon={IconClipboard} label={jdSet ? 'JD 已设置' : '选择岗位 JD'} ready={jdSet} onClick={onJDPick} />
            )}
            {interviewSubMode === 'knowledge' && (
              <ContextChip icon={IconBook} label={skillSet ? `领域：${skillSet}` : '选择知识领域'} ready={!!skillSet} onClick={onSkillPick} />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function ContextChip({
  icon: Icon,
  label,
  ready,
  onClick,
}: {
  icon: (p: IconProps) => JSX.Element;
  label: string;
  ready: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-[13px] border transition-all ${
        ready ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-white text-stone-600 border-stone-200 hover:border-indigo-300'
      }`}
    >
      <Icon size={15} />
      {label}
      {ready && <IconCheck size={14} className="text-emerald-600" />}
    </button>
  );
}

/* ============================================================
 * JD 选择弹窗
 * ========================================================== */
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
    ? jobs.filter((j) => j.title.toLowerCase().includes(filter.toLowerCase()) || j.company.toLowerCase().includes(filter.toLowerCase()))
    : jobs;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-stone-900/30 backdrop-blur-sm fade-in" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-[560px] max-h-[72vh] flex flex-col overflow-hidden" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-stone-200">
          <div>
            <h3 className="font-semibold text-stone-800 tracking-tight">选择岗位 JD</h3>
            <p className="text-[12px] text-stone-400 mt-0.5">从库中挑选一个岗位作为面试依据</p>
          </div>
          <button onClick={onClose} className="w-8 h-8 rounded-lg flex items-center justify-center text-stone-400 hover:bg-stone-100 hover:text-stone-700 transition-colors">
            <IconClose size={18} />
          </button>
        </div>

        <div className="px-5 py-3 border-b border-stone-200">
          <div className="flex items-center gap-2 bg-stone-100 rounded-lg px-3">
            <IconSearch size={16} className="text-stone-400" />
            <input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="搜索岗位名称或公司…"
              className="flex-1 text-[14px] bg-transparent py-2.5 focus:outline-none placeholder:text-stone-400 text-stone-700"
            />
            <button onClick={onRefresh} className="text-[12px] text-indigo-600 hover:text-indigo-700 font-medium px-2 py-1">刷新</button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-2.5">
          {loading ? (
            <div className="flex items-center justify-center py-12"><SpinnerDot /></div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-12 text-[13px] text-stone-400">暂无匹配的岗位</div>
          ) : (
            filtered.map((job) => {
              const active = selected?.id === job.id;
              return (
                <button
                  key={job.id}
                  onClick={() => onSelect(job)}
                  className={`w-full text-left px-4 py-3 rounded-xl transition-colors mb-1 ${
                    active ? 'bg-indigo-50/70 ring-1 ring-indigo-200' : 'hover:bg-stone-50'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <div className="font-medium text-[14px] text-stone-800 truncate">{job.title}</div>
                      <div className="text-[12px] text-stone-500 mt-0.5">{job.company} · {job.city}</div>
                      <div className="flex items-center gap-2 mt-1">
                        <span className="text-[12px] font-semibold text-indigo-600">{job.salary}</span>
                        <span className="text-[12px] text-stone-400">{job.experience}</span>
                      </div>
                    </div>
                    {active && <IconCheck size={18} className="text-indigo-600 flex-shrink-0 mt-1" />}
                  </div>
                  {job.skills && job.skills.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      {job.skills.slice(0, 4).map((s) => (
                        <span key={s} className="text-[11px] px-2 py-0.5 rounded-full bg-stone-100 text-stone-500 border border-stone-200">{s}</span>
                      ))}
                      {job.skills.length > 4 && <span className="text-[11px] px-2 py-0.5 rounded-full bg-stone-100 text-stone-400">+{job.skills.length - 4}</span>}
                    </div>
                  )}
                </button>
              );
            })
          )}
        </div>

        <div className="px-5 py-3 border-t border-stone-200 flex justify-between items-center">
          <span className="text-[12px] text-stone-400">共 {jobs.length} 个岗位可选</span>
          <button onClick={onClose} className="text-[13px] text-stone-500 hover:text-stone-800 transition-colors">关闭</button>
        </div>
      </div>
    </div>
  );
}

/* ============================================================
 * Skills 选择弹窗
 * ========================================================== */
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
  const filtered = filter ? skills.filter((s) => s.name.toLowerCase().includes(filter.toLowerCase())) : skills;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-stone-900/30 backdrop-blur-sm fade-in" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-[480px] max-h-[64vh] flex flex-col overflow-hidden" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-stone-200">
          <div>
            <h3 className="font-semibold text-stone-800 tracking-tight">选择知识领域</h3>
            <p className="text-[12px] text-stone-400 mt-0.5">挑一个方向进行系统性考核</p>
          </div>
          <button onClick={onClose} className="w-8 h-8 rounded-lg flex items-center justify-center text-stone-400 hover:bg-stone-100 hover:text-stone-700 transition-colors">
            <IconClose size={18} />
          </button>
        </div>

        <div className="px-5 py-3 border-b border-stone-200">
          <div className="flex items-center gap-2 bg-stone-100 rounded-lg px-3">
            <IconSearch size={16} className="text-stone-400" />
            <input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="搜索技能…"
              className="flex-1 text-[14px] bg-transparent py-2.5 focus:outline-none placeholder:text-stone-400 text-stone-700"
            />
            <button onClick={onRefresh} className="text-[12px] text-indigo-600 hover:text-indigo-700 font-medium px-2 py-1">刷新</button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-2.5">
          {loading ? (
            <div className="flex items-center justify-center py-12"><SpinnerDot /></div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-12 text-[13px] text-stone-400">暂无技能数据</div>
          ) : (
            <div className="grid grid-cols-2 gap-2 p-1">
              {filtered.map((s) => {
                const active = selected === s.name;
                return (
                  <button
                    key={s.name}
                    onClick={() => onSelect(s.name)}
                    className={`text-left px-3.5 py-3 rounded-xl transition-all ${
                      active ? 'bg-indigo-50/70 ring-1 ring-indigo-200' : 'bg-white border border-stone-200 hover:border-indigo-300 hover:bg-stone-50'
                    }`}
                  >
                    <div className={`text-[13px] truncate ${active ? 'text-indigo-700 font-medium' : 'text-stone-700'}`}>{s.name}</div>
                    <div className="text-[11px] text-stone-400 mt-0.5">{s.count} 个岗位涉及</div>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div className="px-5 py-3 border-t border-stone-200 flex justify-between items-center">
          <span className="text-[12px] text-stone-400">共 {skills.length} 个技能</span>
          <button onClick={onClose} className="text-[13px] text-stone-500 hover:text-stone-800 transition-colors">关闭</button>
        </div>
      </div>
    </div>
  );
}

/* ============================================================
 * 消息气泡
 * ========================================================== */
function MessageBubble({ message, currentMode }: { message: UnifiedMessage; currentMode: ChatMode }) {
  const isUser = message.role === 'user';

  if (isUser) {
    return (
      <div className="msg-in flex gap-3 flex-row-reverse">
        <div className="w-8 h-8 rounded-full bg-stone-800 text-white flex items-center justify-center text-[12px] font-medium flex-shrink-0">我</div>
        <div className="bg-stone-800 text-white rounded-2xl rounded-tr-md px-4 py-3 max-w-[78%]">
          <div className="text-[14px] whitespace-pre-wrap leading-relaxed">{message.content}</div>
        </div>
      </div>
    );
  }

  const intentLabel = message.intent ? INTENT_LABELS[message.intent] : null;
  const Icon = MODE_ICON[currentMode];

  return (
    <div className="msg-in flex gap-3">
      <div className="w-8 h-8 rounded-full bg-white border border-stone-200 flex items-center justify-center text-indigo-600 flex-shrink-0">
        <Icon size={17} />
      </div>
      <div className="max-w-[78%] space-y-2.5">
        {intentLabel && (
          <span className="inline-flex items-center gap-1.5 text-[11px] text-stone-500">
            <span className={`w-1.5 h-1.5 rounded-full ${intentLabel.dot}`} />
            {intentLabel.text}
          </span>
        )}
        <div className="bg-white border border-stone-200 rounded-2xl rounded-tl-md px-4 py-3">
          <div className="text-[14px] text-stone-700 whitespace-pre-wrap leading-relaxed">{message.content}</div>
        </div>
        {message.jobCards && message.jobCards.length > 0 && (
          <div className="space-y-2.5">
            {message.jobCards.slice(0, 5).map((job, i) => (
              <JobCard key={i} job={job} />
            ))}
            {message.jobCards.length > 5 && <div className="text-[12px] text-stone-400 px-2">还有 {message.jobCards.length - 5} 个岗位…</div>}
          </div>
        )}
        {message.matchResults && message.matchResults.length > 0 && (
          <div className="space-y-2.5">
            {message.matchResults.map((m, i) => (
              <MatchCard key={i} match={m} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* ============================================================
 * 岗位卡片
 * ========================================================== */
function JobCard({ job }: { job: JobItem }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div
      onClick={() => setExpanded(!expanded)}
      className="bg-white border border-stone-200 border-l-2 border-l-indigo-500 rounded-xl px-3.5 py-3 hover:shadow-sm hover:border-stone-300 transition-all cursor-pointer"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="font-medium text-[14px] text-stone-800 truncate">{job.title}</div>
          <div className="text-[12px] text-stone-500 mt-0.5">{job.company} · {job.city}</div>
          <div className="flex items-center gap-2 mt-1">
            <span className="text-[12px] font-semibold text-indigo-600">{job.salary}</span>
            <span className="text-[12px] text-stone-400">{job.experience}</span>
          </div>
        </div>
        {job.skills && job.skills.length > 0 && (
          <div className="flex flex-wrap gap-1.5 justify-end max-w-[50%]">
            {job.skills.slice(0, 3).map((s) => (
              <span key={s} className="text-[11px] px-2 py-0.5 rounded-full bg-stone-100 text-stone-500 border border-stone-200">{s}</span>
            ))}
          </div>
        )}
      </div>
      {expanded && job.description && (
        <div className="mt-2.5 pt-2.5 border-t border-stone-100 text-[12px] text-stone-500 whitespace-pre-wrap leading-relaxed">{job.description}</div>
      )}
    </div>
  );
}

/* ============================================================
 * 匹配结果卡片
 * ========================================================== */
function MatchCard({ match }: { match: MatchResult }) {
  const tone =
    match.match_score >= 70 ? 'text-emerald-600' :
    match.match_score >= 40 ? 'text-amber-500' :
    'text-rose-500';

  return (
    <div className="bg-white border border-stone-200 border-l-2 border-l-emerald-500 rounded-xl px-3.5 py-3">
      <div className="flex items-center justify-between">
        <div className="flex-1 min-w-0">
          <div className="font-medium text-[14px] text-stone-800 truncate">{match.job_title}</div>
          <div className="text-[12px] text-stone-500 mt-0.5">{match.company}</div>
        </div>
        <div className={`text-[19px] font-semibold tabular-nums ml-2 ${tone}`}>{match.match_score}%</div>
      </div>
      <div className="flex flex-wrap gap-1.5 mt-2.5">
        {match.matched_skills?.slice(0, 5).map((s) => (
          <span key={s} className="text-[11px] px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-100">✓ {s}</span>
        ))}
        {match.missing_skills?.slice(0, 3).map((s) => (
          <span key={s} className="text-[11px] px-2 py-0.5 rounded-full bg-rose-50 text-rose-600 border border-rose-100">✗ {s}</span>
        ))}
      </div>
      {match.gap_analysis && (
        <div className="text-[12px] text-stone-500 mt-2.5 leading-relaxed">{match.gap_analysis}</div>
      )}
    </div>
  );
}

/* 极简点状加载 */
function SpinnerDot() {
  return (
    <span className="flex gap-1.5">
      <i className="w-2 h-2 rounded-full bg-stone-300 animate-bounce" style={{ animationDelay: '0ms' }} />
      <i className="w-2 h-2 rounded-full bg-stone-300 animate-bounce" style={{ animationDelay: '150ms' }} />
      <i className="w-2 h-2 rounded-full bg-stone-300 animate-bounce" style={{ animationDelay: '300ms' }} />
    </span>
  );
}
