import { useEffect, useState } from 'react';
import { Routes, Route, useLocation, useNavigate } from 'react-router-dom';
import Layout from './components/layout/Layout';
import ToastContainer from './components/common/ToastContainer';
import Dashboard from './pages/Dashboard';
import Options from './pages/Options';
import Futures from './pages/Futures';
import SmartOrders from './pages/SmartOrders';
import Risk from './pages/Risk';
import Settings from './pages/Settings';
import { useAccountsStore } from './stores/accounts';
import { migrateLegacyChatStore, switchChatPersistKey } from './stores/chat';

function App() {
  const fetchAccounts = useAccountsStore((s) => s.fetchAccounts);
  const activeId = useAccountsStore((s) => s.activeId);
  const [bootChecked, setBootChecked] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  // One-shot boot: pull accounts → migrate legacy chat store → set chat key →
  // route to /settings if no active account.
  useEffect(() => {
    (async () => {
      await fetchAccounts();
      const id = useAccountsStore.getState().activeId;
      // Legacy v3 chat data lived under "chat-store"; one-shot rename to the
      // active account's bucket (or anonymous if none).
      migrateLegacyChatStore(id);
      await switchChatPersistKey(id);
      setBootChecked(true);
      if (!id && location.pathname !== '/settings') {
        navigate('/settings', { replace: true });
      }
    })();
    // Intentionally only run once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Layout>
      {bootChecked && !activeId && location.pathname === '/settings' && (
        <div className="mb-4 px-4 py-3 rounded-card border border-loss/30 bg-loss-bg text-loss text-sm">
          <div className="font-semibold mb-0.5">Add an account to get started</div>
          <div className="text-loss/80 text-xs">
            Configure at least one Deribit / Tibired account below. Trading,
            portfolio, and the AI agent are disabled until an account is
            active.
          </div>
        </div>
      )}
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/options" element={<Options />} />
        <Route path="/futures" element={<Futures />} />
        <Route path="/smart-orders" element={<SmartOrders />} />
        <Route path="/risk" element={<Risk />} />
        <Route path="/settings" element={<Settings />} />
      </Routes>
      <ToastContainer />
    </Layout>
  );
}

export default App;
