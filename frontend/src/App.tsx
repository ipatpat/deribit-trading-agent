import { useEffect, useRef, useState } from 'react';
import { Routes, Route, useLocation, useNavigate } from 'react-router-dom';
import Layout from './components/layout/Layout';
import ToastContainer from './components/common/ToastContainer';
import Dashboard from './pages/Dashboard';
import Options from './pages/Options';
import Futures from './pages/Futures';
import SmartOrders from './pages/SmartOrders';
import Risk from './pages/Risk';
import Settings from './pages/Settings';
import Welcome from './pages/Welcome';
import { useAccountsStore } from './stores/accounts';
import { migrateLegacyChatStore, switchChatPersistKey } from './stores/chat';

function App() {
  const fetchAccounts = useAccountsStore((s) => s.fetchAccounts);
  const activeId = useAccountsStore((s) => s.activeId);
  const navigate = useNavigate();
  const location = useLocation();
  const [bootChecked, setBootChecked] = useState(false);
  const prevActiveIdRef = useRef<string | null | undefined>(undefined);

  // One-shot boot: pull accounts → migrate legacy chat store → set chat key →
  // route to /welcome if no active account. Routes render only after this
  // resolves so Dashboard etc. don't mount-and-fail on a no-account state.
  useEffect(() => {
    (async () => {
      await fetchAccounts();
      const id = useAccountsStore.getState().activeId;
      migrateLegacyChatStore(id);
      await switchChatPersistKey(id);
      prevActiveIdRef.current = id;
      if (!id && location.pathname !== '/welcome') {
        navigate('/welcome', { replace: true });
      }
      setBootChecked(true);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Reactive guard: when activeId transitions from a real value to null
  // (user deleted their last account), send them back to onboarding.
  useEffect(() => {
    const prev = prevActiveIdRef.current;
    if (prev !== undefined && prev !== null && activeId === null) {
      if (location.pathname !== '/welcome') {
        navigate('/welcome', { replace: true });
      }
    }
    prevActiveIdRef.current = activeId;
  }, [activeId, navigate, location.pathname]);

  const isWelcome = location.pathname === '/welcome';

  // Block all route mounting until boot finishes — and, if onboarding is
  // needed, until the redirect to /welcome has actually taken effect.
  // Without this, Dashboard would mount on `/` during the same render that
  // navigate() is queued, fire portfolio fetches, and toast a 500.
  const needsRedirect = !activeId && !isWelcome;
  if (!bootChecked || needsRedirect) {
    return <div className="min-h-screen w-full bg-bg" />;
  }

  return (
    <>
      {isWelcome ? (
        <Routes>
          <Route path="/welcome" element={<Welcome />} />
        </Routes>
      ) : (
        <Layout>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/options" element={<Options />} />
            <Route path="/futures" element={<Futures />} />
            <Route path="/smart-orders" element={<SmartOrders />} />
            <Route path="/risk" element={<Risk />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </Layout>
      )}
      <ToastContainer />
    </>
  );
}

export default App;
