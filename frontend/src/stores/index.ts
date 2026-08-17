import { create } from 'zustand';
import type { TabId, JobItem, UnifiedMessage, ChatMode, InterviewSubMode, FileAttachment, Conversation } from '../types';

// ===== Tab Store =====
interface TabState {
  activeTab: TabId;
  setActiveTab: (tab: TabId) => void;
}

export const useTabStore = create<TabState>((set) => ({
  activeTab: 'jobs',
  setActiveTab: (tab) => set({ activeTab: tab }),
}));

// ===== Job Store (岗位库) =====
interface JobState {
  jobs: JobItem[];
  filteredJobs: JobItem[];
  selectedJob: JobItem | null;
  filters: {
    city: string;
    keyword: string;
    skills: string[];        // 多选技能（OR 逻辑）
    salaryRange: string;     // 薪资范围：'' | '0-10' | '10-20' | '20-30' | '30-50' | '50-999'
  };
  loading: boolean;
  error: string | null;

  setJobs: (jobs: JobItem[]) => void;
  setSelectedJob: (job: JobItem | null) => void;
  setFilter: (key: 'city' | 'keyword' | 'salaryRange', value: string) => void;
  setSkills: (skills: string[]) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
}

export const useJobStore = create<JobState>((set, get) => ({
  jobs: [],
  filteredJobs: [],
  selectedJob: null,
  filters: { city: '', keyword: '', skills: [], salaryRange: '' },
  loading: false,
  error: null,

  setJobs: (jobs) =>
    set((state) => {
      const f = applyFilters(jobs, state.filters);
      return { jobs, filteredJobs: f };
    }),

  setSelectedJob: (job) => set({ selectedJob: job }),

  setFilter: (key, value) =>
    set((state) => {
      const filters = { ...state.filters, [key]: value };
      const filtered = applyFilters(state.jobs, filters);
      return { filters, filteredJobs: filtered };
    }),

  setSkills: (skills) =>
    set((state) => {
      const filters = { ...state.filters, skills };
      const filtered = applyFilters(state.jobs, filters);
      return { filters, filteredJobs: filtered };
    }),

  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),
}));

function applyFilters(jobs: JobItem[], filters: { city: string; keyword: string; skills: string[]; salaryRange: string }): JobItem[] {
  return jobs.filter((job) => {
    if (filters.city && !job.city.includes(filters.city)) return false;
    if (filters.keyword && !job.title.toLowerCase().includes(filters.keyword.toLowerCase()) &&
        !job.company.toLowerCase().includes(filters.keyword.toLowerCase())) return false;
    if (filters.skills.length > 0 && !filters.skills.some((sk) =>
      job.skills.some((js) => js.toLowerCase().includes(sk.toLowerCase()))
    )) return false;
    if (filters.salaryRange) {
      const parsed = parseSalaryK(job.salary);
      if (!parsed) return false;
      const [rMin, rMax] = filters.salaryRange.split('-').map((n) => parseInt(n, 10));
      if (parsed.max < rMin || parsed.min > rMax) return false;
    }
    return true;
  });
}

/** 解析形如 "30-45K·16薪" / "20-40K" / "50K" 的月薪范围，返回 K 为单位的数值区间 */
function parseSalaryK(salary: string): { min: number; max: number } | null {
  const match = salary.match(/(\d+)(?:\s*[-~]\s*(\d+))?\s*[Kk]/);
  if (!match) return null;
  const min = parseInt(match[1], 10);
  const max = match[2] ? parseInt(match[2], 10) : min;
  return { min, max };
}

// ===== 统一 Chat Store =====
interface ChatState {
  // 模式
  mode: ChatMode;
  interviewSubMode: InterviewSubMode;
  sessionId: string | null;

  // 上下文
  resume: FileAttachment | null;   // 上传的简历
  jdText: string;                   // 面试用 JD 文本
  selectedSkillTopic: string | null; // 知识点面试选中的技能名

  // 消息
  messages: UnifiedMessage[];
  isStreaming: boolean;
  streamingContent: string;

