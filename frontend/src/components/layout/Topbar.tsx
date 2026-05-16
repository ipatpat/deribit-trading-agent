import { Link } from 'react-router-dom';
import { Settings as SettingsIcon } from 'lucide-react';
import AccountChip from '../topbar/AccountChip';

function Topbar() {
  return (
    <header className="fixed top-0 left-0 right-0 h-topbar bg-white border-b border-divider flex items-center justify-between px-6 z-40">
      <span className="text-lg font-semibold text-primary tracking-tight">
        Deribit Trading
      </span>
      <div className="flex items-center gap-2">
        <AccountChip />
        <Link
          to="/settings"
          className="p-2 rounded text-secondary hover:text-primary hover:bg-cream transition-colors"
          title="Settings"
        >
          <SettingsIcon size={16} />
        </Link>
      </div>
    </header>
  );
}

export default Topbar;
