import { create } from 'zustand';
import type { TabId, JobItem, UnifiedMessage, ChatMode, InterviewSubMode, FileAttachment, Conversation } from '../types';

// ===== Tab Store =====
interface TabState {
  activeTab: TabId;
  setActiveTab: (tab: TabId) => void;
}

export const useTabStore = create<TabState>((set) => ({
  activeTab: 'chat',
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
  };
  loading: boolean;
  error: string | null;

  setJobs: (jobs: JobItem[]) => void;
  setSelectedJob: (job: JobItem | null) => void;
  setFilter: (key: 'city' | 'keyword', value: string) => void;
  setSkills: (skills: string[]) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
}

export const useJobStore = create<JobState>((set, get) => ({
  jobs: [],
  filteredJobs: [],
  selectedJob: null,
  filters: { city: '', keyword: '', skills: [] },
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

function applyFilters(jobs: JobItem[], filters: { city: string; keyword: string; skills: string[] }): JobItem[] {
  return jobs.filter((job) => {
    if (filters.city && !job.city.includes(filters.city)) return false;
    if (filters.keyword && !job.title.toLowerCase().includes(filters.keyword.toLowerCase()) &&
        !job.company.toLowerCase().includes(filters.keyword.toLowerCase())) return false;
    if (filters.skills.length > 0 && !filters.skills.some((sk) =>
      job.skills.some((js) => js.toLowerCase().includes(sk.toLowerCase()))
    )) return false;
    return true;
  });
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

  // 操作
  createConversation: (mode: ChatMode, subMode?: InterviewSubMode) => string;
  setActiveConversation: (id: string | null) => void;
  updateConversationTitle: (id: string, title: string) => void;
  updateConversationMeta: (id: string, meta: Partial<Pick<Conversation, 'messageCount' | 'updatedAt' | 'interviewSubMode'>>) => void;
  deleteConversation: (id: string) => void;
}

let conversationIdCounter = 0;

export const useConversationStore = create<ConversationState>((set, get) => ({
  conversations: [],
  activeConversationId: null,

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
}));
