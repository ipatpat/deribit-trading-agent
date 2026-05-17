import { useLocation, Link } from 'react-router-dom';
import {
  LayoutDashboard,
  LineChart,
  TrendingUp,
  Crosshair,
  Shield,
  Settings,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

interface NavItem {
  path: string;
  icon: LucideIcon;
  label: string;
}

const NAV_ITEMS: NavItem[] = [
  { path: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { path: '/options', icon: LineChart, label: 'Options' },
  { path: '/futures', icon: TrendingUp, label: 'Futures' },
  { path: '/smart-orders', icon: Crosshair, label: 'Smart Orders' },
  { path: '/risk', icon: Shield, label: 'Risk' },
  { path: '/settings', icon: Settings, label: 'Settings' },
];

function Sidebar() {
  const { pathname } = useLocation();

  return (
    <aside className="fixed left-0 top-0 bottom-0 w-sidebar bg-white border-r border-divider flex flex-col items-center pt-topbar z-10">
      {NAV_ITEMS.map(({ path, icon: Icon, label }, idx) => {
        const active = path === '/' ? pathname === '/' : pathname.startsWith(path);
        const isLast = idx === NAV_ITEMS.length - 1;
        return (
          <div key={path} className={`w-full ${isLast ? 'mt-auto' : ''}`}>
            {isLast && (
              <div className="border-t border-divider mx-3 mb-1" />
            )}
            <Link
              to={path}
              title={label}
              aria-current={active ? 'page' : undefined}
              className={`group relative flex items-center justify-center w-full h-12 transition-colors ${
                active
                  ? 'text-accent border-l-2 border-accent bg-cream'
                  : 'text-secondary hover:text-primary hover:bg-cream/50'
              }`}
            >
              <Icon size={20} />
              {/* Tooltip */}
              <span className="absolute left-full ml-2 px-2 py-1 rounded bg-primary text-white text-xs whitespace-nowrap opacity-0 pointer-events-none group-hover:opacity-100 transition-opacity">
                {label}
              </span>
            </Link>
          </div>
        );
      })}
    </aside>
  );
}

export default Sidebar;
