import { Sparkles } from 'lucide-react';
import { useChatStore } from '../../stores/chat';

function ChatFab() {
  const open = useChatStore((s) => s.open);
  const toggle = useChatStore((s) => s.toggle);

  if (open) return null;

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label="Open AI assistant"
      className="fixed bottom-fab-bottom right-fab-right z-30 w-chat-fab h-chat-fab rounded-full bg-primary text-white shadow-popup flex items-center justify-center transition-transform hover:shadow-card active:scale-95"
    >
      <Sparkles size={20} strokeWidth={2.25} />
    </button>
  );
}

export default ChatFab;
