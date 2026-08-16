# AI 求职 Agent · UI 设计系统 (Design System)

> 版本 v1.0 · 设计: UI Designer · 适用: 本项目全部前端界面

## 一、设计原则

1. **单一真源 (Single Source of Truth)** — 所有颜色 / 间距 / 圆角收敛为 CSS 变量, 禁止在组件里再写硬编码色值。
2. **一致性 (Consistency)** — 同一交互 (按钮 / 标签 / 卡片) 全局只有一套样式, 杜绝"两个面试面板各写一份"的漂移。
3. **可访问性 (Accessibility, WCAG AA 底线)** — 正文对比度 ≥ 4.5:1, 交互元素可键盘操作, 尊重 `prefers-reduced-motion`。
4. **可演进 (Evolvable)** — 通过 `[data-theme]` 支持暗 / 亮双主题, 组件类与业务解耦。

## 二、交付物

| 文件 | 作用 |
|---|---|
| `src/web/static/design-system.css` | Token + 组件样式 (唯一依赖, 直接 `<link>` 引入) |
| `src/web/static/design-system.html` | 组件库实时预览页 (浏览器打开即可看全部组件 + 主题切换) |
| `docs/UI设计系统.md` | 本文档 (规范 / 迁移映射) |

## 三、设计 Token

### 3.1 颜色
- **主色**: `--accent-300: #4fc3f7` (提取自现有界面) · hover `--accent-400: #29b6f6`
- **表面**: `--bg-base:#0f0f0f` · `--surface-1:#1a1a1a` (卡片/输入) · `--surface-2:#222` (内层)
- **边框**: `--border-1:#333` · `--border-2:#222`
- **文本**: `--text-primary:#e0e0e0` · `--text-secondary:#b3b3b3` (旧 #aaa 已提亮达标) · `--text-muted:#8c8c8c`
- **语义**: `--success:#66bb6a` · `--warning:#ffb74d` · `--error:#ff6b6b` · `--info:#4fc3f7` (各含 `-bg`/`-border` 三态底色)
- **亮色主题**: `[data-theme="light"]` 覆盖以上变量, 无需改组件类

### 3.2 字体 / 字号
- `--font-sans`: 系统字体栈 (含 PingFang SC / 微软雅黑) · `--font-mono`: SF Mono / Fira Code
- 字号梯度: `xs12 / sm13 / base14 / md15 / lg16 / xl18 / 2xl20 / 3xl24 / 4xl28`

### 3.3 间距 / 圆角 / 阴影 / 动效
- 间距: 4px 基础栅格 → `--space-1..16` (4/8/12/16/20/24/32/40/48/64)
- 圆角: `--radius-sm4 / md8 / lg12 / xl16 / pill999`
- 阴影: `--shadow-sm/md/lg` + `--shadow-accent` (聚焦环)
- 动效: `--transition-fast120 / base200 / slow300`

## 四、组件清单

| 组件 | 类 | 关键状态 |
|---|---|---|
| 按钮 | `.btn` + `.btn--primary/secondary/ghost/success/warning/danger` + `.btn--sm/lg` | `:disabled` · `.is-loading` |
| 表单 | `.input` `.textarea` `.select` `.file-drop` `.switch` | `:focus` 聚焦环 · `.is-invalid` |
| 标签 | `.tag` + `--accent/success/warning/error` · 技能三态 `--have/learning/missing` | — |
| 徽章 | `.badge` `.badge--accent` | 计数场景 |
| 卡片 | `.card` `.card--hover` · `.job-card` · `.stat-card` | hover 抬升 |
| 标签页 | `.tabs` `.tab[aria-selected]` | 语义 `<button>`, 键盘可达 |
| 告警 | `.alert` + `--info/success/warning/error` | — |
| 表格 | `.table` | hover 行高亮 |
| 进度条 | `.progress` `.progress__fill` · `.skill-bar` | 宽度过渡 |
| 聊天气泡 | `.bubble--ai/user` · `.bubble__tag` | — |
| 加载 | `.spinner` · `.skeleton` (`--line/--title/--block`) | shimmer 动画 |
| 模态框 | `.modal-overlay` `.modal` (`__header/__body/__footer/__close`) | 点击遮罩关闭 |
| 空状态 | `.empty` (`__icon/__title/__hint`) | — |

## 五、无障碍 (A11y) 规范

- **对比度**: 正文文本 ≥ 4.5:1; 上一轮评审指出的 `.skill-filter .count(#666)` / `.detail-empty(#555)` 已替换为 `--text-muted/#8c8c8c` 提亮。
- **键盘**: Tab / 筛选 / 模式标签统一用 `<button>` 或带 `role="tab"` + `aria-selected`, 支持方向键 (见展示页 Tabs 演示)。
- **焦点**: 全局 `:focus-visible` 提供 2px 主色描边, 满足 WCAG 2.4.7。
- **动效**: 所有动画包在 `@media (prefers-reduced-motion: reduce)` 内自动降级。
- **播报**: 加载 / 报错等关键状态建议加 `aria-live="polite"` (实现时在调用处补充)。

## 六、与现有 index.html 的迁移映射

> 目标: 不动业务逻辑, 只替换样式来源, 顺手修掉 P0/P1 问题。

| 现有写法 (index.html) | 改用 | 收益 |
|---|---|---|
| `#4fc3f7` (≈30 处) | `var(--accent-300)` | 集中管控, 换肤一行生效 |
| `#1a1a1a` / `#333` / `#222` | `var(--surface-1/--border-1/--border-2)` | 暗亮主题统一 |
| 行内 `style="...padding:16px"` | `.card` / `.field` 等组件类 | 去重, 易维护 |
| `<span class="tab" onclick>` | `<button class="tab" role="tab">` | 键盘可达 (P1) |
| 面试双控件 mini 行 + mode-tags | 唯一真源 `MODE_LABELS` + 组件类 | 修 P0 双控件 bug |
| `.skill-filter .count`(#666) | `var(--text-muted)` | 对比度达标 (P2) |

**迁移步骤建议**
1. 在 `index.html` `<head>` 引入 `<link rel="stylesheet" href="design-system.css">`
2. 把硬编码色值批量替换为 Token (可正则 `\#4fc3f7` → `var(--accent-300)` 等)
3. 先收敛 P0: 删除面试设置区冗余的 mini 模式控件, 以 `mode-tags` 为唯一真源
4. 将 Tab / 筛选 / 模式标签改为 `<button>`, 补 `aria-selected` / `tabindex`
5. 两份重复的面试面板模板 (静态 + `newInterviewChat` 重建) 收敛为单函数 `renderSetupCard()`

## 七、使用方式

```bash
# 1. 引入样式 (index.html <head>)
<link rel="stylesheet" href="design-system.css">

# 2. 预览组件库
# 直接用浏览器打开:
#   src/web/static/design-system.html
# 或在 web 服务下访问 (FastAPI 已托管 static 目录):
#   http://localhost:8000/design-system.html
```

## 八、后续演进路线

- **阶段一 (规范落地)**: 完成第六节迁移映射, 修 P0/P1, 全站对比度达标。
- **阶段二 (体验增强)**: 引入设计走查 (Figma 或截图比对) + 组件单元快照测试。
- **阶段三 (工程化)**: 若未来引入构建工具 (Vite), 可将 CSS 拆分为 `tokens.css` / `components/*.css` 按需打包。
