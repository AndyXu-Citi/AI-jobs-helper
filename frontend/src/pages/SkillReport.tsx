import { useEffect, useMemo, useState } from 'react';
import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import { reportApi, type RawReportData } from '../api';
import { Card, SkillBar, EmptyState, Spinner } from '../components/ui';
import { useJobStore, useTabStore } from '../stores';

export function SkillReportPage() {
  const [data, setData] = useState<RawReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const { setFilter, setSkills } = useJobStore();
  const { setActiveTab } = useTabStore();

  useEffect(() => {
    async function load() {
      try {
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

  const handleSkillClick = (skill: string) => {
    setSkills([skill]);
    setActiveTab('jobs');
  };

  const handleCityClick = (city: string) => {
    setFilter('city', city);
    setActiveTab('jobs');
  };

  const handleSalaryClick = (band: string) => {
    const range = bandToSalaryRange(band);
    if (range) setFilter('salaryRange', range);
    setActiveTab('jobs');
  };

  const treemapOption = useMemo<EChartsOption>(
    () => (data ? buildTreemapOption(data.skills.map((s) => ({ name: s.name, count: s.count }))) : {}),
    [data]
  );

  const onTreemapClick = (params: any) => {
    if (params?.name && !params.name.includes('其他')) handleSkillClick(params.name);
  };

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

      {/* Main: Treemap + Side Stats */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card padding="md" className="lg:col-span-2 h-[600px] flex flex-col">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-base font-semibold text-text-primary">技能需求分布</h2>
            <span className="text-xs text-text-muted">点击板块跳转岗位库</span>
          </div>
          <div className="flex-1 min-h-0 overflow-visible">
            <ReactECharts
              option={treemapOption}
              style={{ height: '100%', width: '100%' }}
              onEvents={{ click: onTreemapClick }}
            />
          </div>
        </Card>

        <div className="space-y-4">
          <Card padding="lg" className="h-[250px] flex flex-col">
            <h3 className="text-sm font-semibold text-text-primary mb-3">城市分布</h3>
            <div className="overflow-y-auto flex-1 space-y-0.5">
              {data.cities.slice(0, 10).map((c) => (
                <SkillBar
                  key={c.name}
                  skill={c.name}
                  count={c.count}
                  total={data.total_jobs}
                  maxCount={data.cities[0]?.count}
                  onClick={() => handleCityClick(c.name)}
                />
              ))}
            </div>
          </Card>

          <Card padding="lg" className="flex flex-col">
            <h3 className="text-sm font-semibold text-text-primary mb-3">薪资范围</h3>
            <div className="space-y-0.5">
              {data.salary_bands
                .filter((r) => r.count > 0)
                .map((r) => (
                  <SkillBar
                    key={r.name}
                    skill={r.name}
                    count={r.count}
                    total={data.total_jobs}
                    maxCount={Math.max(...data.salary_bands.map((x) => x.count))}
                    onClick={() => handleSalaryClick(r.name)}
                  />
                ))}
            </div>
          </Card>
        </div>
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
                  <button
                    key={item.skill}
                    onClick={() => handleSkillClick(item.skill)}
                    className="text-xs bg-green-50 text-success px-2 py-0.5 rounded hover:bg-green-100 transition-colors"
                  >
                    {item.skill}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <div className="text-xs text-warning font-medium mb-1.5">学习中 ({data.my_coverage.learning.length})</div>
              <div className="flex flex-wrap gap-1">
                {data.my_coverage.learning.map((item) => (
                  <button
                    key={item.skill}
                    onClick={() => handleSkillClick(item.skill)}
                    className="text-xs bg-amber-50 text-warning px-2 py-0.5 rounded hover:bg-amber-100 transition-colors"
                  >
                    {item.skill}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <div className="text-xs text-danger font-medium mb-1.5">待补齐 ({data.my_coverage.missing_top.length})</div>
              <div className="flex flex-wrap gap-1">
                {data.my_coverage.missing_top.map((item) => (
                  <button
                    key={item.skill}
                    onClick={() => handleSkillClick(item.skill)}
                    className="text-xs bg-red-50 text-danger px-2 py-0.5 rounded hover:bg-red-100 transition-colors"
                  >
                    {item.skill}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}

/** Treemap 板块图：按技能出现次数自动排成大小不一的方块，出现越多板块越大，可点击跳转 */
function buildTreemapOption(skills: { name: string; count: number }[]): EChartsOption {
  const TOP_N = 40;
  const sorted = [...skills].sort((a, b) => b.count - a.count);
  const main = sorted.slice(0, TOP_N);
  const rest = sorted.slice(TOP_N);
  const treemapData = main.map((s) => ({ name: s.name, value: s.count }));
  if (rest.length > 0) {
    treemapData.push({
      name: `其他 (${rest.length})`,
      value: rest.reduce((a, s) => a + s.count, 0),
    });
  }
  return {
    tooltip: {
      trigger: 'item',
      formatter: (params: any) => `${params.name}<br/>出现 ${params.value} 次`,
    },
    series: [
      {
        type: 'treemap',
        data: treemapData,
        sort: 'desc',
        left: '2%',
        top: '2%',
        right: '2%',
        bottom: '2%',
        width: '96%',
        height: '96%',
        roam: false,
        nodeClick: false,
        breadcrumb: { show: false },
        label: {
          show: true,
          formatter: '{b}\n{c} 次',
          fontSize: 10,
          color: '#fff',
          overflow: 'break',
          lineHeight: 13,
          padding: [2, 2],
        },
        upperLabel: { show: false },
        itemStyle: {
          borderColor: '#fff',
          borderWidth: 1,
          gapWidth: 1,
        },
        colorSaturation: [0.35, 0.65],
        levels: [
          {
            itemStyle: {
              borderWidth: 0,
              gapWidth: 2,
              borderColorSaturation: 0.6,
            },
            label: {
              formatter: '{b}\n{c} 次',
              fontSize: 10,
              overflow: 'break',
              lineHeight: 13,
              padding: [2, 2],
            },
          },
        ],
      },
    ],
  };
}

function bandToSalaryRange(band: string): string {
  const map: Record<string, string> = {
    '<10K': '0-10',
    '10-15K': '10-20',
    '15-20K': '10-20',
    '20-30K': '20-30',
    '30K+': '30-50',
  };
  return map[band] || '';
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
