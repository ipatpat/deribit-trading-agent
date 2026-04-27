import type { ReactNode } from 'react';
import Sidebar from './Sidebar';
import Topbar from './Topbar';

interface LayoutProps {
  children: ReactNode;
}

function Layout({ children }: LayoutProps) {
  return (
    <div className="min-h-screen bg-cream">
      <Topbar />
      <Sidebar />

      <main className="pl-sidebar pt-topbar">
        <div className="max-w-content mx-auto p-8">
          {children}
        </div>
      </main>
    </div>
  );
}

export default Layout;
