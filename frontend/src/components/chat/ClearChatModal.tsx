import { Trash2 } from 'lucide-react';

interface ClearChatModalProps {
  count: number;
  onConfirm: () => void;
  onCancel: () => void;
}

function ClearChatModal({ count, onConfirm, onCancel }: ClearChatModalProps) {
  return (
    <div
      className="absolute inset-0 z-50 flex items-center justify-center bg-black/30"
      onClick={onCancel}
      role="dialog"
      aria-modal="true"
      aria-label="Confirm clear chat"
    >
      <div
        className="bg-white rounded-lg shadow-popup p-5 max-w-[280px] mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 mb-3">
          <div className="w-8 h-8 rounded-full bg-loss-bg flex items-center justify-center">
            <Trash2 size={16} className="text-loss" />
          </div>
          <div className="text-sm font-semibold text-primary">Clear chat?</div>
        </div>
        <p className="text-xs text-secondary mb-5 leading-relaxed">
          Delete {count} message{count === 1 ? '' : 's'}? This cannot be undone.
        </p>
        <div className="flex gap-2 justify-end">
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-1.5 rounded-lg text-xs font-semibold text-secondary hover:text-primary hover:bg-cream transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="px-4 py-1.5 rounded-lg bg-loss text-white text-xs font-semibold hover:bg-loss/90 transition-colors"
          >
            Clear
          </button>
        </div>
      </div>
    </div>
  );
}

export default ClearChatModal;
