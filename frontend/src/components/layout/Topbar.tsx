import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getSettingsStatus } from '../../api/client';

function Topbar() {
  const [env, setEnv] = useState('');

  useEffect(() => {
    getSettingsStatus()
      .then((s) => setEnv(s.env))
      .catch(() => setEnv(''));

    // Poll every 5s to catch env switches
    const interval = setInterval(() => {
      getSettingsStatus()
        .then((s) => setEnv(s.env))
        .catch(() => {});
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  return (
    <header className="fixed top-0 left-0 right-0 h-topbar bg-white border-b border-divider flex items-center justify-between px-6 z-40">
      <span className="text-lg font-semibold text-primary tracking-tight">
        Deribit Trading
      </span>
      <div className="flex items-center gap-2">
        {env && (
          <Link
            to="/settings"
            className={`text-xs font-medium uppercase tracking-wider transition-colors hover:text-accent ${
              env === 'production' ? 'text-loss' : 'text-secondary'
            }`}
          >
            {env}
          </Link>
        )}
      </div>
    </header>
  );
}

export default Topbar;
