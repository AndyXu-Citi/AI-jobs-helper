import { useConversationStore, useChatStore } from '../stores';
import type { ChatMode, InterviewSubMode } from '../types';

const S = (p: { size?: number; className?: string }) => ({
  width: p.size ?? 16, height: p.size ?? 16, className: p.className, viewBox: '0 0 24 24',
  fill: 'none', stroke: 'currentColor', strokeWidth: 1.6, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const,
});
const IconPlus = (p: { size?: number; className?: string }) => (<svg {...S(p)}><path d="M12 5v14M5 12h14" /></svg>);
const IconClose = (p: { size?: number; className?: string }) => (<svg {...S(p)}><path d="M6 6l12 12M18 6 6 18" /></svg>);
const IconChat = (p: { size?: number; className?: string }) => (<svg {...S(p)}><path d="M21 12a8 8 0 0 1-11.5 7.2L4 20l1-4.5A8 8 0 1 1 21 12Z" /></svg>);
const IconAssistant = (p: { size?: number; className?: string }) => (<svg {...S(p)}><path d="M12 3a6 6 0 0 1 4.5 10v3.5a1.5 1.5 0 0 1-1.5 1.5h-6A1.5 1.5 0 0 1 7.5 16.5V13A6 6 0 0 1 12 3Z" /><circle cx="9.5" cy="11" r="1" /><circle cx="14.5" cy="11" r="1" /></svg>);
const IconInterviewer = (p: { size?: number; className?: string }) => (<svg {...S(p)}><circle cx="12" cy="8" r="3.4" /><path d="M5.5 20a6.5 6.5 0 0 1 13 0" /></svg>);

interface SidebarProps {
  onNewChat: () => void;
}

export function Sidebar({ onNewChat }: SidebarProps) {
  const { conversations, activeConversationId, setActiveConversation, deleteConversation } = useConversationStore();
  const { mode: currentMode } = useChatStore();

  // 按日期分组
  const grouped = groupByDate(conversations);

  return (
    <aside className="w-[260px] flex-shrink-0 flex flex-col h-full bg-surface-0 border-r border-border-light">
      {/* Header */}
      <div className="p-3 border-b border-border-light">
        <button
          onClick={onNewChat}
          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg border border-dashed border-indigo-300 text-sm font-medium text-indigo-600 hover:bg-indigo-50 transition-colors"
        >
          <IconPlus size={16} />
          开启新对话
        </button>
      </div>

      {/* Conversation List */}
      <div className="flex-1 overflow-y-auto p-2 space-y-4">
        {Object.entries(grouped).map(([label, items]) => (
          <div key={label}>
            <div className="px-2 py-1 text-xs font-medium text-text-muted">{label}</div>
            {items.map((conv) => (
              <ConversationItem
                key={conv.id}
                conv={conv}
                active={conv.id === activeConversationId}
                currentMode={currentMode}
                onClick={() => setActiveConversation(conv.id)}
                onDelete={(e) => { e.stopPropagation(); deleteConversation(conv.id); }}
              />
            ))}
            {items.length === 0 && (
              <div className="px-2 py-3 text-xs text-text-muted text-center">暂无对话</div>
            )}
          </div>
        ))}
        {conversations.length === 0 && (
          <div className="flex flex-col items-center justify-center py-12 text-text-muted">
            <div className="mb-2 text-stone-300"><IconChat size={30} /></div>
            <div className="text-xs">还没有对话记录</div>
            <div className="text-xs mt-1">点击上方开始新对话</div>
          </div>
        )}
      </div>

      {/* Footer - 预留记忆模块入口 */}
      <div className="p-3 border-t border-border-light">
        <div className="text-xs text-text-muted text-center">
          对话记录本地存储 · 后续支持云端同步
        </div>
      </div>
    </aside>
  );
}

// ===== 单条对话 =====
function ConversationItem({
  conv,
  active,
  currentMode,
  onClick,
  onDelete,
}: {
  conv: { id: string; title: string; mode: ChatMode; interviewSubMode?: InterviewSubMode; messageCount: number; updatedAt: number };
  active: boolean;
  currentMode: ChatMode;
  onClick: () => void;
  onDelete: (e: React.MouseEvent) => void;
}) {
  const modeIcon = conv.mode === 'assistant' ? <IconAssistant size={15} /> : <IconInterviewer size={15} />;
  const timeLabel = formatTime(conv.updatedAt);

  return (
    <div
      onClick={onClick}
      className={`group relative flex items-start gap-2 px-3 py-2.5 rounded-lg cursor-pointer transition-colors ${
        active
          ? 'bg-indigo-50 text-indigo-800'
          : 'hover:bg-surface-1 text-text-primary'
      }`}
    >
      <span className="mt-0.5 flex-shrink-0 text-stone-400">{modeIcon}</span>
      <div className="flex-1 min-w-0">
        <div className={`text-sm truncate ${active ? 'font-medium' : ''}`}>{conv.title}</div>
        <div className="flex items-center gap-2 mt-0.5">
          <span className="text-[11px] text-text-muted">{timeLabel}</span>
          {conv.messageCount > 0 && (
            <span className="text-[11px] text-text-muted">{conv.messageCount} 条消息</span>
          )}
        </div>
      </div>
      {/* 删除按钮（hover 显示） */}
      <button
        onClick={onDelete}
        className="opacity-0 group-hover:opacity-100 absolute right-1.5 top-1.5 w-6 h-6 rounded flex items-center justify-center text-text-muted hover:text-red-500 hover:bg-red-50 transition-all text-xs"
        title="删除对话"
      >
        <IconClose size={13} />
      </button>
    </div>
  );
}

// ===== 按日期分组 =====
function groupByDate(convs: { updatedAt: number }[]) {
  const now = Date.now();
  const groups: Record<string, typeof convs> = {};

  for (const c of convs) {
    const diff = now - c.updatedAt;
    let label: string;
    if (diff < 86400000) label = '今天';
    else if (diff < 86400000 * 2) label = '昨天';
    else if (diff < 86400000 * 7) label = '7天内';
    else label = '更早';

    if (!groups[label]) groups[label] = [];
    groups[label].push(c);
  }

  return groups;
}

function formatTime(ts: number): string {
  const d = new Date(ts);
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${hh}:${mm}`;
}
