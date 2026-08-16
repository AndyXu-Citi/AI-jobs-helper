import { type InputHTMLAttributes } from 'react';

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  hint?: string;
}

export function Input({ label, error, hint, className = '', ...props }: InputProps) {
  return (
    <div className="flex flex-col gap-1">
      {label && (
        <label className="text-sm font-medium text-text-secondary">{label}</label>
      )}
      <input
        className={`
          px-3 py-2 text-sm rounded-md border
          bg-surface-0 text-text-primary placeholder:text-text-muted
          transition-colors duration-150
          focus:outline-none focus:ring-2 focus:ring-brand-300 focus:border-brand-400
          ${error ? 'border-danger' : 'border-border-light'}
          ${className}
        `}
        {...props}
      />
      {hint && !error && <span className="text-xs text-text-muted">{hint}</span>}
      {error && <span className="text-xs text-danger">{error}</span>}
    </div>
  );
}
