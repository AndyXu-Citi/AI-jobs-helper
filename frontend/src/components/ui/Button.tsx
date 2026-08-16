import { type ReactNode, type ButtonHTMLAttributes } from 'react';

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
type ButtonSize = 'sm' | 'md' | 'lg';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  children: ReactNode;
}

const variantStyles: Record<ButtonVariant, string> = {
  primary:
    'bg-brand-500 text-white hover:bg-brand-600 active:bg-brand-700 shadow-sm',
  secondary:
    'bg-surface-2 text-text-primary border border-border-light hover:bg-surface-3',
  ghost:
    'text-text-secondary hover:text-text-primary hover:bg-surface-2',
  danger:
    'bg-danger text-white hover:bg-red-700',
};

const sizeStyles: Record<ButtonSize, string> = {
  sm: 'px-2.5 py-1 text-xs rounded-sm',
  md: 'px-4 py-2 text-sm rounded-md',
  lg: 'px-6 py-2.5 text-base rounded-lg',
};

export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  disabled,
  children,
  className = '',
  ...props
}: ButtonProps) {
  return (
    <button
      className={`
        inline-flex items-center justify-center gap-1.5 font-medium
        transition-colors duration-150 cursor-pointer
        disabled:opacity-50 disabled:pointer-events-none
        ${variantStyles[variant]}
        ${sizeStyles[size]}
        ${className}
      `}
      disabled={disabled || loading}
      {...props}
    >
      {loading && (
        <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      )}
      {children}
    </button>
  );
}
