interface SkillBarProps {
  skill: string;
  count: number;
  total: number;
  maxCount?: number;
  onClick?: () => void;
}

export function SkillBar({ skill, count, total, maxCount, onClick }: SkillBarProps) {
  const max = maxCount || Math.max(count, 1);
  const pct = Math.round((count / max) * 100);

  return (
    <div
      onClick={onClick}
      className={`flex items-center gap-3 py-1.5 rounded ${
        onClick ? 'cursor-pointer hover:bg-surface-1 transition-colors' : ''
      }`}
    >
      <span className={`text-sm w-28 shrink-0 truncate ${onClick ? 'text-brand-600 hover:underline' : 'text-text-primary'}`} title={skill}>
        {skill}
      </span>
      <div className="flex-1 h-5 bg-surface-2 rounded-sm overflow-hidden">
        <div
          className="h-full bg-brand-500 rounded-sm transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-text-muted w-10 text-right tabular-nums">
        {count} ({total > 0 ? Math.round((count / total) * 100) : 0}%)
      </span>
    </div>
  );
}
