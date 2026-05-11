import type { ReactNode } from 'react';
import Sidebar from './Sidebar';
import Topbar from './Topbar';
import ChatFab from '../chat/ChatFab';
import ChatSidebar from '../chat/ChatSidebar';
import { useChatStore } from '../../stores/chat';

interface LayoutProps {
  children: ReactNode;
}

function Layout({ children }: LayoutProps) {
  const chatOpen = useChatStore((s) => s.open);

  return (
    <div className="min-h-screen bg-cream">
      <Topbar />
      <Sidebar />

      <main
        className={`pl-sidebar pt-topbar transition-[padding] duration-200 ${
          chatOpen ? 'pr-chat-sidebar' : ''
        }`}
      >
        <div className="max-w-content mx-auto p-8 min-w-0">{children}</div>
      </main>

      {chatOpen && <ChatSidebar />}
      <ChatFab />
    </div>
  );
}

export default Layout;
