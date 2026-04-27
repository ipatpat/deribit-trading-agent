import type { ReactNode } from 'react';

interface PanelProps {
  children: ReactNode;
  className?: string;
  header?: ReactNode;
  headerClassName?: string;
  contentClassName?: string;
}

function Panel({
  children,
  className = '',
  header,
  headerClassName = '',
  contentClassName = '',
}: PanelProps) {
  return (
    <div className={`bg-white border border-divider rounded-card shadow-sm overflow-hidden flex flex-col ${className}`}>
      {header && (
        <div className={`px-3 py-2 border-b border-divider bg-white font-semibold text-primary ${headerClassName}`}>
          {header}
        </div>
      )}
      <div className={`flex-1 p-3 ${contentClassName}`}>
        {children}
      </div>
    </div>
  );
}

export default Panel;