  // 操作
  setMode: (mode: ChatMode) => void;
  setInterviewSubMode: (sub: InterviewSubMode) => void;
  setSessionId: (id: string | null) => void;
  setResume: (resume: FileAttachment | null) => void;
  setJdText: (text: string) => void;
  setSelectedSkillTopic: (topic: string | null) => void;
  addMessage: (msg: UnifiedMessage) => void;
  setMessages: (messages: UnifiedMessage[]) => void;
  setStreaming: (streaming: boolean, content?: string) => void;
  appendStreamContent: (chunk: string) => void;
  finalizeStream: (intent?: UnifiedMessage['intent'], extra?: Partial<UnifiedMessage>) => void;
  clearMessages: () => void;
  resetSession: () => void;
}

export const useChatStore = create<ChatState>((set) => ({
  mode: 'assistant',
  interviewSubMode: 'resume',
  sessionId: null,
  resume: null,
  jdText: '',
  selectedSkillTopic: null,
  messages: [],
  isStreaming: false,
  streamingContent: '',

  setMode: (mode) =>
    set((s) => ({
      mode,
      // 切换模式时清空当前对话和 session
      messages: [],
      sessionId: null,
      isStreaming: false,
      streamingContent: '',
    })),

  setInterviewSubMode: (sub) =>
    set((s) => ({
      interviewSubMode: sub,
      // 切换面试子模式也清空对话
      messages: [],
      sessionId: null,
    })),

  setSessionId: (id) => set({ sessionId: id }),
  setResume: (resume) => set({ resume }),
  setJdText: (text) => set({ jdText: text }),
  setSelectedSkillTopic: (topic) => set({ selectedSkillTopic: topic }),

  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),

  setMessages: (messages) => set({ messages }),

  setStreaming: (streaming, content = '') => set({ isStreaming: streaming, streamingContent: content }),

  appendStreamContent: (chunk) => set((s) => ({ streamingContent: s.streamingContent + chunk })),

  finalizeStream: (intent, extra) =>
    set((s) => ({
      messages: [
        ...s.messages,
        {
          id: `msg-${Date.now()}`,
          role: 'assistant',
          content: s.streamingContent,
          intent,
          timestamp: Date.now(),
          ...extra,
        },
      ],
      isStreaming: false,
      streamingContent: '',
    })),

  clearMessages: () => set({ messages: [], sessionId: null, isStreaming: false, streamingContent: '' }),

  resetSession: () =>
    set({
      messages: [],
      sessionId: null,
      isStreaming: false,
      streamingContent: '',
      resume: null,
      jdText: '',
    }),
}));

// ===== 对话历史 Store（DeepSeek 风格左侧边栏）=====
interface ConversationState {
  conversations: Conversation[];
  activeConversationId: string | null;
  loading: boolean;

  // 操作
  createConversation: (mode: ChatMode, subMode?: InterviewSubMode) => string;
  setConversations: (conversations: Conversation[]) => void;
  setActiveConversation: (id: string | null) => void;
  updateConversationTitle: (id: string, title: string) => void;
  updateConversationMeta: (id: string, meta: Partial<Pick<Conversation, 'messageCount' | 'updatedAt' | 'interviewSubMode'>>) => void;
  deleteConversation: (id: string) => void;
  setLoading: (loading: boolean) => void;
}

let conversationIdCounter = 0;

export const useConversationStore = create<ConversationState>((set, get) => ({
  conversations: [],
  activeConversationId: null,
  loading: false,

  createConversation: (mode, subMode) => {
    const id = `conv-${Date.now()}-${++conversationIdCounter}`;
    const now = Date.now();
    const newConv: Conversation = {
      id,
      title: '新对话',
      mode,
      interviewSubMode: subMode,
      createdAt: now,
      updatedAt: now,
      messageCount: 0,
      persisted: false,
    };
    set((s) => ({
      conversations: [newConv, ...s.conversations],
      activeConversationId: id,
    }));
    return id;
  },

  setConversations: (conversations) => set({ conversations }),

  setActiveConversation: (id) => set({ activeConversationId: id }),

  updateConversationTitle: (id, title) =>
    set((s) => ({
      conversations: s.conversations.map((c) =>
        c.id === id ? { ...c, title } : c
      ),
    })),

  updateConversationMeta: (id, meta) =>
    set((s) => ({
      conversations: s.conversations.map((c) =>
        c.id === id ? { ...c, ...meta, updatedAt: Date.now() } : c
      ),
    })),

  deleteConversation: (id) =>
    set((s) => ({
      conversations: s.conversations.filter((c) => c.id !== id),
      activeConversationId: s.activeConversationId === id ? null : s.activeConversationId,
    })),

  setLoading: (loading) => set({ loading }),
}));
