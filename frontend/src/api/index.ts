import type {
  JobItem,
  UnifiedChatRequest,
  UnifiedChatResponse,
  MatchResult,
} from '../types';

// 后端实际返回的报表数据格式（与后端 app.py 对齐）
export interface RawReportData {
  total_jobs: number;
  skills: { name: string; count: number; pct: number }[];
  cities: { name: string; count: number; pct: number }[];
  experience: { name: string; count: number; pct: number }[];
  degree: { name: string; count: number; pct: number }[];
  salary_bands: { name: string; count: number }[];
  my_coverage: {
    have: { skill: string; count: number }[];
    learning: { skill: string; count: number }[];
    missing_top: { skill: string; count: number }[];
  };
}

const BASE = '/api';

// ===== 通用请求封装（后端返回裸对象，无 {code,data} 包装）=====
async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: res.statusText, detail: res.statusText }));
    throw new Error((err as any).detail || (err as any).message || (err as any).error || `HTTP ${res.status}`);
  }
  return res.json();
}

// ===== SSE 流式请求 =====
export async function* streamChat(query: string): AsyncGenerator<string> {
  const res = await fetch(`${BASE}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query }),
  });

  if (!res.ok || !res.body) {
    throw new Error('Stream request failed');
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed === '' || trimmed === '[DONE]') continue;
      if (trimmed.startsWith('data: ')) {
        try {
          const data = JSON.parse(trimmed.slice(6));
          yield data.content || data.text || data.reply || JSON.stringify(data);
        } catch {
          yield trimmed.slice(6);
        }
      }
    }
  }
}

// ===== 统一对话 API（核心入口）=====
export const chatApi = {
  /** 统一对话：自动意图识别 + 路由分发 */
  unified: (req: UnifiedChatRequest): Promise<UnifiedChatResponse> =>
    request<UnifiedChatResponse>('/chat/unified', {
      method: 'POST',
      body: JSON.stringify(req),
    }),
};

// ===== 简历上传 API =====
export const resumeApi = {
  /** 上传 PDF 简历，返回解析后的文本 */
  upload: async (file: File): Promise<{ filename: string; size: number; text: string; char_count: number }> => {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${BASE}/resume/upload`, {
      method: 'POST',
      body: formData,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: res.statusText }));
      throw new Error((err as any).error || `上传失败 HTTP ${res.status}`);
    }
    return res.json();
  },
};

// ===== 岗位库 =====
// 后端实际返回 { total, jobs: [...] }，且字段名与前端不一致，这里做映射
interface RawJobItem {
  title: string;
  brand: string;
  city: string;
  salary_desc: string;
  experience: string;
  degree: string;
  skills: string[];
  post_description: string;
  url: string;
}

function mapRawJob(raw: RawJobItem, index: number): JobItem {
  return {
    id: `job-${index}-${raw.title.slice(0, 8)}`,
    title: raw.title,
    company: raw.brand,
    salary: raw.salary_desc,
    city: raw.city,
    experience: raw.experience,
    education: raw.degree,
    skills: raw.skills || [],
    description: raw.post_description,
    url: raw.url,
  };
}

export const jobsApi = {
  list: (params?: { city?: string; keyword?: string; skill?: string; limit?: number }): Promise<JobItem[]> => {
    const search = new URLSearchParams();
    if (params?.city) search.set('city', params.city);
    if (params?.keyword) search.set('keyword', params.keyword);
    if (params?.skill) search.set('skill', params.skill);
    // 后端默认 limit=20，前端默认请求全部（传个大数）
    if (params?.limit !== undefined) search.set('limit', String(params.limit));
    else search.set('limit', '9999');
    const qs = search.toString();
    return request<{ total: number; jobs: RawJobItem[] }>(`/jobs${qs ? `?${qs}` : ''}`).then((res) =>
      res.jobs.map(mapRawJob)
    );
  },

  get: (id: string): Promise<JobItem> =>
    request<JobItem>(`/jobs/${id}`),
};

// ===== 技能报表（返回后端原始格式）=====
export const reportApi = {
  get: (): Promise<RawReportData> =>
    request<RawReportData>('/report'),
};
