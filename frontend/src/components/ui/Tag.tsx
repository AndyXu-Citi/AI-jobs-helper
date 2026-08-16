import { type ReactNode } from 'react';

type TagVariant = 'default' | 'success' | 'warning' | 'danger' | 'info';
type TagSize = 'sm' | 'md';

interface TagProps {
  children: ReactNode;
  variant?: TagVariant;
  size?: TagSize;
  removable?: boolean;
  onRemove?: () => void;
}

const variantStyles: Record<TagVariant, string> = {
  default: 'bg-surface-2 text-text-secondary border-border-light',
  success: 'bg-green-50 text-success border-green-200',
  warning: 'bg-amber-50 text-warning border-amber-200',
  danger: 'bg-red-50 text-danger border-red-200',
  info: 'bg-brand-50 text-brand-600 border-brand-200',
};

const sizeStyles: Record<TagSize, string> = {
  sm: 'text-xs px-1.5 py-0.5',
  md: 'text-sm px-2.5 py-0.5',
};

export function Tag({ children, variant = 'default', size = 'sm', removable, onRemove }: TagProps) {
  return (
    <span
      className={`
        inline-flex items-center gap-1 rounded-full border font-medium
        ${variantStyles[variant]}
        ${sizeStyles[size]}
      `}
    >
      {children}
      {removable && (
        <button
          onClick={onRemove}
          className="ml-0.5 hover:text-danger transition-colors cursor-pointer"
        >
          ×
        </button>
      )}
    </span>
  );
}
