import type { ReactNode } from 'react';

interface CardProps {
  children: ReactNode;
  className?: string;
}

function Card({ children, className = '' }: CardProps) {
  return (
    <div className={`bg-white shadow-card rounded-card p-4 ${className}`}>
      {children}
    </div>
  );
}

export default Card;
