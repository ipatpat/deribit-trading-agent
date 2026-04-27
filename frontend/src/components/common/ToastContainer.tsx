import { X } from 'lucide-react';
import { useToastStore } from '../../stores/toast';

const typeStyles = {
  success: 'bg-profit/10 text-profit border-profit/20',
  error: 'bg-loss/10 text-loss border-loss/20',
  info: 'bg-primary/10 text-primary border-primary/20',
};

function ToastContainer() {
  const toasts = useToastStore((s) => s.toasts);
  const dismiss = useToastStore((s) => s.dismiss);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed top-16 right-4 z-[100] flex flex-col gap-2 pointer-events-none">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`px-4 py-3 rounded-lg text-sm font-medium border shadow-card pointer-events-auto flex items-center gap-3 animate-in ${typeStyles[t.type]}`}
        >
          <span className="flex-1">{t.message}</span>
          <button
            onClick={() => dismiss(t.id)}
            className="opacity-60 hover:opacity-100 transition-opacity shrink-0"
            aria-label="Close notification"
          >
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}

export default ToastContainer;
