import { type ReactNode } from 'react';

interface CardProps {
  children: ReactNode;
  className?: string;
  hover?: boolean;
  padding?: 'none' | 'sm' | 'md' | 'lg';
}

const paddingStyles = {
  none: '',
  sm: 'p-3',
  md: 'p-5',
  lg: 'p-6',
};

export function Card({ children, className = '', hover = false, padding = 'md' }: CardProps) {
  return (
    <div
      className={`
        bg-surface-0 border border-border-light rounded-lg
        ${hover ? 'hover:shadow-card-hover transition-shadow duration-200' : 'shadow-card'}
        ${paddingStyles[padding]}
        ${className}
      `}
    >
      {children}
    </div>
  );
}
