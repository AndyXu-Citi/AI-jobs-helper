import { useEffect, useState } from 'react';
import { reportApi, type RawReportData } from '../api';
import { Card, SkillBar, EmptyState, Spinner } from '../components/ui';

export function SkillReportPage() {
  const [data, setData] = useState<RawReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        // reportApi.get() 现在直接返回后端裸数据（无 .data 包装）
        const res = await reportApi.get();
        setData(res);
      } catch (err) {
        setError(err instanceof Error ? err.message : '加载失败');
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  if (loading) return <Spinner size="lg" />;
  if (error || !data) return <EmptyState title="加载失败" description={error || undefined} />;

  return (
    <div className="space-y-5">
      {/* Summary Cards */}
      <div className="grid grid-cols-3 gap-4">
        <StatCard label="总岗位数" value={data.total_jobs} color="brand" />
        <StatCard label="技能种类" value={data.skills.length} color="success" />
        <StatCard label="覆盖城市" value={data.cities.length} color="warning" />
      </div>

      {/* Skills Chart */}
      <Card padding="lg">
        <h2 className="text-base font-semibold text-text-primary mb-4">技能需求分布</h2>
        <div className="space-y-0.5">
          {data.skills.map((s) => (
            <SkillBar
              key={s.name}
              skill={s.name}
              count={s.count}
              total={data.total_jobs}
              maxCount={data.skills[0]?.count}
            />
          ))}
        </div>
      </Card>

      {/* Cities & Salary */}
      <div className="grid grid-cols-2 gap-4">
        <Card padding="lg">
          <h3 className="text-sm font-semibold text-text-primary mb-3">城市分布</h3>
          <div className="space-y-2">
            {data.cities.slice(0, 10).map((c) => (
              <div key={c.name} className="flex items-center justify-between text-sm">
                <span className="text-text-secondary">{c.name}</span>
                <span className="font-medium text-text-primary tabular-nums">{c.count}</span>
                <span className="text-xs text-text-muted ml-1">{c.pct}%</span>
              </div>
            ))}
          </div>
        </Card>

        <Card padding="lg">
          <h3 className="text-sm font-semibold text-text-primary mb-3">薪资范围</h3>
          <div className="space-y-2">
            {data.salary_bands.map((r) => (
              <div key={r.name} className="flex items-center justify-between text-sm">
                <span className="text-text-secondary">{r.name}</span>
                <span className="font-medium text-text-primary tabular-nums">{r.count}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* My Coverage */}
      {data.my_coverage && (
        <Card padding="lg">
          <h3 className="text-sm font-semibold text-text-primary mb-3">我的技能覆盖</h3>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <div className="text-xs text-success font-medium mb-1.5">已掌握 ({data.my_coverage.have.length})</div>
              <div className="flex flex-wrap gap-1">
                {data.my_coverage.have.map((item) => (
                  <span key={item.skill} className="text-xs bg-green-50 text-success px-2 py-0.5 rounded">{item.skill}</span>
                ))}
              </div>
            </div>
            <div>
              <div className="text-xs text-warning font-medium mb-1.5">学习中 ({data.my_coverage.learning.length})</div>
              <div className="flex flex-wrap gap-1">
                {data.my_coverage.learning.map((item) => (
                  <span key={item.skill} className="text-xs bg-amber-50 text-warning px-2 py-0.5 rounded">{item.skill}</span>
                ))}
              </div>
            </div>
            <div>
              <div className="text-xs text-danger font-medium mb-1.5">待补齐 ({data.my_coverage.missing_top.length})</div>
              <div className="flex flex-wrap gap-1">
                {data.my_coverage.missing_top.map((item) => (
                  <span key={item.skill} className="text-xs bg-red-50 text-danger px-2 py-0.5 rounded">{item.skill}</span>
                ))}
              </div>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}

function StatCard({ label, value, color }: { label: string; value: number; color: 'brand' | 'success' | 'warning' }) {
  const colors = {
    brand: 'text-brand-600 bg-brand-50',
    success: 'text-success bg-green-50',
    warning: 'text-warning bg-amber-50',
  };

  return (
    <Card className="text-center">
      <div className={`text-2xl font-bold tabular-nums ${colors[color].split(' ')[0]}`}>
        {value.toLocaleString()}
      </div>
      <div className="text-xs text-text-muted mt-1">{label}</div>
    </Card>
  );
}
