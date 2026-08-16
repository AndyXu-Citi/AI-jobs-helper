import { useEffect, useMemo, useState } from 'react';
import { jobsApi } from '../api';
import { useJobStore } from '../stores';
import { Card, Tag, EmptyState, Spinner, Button } from '../components/ui';
import type { JobItem } from '../types';

export function JobLibraryPage() {
  const {
    jobs,
    filteredJobs,
    selectedJob,
    filters,
    loading,
    error,
    setJobs,
    setSelectedJob,
    setFilter,
    setSkills,
    setLoading,
    setError,
  } = useJobStore();

  // 技能下拉展开状态
  const [skillDropdownOpen, setSkillDropdownOpen] = useState(false);

  // Load jobs on mount
  useEffect(() => {
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await jobsApi.list();
        setJobs(res);
        // 默认选中第一条，右侧直接展示详情
        if (res.length > 0 && !selectedJob) {
          setSelectedJob(res[0]);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : '加载失败');
      } finally {
        setLoading(false);
      }
    }
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Extract unique filter options
  const cities = useMemo(() => [...new Set(jobs.map((j) => j.city).filter(Boolean))], [jobs]);

  // 技能列表 + 出现次数，按次数降序
  const skillsWithCount = useMemo(() => {
    const map = new Map<string, number>();
    jobs.forEach((j) => j.skills?.forEach((s) => map.set(s, (map.get(s) || 0) + 1)));
    return [...map.entries()].sort((a, b) => b[1] - a[1]);
  }, [jobs]);

  // 切换单个技能选中状态（toggle）
  const toggleSkill = (skill: string) => {
    const current = filters.skills;
    if (current.includes(skill)) {
      setSkills(current.filter((s) => s !== skill));
    } else {
      setSkills([...current, skill]);
    }
  };

  // 点击外部关闭下拉
  useEffect(() => {
    if (!skillDropdownOpen) return;
    function handler(e: MouseEvent) {
      const target = e.target as HTMLElement;
      if (!target.closest('.skill-multi-select')) {
        setSkillDropdownOpen(false);
      }
    }
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [skillDropdownOpen]);

  return (
    <div className="flex flex-col gap-4">
      {/* Filters */}
      <Card padding="sm" className="flex flex-wrap items-center gap-3">
        <span className="text-sm font-medium text-text-secondary">筛选：</span>

        <select
          value={filters.city}
          onChange={(e) => setFilter('city', e.target.value)}
          className="text-xs rounded border border-border-light bg-surface-0 px-2 py-1"
        >
          <option value="">全部城市</option>
          {cities.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>

        {/* 薪资范围 */}
        <select
          value={filters.salaryRange}
          onChange={(e) => setFilter('salaryRange', e.target.value)}
          className="text-xs rounded border border-border-light bg-surface-0 px-2 py-1"
        >
          <option value="">全部薪资</option>
          <option value="0-10">10K 以下</option>
          <option value="10-20">10-20K</option>
          <option value="20-30">20-30K</option>
          <option value="30-50">30-50K</option>
          <option value="50-999">50K 以上</option>
        </select>

        {/* 技能多选下拉 */}
        <div className="skill-multi-select relative">
          <button
            type="button"
            onClick={() => setSkillDropdownOpen(!skillDropdownOpen)}
            className="text-xs rounded border border-border-light bg-surface-0 px-2 py-1 min-w-[120px] text-left flex items-center justify-between gap-1 hover:border-brand-300 transition-colors"
          >
            <span className="truncate">
              {filters.skills.length === 0
                ? '全部技能'
                : filters.skills.length <= 2
                  ? filters.skills.join(', ')
                  : `${filters.skills[0]} +${filters.skills.length - 1}`}
            </span>
            <span className="text-text-muted text-[10px]">▾</span>
          </button>

          {skillDropdownOpen && (
            <div className="absolute top-full left-0 mt-1 w-64 max-h-[280px] overflow-y-auto bg-surface-0 border border-border-light rounded-md shadow-lg z-50">
              {/* 已选提示 */}
              {filters.skills.length > 0 && (
                <div className="px-3 py-2 border-b border-border-light flex items-center justify-between bg-brand-50/50">
                  <span className="text-xs text-text-secondary">已选 {filters.skills.length} 项</span>
                  <button
                    type="button"
                    onClick={() => setSkills([])}
                    className="text-xs text-brand-600 hover:text-brand-700 font-medium"
                  >
                    清空
                  </button>
                </div>
              )}
              {/* 技能列表（带次数） */}
              {skillsWithCount.map(([skill, count]) => {
                const selected = filters.skills.includes(skill);
                return (
                  <button
                    key={skill}
                    type="button"
                    onClick={() => toggleSkill(skill)}
                    className={`w-full px-3 py-1.5 text-left text-xs flex items-center justify-between hover:bg-surface-1 transition-colors ${
                      selected ? 'bg-brand-50 text-brand-700' : 'text-text-primary'
                    }`}
                  >
                    <span className={`flex items-center gap-1.5 ${selected ? 'font-medium' : ''}`}>
                      <span className={`w-3.5 h-3.5 rounded flex items-center justify-center text-[10px] border ${
                        selected
                          ? 'bg-brand-500 text-white border-brand-500'
                          : 'border-border-light text-transparent hover:border-brand-300'
                      }`}>
                        {selected ? '✓' : ''}
                      </span>
                      {skill}
                    </span>
                    <span className="text-text-muted tabular-nums">{count}</span>
                  </button>
                );
              })}
              {skillsWithCount.length === 0 && (
                <div className="px-3 py-4 text-xs text-text-muted text-center">暂无技能数据</div>
              )}
            </div>
          )}
        </div>

        <input
          value={filters.keyword}
          onChange={(e) => setFilter('keyword', e.target.value)}
          placeholder="搜索岗位/公司..."
          className="text-xs rounded border border-border-light bg-surface-0 px-2 py-1 w-40"
        />

        <span className="text-xs text-text-muted ml-auto">
          共 {filteredJobs.length} 条 / {jobs.length} 条
        </span>
      </Card>

      {/* Master-Detail Layout */}
      {loading ? (
        <Spinner size="lg" />
      ) : error ? (
        <EmptyState title="加载失败" description={error} action={<Button onClick={() => window.location.reload()}>重试</Button>} />
      ) : (
        <div className="grid grid-cols-[340px_1fr] gap-4 min-h-[600px]" style={{ height: 'calc(100vh - 220px)' }}>
          {/* Left: Job List */}
          <Card padding="none" className="overflow-hidden flex flex-col">
            <div className="px-4 py-2.5 border-b border-border-light bg-surface-1 font-semibold text-sm">
              岗位列表 ({filteredJobs.length})
            </div>
            <div className="overflow-y-auto flex-1">
              {filteredJobs.length === 0 ? (
                <EmptyState title="无匹配结果" description="尝试调整筛选条件" />
              ) : (
                filteredJobs.map((job) => (
                  <JobListItem
                    key={job.id}
                    job={job}
                    active={selectedJob?.id === job.id}
                    onClick={() => setSelectedJob(job)}
                  />
                ))
              )}
            </div>
          </Card>

          {/* Right: Job Detail */}
          <Card padding="none" className="overflow-y-auto">
            {selectedJob ? (
              <JobDetail job={selectedJob} onClose={() => setSelectedJob(null)} />
            ) : (
              <EmptyState title="选择岗位查看详情" description="点击左侧列表中的任意岗位" />
            )}
          </Card>
        </div>
      )}
    </div>
  );
}

// ===== Job List Item =====
function JobListItem({ job, active, onClick }: { job: JobItem; active: boolean; onClick: () => void }) {
  return (
    <div
      onClick={onClick}
      className={`px-4 py-3 cursor-pointer border-b border-border-light transition-all duration-150 ${
        active
          ? 'bg-brand-50 border-l-4 border-l-brand-500 -ml-[1px]'
          : 'hover:bg-surface-1 border-l-4 border-l-transparent -ml-[1px]'
      }`}
    >
      <div className={`font-medium text-sm truncate ${active ? 'text-brand-700' : 'text-text-primary'}`}>
        {job.title}
      </div>
      <div className="text-xs text-text-secondary mt-0.5">{job.company}</div>
      <div className="flex items-center gap-2 mt-1.5">
        <span className="text-xs font-semibold text-success">{job.salary}</span>
        <span className="text-xs text-text-muted">{job.city}</span>
        <span className="text-xs text-text-muted">|</span>
        <span className="text-xs text-text-muted">{job.experience}</span>
      </div>
      <div className="flex flex-wrap gap-1 mt-1.5">
        {job.skills?.slice(0, 3).map((s) => (
          <Tag key={s} size="sm" variant="info">{s}</Tag>
        ))}
        {job.skills && job.skills.length > 3 && (
          <Tag size="sm">+{job.skills.length - 3}</Tag>
        )}
      </div>
    </div>
  );
}

// ===== Job Detail Panel =====
function JobDetail({ job, onClose }: { job: JobItem; onClose: () => void }) {
  return (
    <div className="p-5 space-y-4">
      <div className="flex justify-between items-start">
        <div>
          <h2 className="text-lg font-bold text-text-primary">
            {job.url ? (
              <a
                href={job.url}
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-brand-600 hover:underline"
                title="在 Boss 直聘打开"
              >
                {job.title}
              </a>
            ) : (
              job.title
            )}
          </h2>
          <p className="text-sm text-text-secondary mt-0.5">{job.company}</p>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose}>✕</Button>
      </div>

      <div className="flex flex-wrap gap-3 text-sm">
        <span className="inline-flex items-center gap-1 text-success font-semibold">
          💰 {job.salary}
        </span>
        <span>📍 {job.city}</span>
        <span>📅 {job.experience}</span>
        <span>🎓 {job.education}</span>
      </div>

      {job.skills && job.skills.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-text-primary mb-2">技能要求</h3>
          <div className="flex flex-wrap gap-1.5">
            {job.skills.map((s) => (
              <Tag key={s} variant="info" size="md">{s}</Tag>
            ))}
          </div>
        </div>
      )}

      {job.description && (
        <div>
          <h3 className="text-sm font-semibold text-text-primary mb-2">职位描述</h3>
          <div className="text-sm text-text-secondary whitespace-pre-wrap leading-relaxed bg-surface-1 p-3 rounded-md">
            {job.description}
          </div>
        </div>
      )}

      {job.tags && job.tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pt-2 border-t border-border-light">
          {job.tags.map((t) => (
            <Tag key={t}>{t}</Tag>
          ))}
        </div>
      )}
    </div>
  );
}
