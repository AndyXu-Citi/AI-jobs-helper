import { type ReactNode } from 'react';

interface SpinnerProps {
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

const sizes = { sm: 'h-4 w-4', md: 'h-6 w-6', lg: 'h-10 w-10' };

export function Spinner({ size = 'md', className = '' }: SpinnerProps) {
  return (
    <svg
      className={`animate-spin text-brand-500 ${sizes[size]} ${className}`}
      viewBox="0 0 24 24"
      fill="none"
    >
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
      />
    </svg>
  );
}

// ===== 全屏加载遮罩 =====
interface LoadingOverlayProps {
  text?: string;
}

export function LoadingOverlay({ text = '加载中...' }: LoadingOverlayProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16">
      <Spinner size="lg" />
      <span className="text-sm text-text-muted">{text}</span>
    </div>
  );
}
