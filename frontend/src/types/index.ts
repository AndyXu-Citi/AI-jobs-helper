// ===== 岗位数据 =====
export interface JobItem {
  id: string;
  title: string;
  company: string;
  salary: string;
  city: string;
  experience: string;
  education: string;
  skills: string[];
  description?: string;
  tags?: string[];
  source?: string;
  url?: string;
}

// ===== 检索结果 =====
export interface SearchResult {
  title: string;
  content: string;
  score: number;
  source: string;
  url?: string;
}

// ===== 统一对话系统 =====
/** 两种模式：求职助手（默认）/ 面试官 */
export type ChatMode = 'assistant' | 'interviewer';

/** 面试官子模式 */
export type InterviewSubMode = 'jd' | 'resume' | 'project' | 'knowledge';

/** 消息意图标签（用于展示 Agent 做了什么） */
export type MessageIntent =
  | 'search'       // 🔍 岗位搜索（RAG）
  | 'match'        // 📋 简历匹配
  | 'diagnose'     // 🩺 简历诊断
  | 'interview'    // 👨‍💼 面试问答
  | 'reject'       // 🚫 礼貌拒绝
  | 'chat';        // 💬 普通对话

/** 附件（上传的简历 PDF 等） */
export interface FileAttachment {
  id: string;
  name: string;
  type: 'pdf' | 'text';
  size: number;
  /** 后端解析后的文本内容 */
  content?: string;
}

/** 统一消息结构 */
export interface UnifiedMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  intent?: MessageIntent;
  timestamp: number;
  /** RAG 检索引用来源 */
  sources?: SearchResult[];
  /** 内嵌岗位卡片（搜索结果） */
  jobCards?: JobItem[];
  /** 简历匹配结果 */
  matchResults?: MatchResult[];
  /** 附件 */
  attachments?: FileAttachment[];
  /** Agent 思考过程（每步做了什么），用于 UI 展示 */
  steps?: { label: string; status: 'running' | 'done'; detail?: string }[];
}

/** 统一对话请求 */
export interface UnifiedChatRequest {
  message: string;
  mode: ChatMode;
  session_id?: string;
  resume_text?: string;
  jd_text?: string;
  interview_submode?: InterviewSubMode;
  /** 知识点面试：选中的技能/领域名称 */
  skill_topic?: string;
}

/** 统一对话响应 */
export interface UnifiedChatResponse {
  reply: string;
  intent?: MessageIntent;
  session_id?: string;
  sources?: SearchResult[];
  job_cards?: JobItem[];
  match_results?: MatchResult[];
  follow_ups?: string[];
}

// ===== 技能报表 =====
export interface SkillStat {
  skill: string;
  count: number;
  jobs: string[];
  percentage?: number;
}

export interface ReportData {
  total_jobs: number;
  skills: SkillStat[];
  cities: { city: string; count: number }[];
  salary_ranges: { range: string; count: number }[];
}

// ===== 简历匹配 =====
export interface MatchResult {
  job_title: string;
  company: string;
  match_score: number;
  matched_skills: string[];
  missing_skills: string[];
  gap_analysis: string;
  suggestions: string[];
}

// ===== 用户档案 =====
export interface UserProfile {
  name: string;
  target_position: string;
  target_cities: string[];
  expected_salary: string;
  skills: string[];
  experience_years: number;
  education: string;
  projects: ProjectSummary[];
}

export interface ProjectSummary {
  name: string;
  description: string;
  tech_stack: string[];
  role: string;
  highlights: string[];
}

// ===== Tab 枚举 =====
export type TabId = 'chat' | 'jobs' | 'report';

// ===== 对话历史（DeepSeek 风格左侧边栏）=====
export interface Conversation {
  id: string;
  title: string;
  mode: ChatMode;
  interviewSubMode?: InterviewSubMode;
  createdAt: number;
  updatedAt: number;
  messageCount: number;
  /** 预留：后续对接数据库记忆模块 */
  persisted?: boolean;
}

// ===== 组件 Props 通用类型 =====
export interface LoadingProps {
  loading?: boolean;
  text?: string;
}
