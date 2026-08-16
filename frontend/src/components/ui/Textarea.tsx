import { type TextareaHTMLAttributes } from 'react';

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  error?: string;
}

export function Textarea({ label, error, className = '', ...props }: TextareaProps) {
  return (
    <div className="flex flex-col gap-1">
      {label && (
        <label className="text-sm font-medium text-text-secondary">{label}</label>
      )}
      <textarea
        className={`
          px-3 py-2 text-sm rounded-md border resize-y min-h-[80px]
          bg-surface-0 text-text-primary placeholder:text-text-muted
          transition-colors duration-150
          focus:outline-none focus:ring-2 focus:ring-brand-300 focus:border-brand-400
          ${error ? 'border-danger' : 'border-border-light'}
          ${className}
        `}
        {...props}
      />
      {error && <span className="text-xs text-danger">{error}</span>}
    </div>
  );
}
