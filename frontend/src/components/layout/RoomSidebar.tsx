import React, { useState } from 'react';
import {
  LayoutGrid,
  History,
  GitBranch,
  RotateCcw,
  CheckCircle2,
  Users,
  Settings,
  Cpu,
  Layers,
  Sun,
  Moon,
  ChevronDown,
  Copy,
  Check,
  FileCheck,
} from 'lucide-react';
import { Room, Role } from '../../api/types';
import { applyTheme, getTheme, Theme } from '../../lib/theme';

export type ActiveView =
  | 'roadmap'
  | 'live'
  | 'setup'
  | 'board'
  | 'timeline'
  | 'decisions'
  | 'trace'
  | 'recovery'
  | 'verification'
  | 'members'
  | 'context'
  | 'models'
  | 'settings';

interface RoomSidebarProps {
  room: Room | null;
  activeView: ActiveView;
  onSelectView: (view: ActiveView) => void;
  currentUser: { display_name: string; id: string } | null;
  myRole: Role;
}

export const RoomSidebar: React.FC<RoomSidebarProps> = ({
  room,
  activeView,
  onSelectView,
  currentUser,
  myRole,
}) => {
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [copiedCode, setCopiedCode] = useState(false);
  const [theme, setThemeState] = useState<Theme>(getTheme());
  const toggleTheme = () => {
    const next: Theme = theme === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    setThemeState(next);
  };

  const copyInviteCode = () => {
    if (!room) return;
    navigator.clipboard.writeText(room.invite_code);
    setCopiedCode(true);
    setTimeout(() => setCopiedCode(false), 2000);
    setDropdownOpen(false);
  };

  const navItems: Array<{
    id: ActiveView;
    label: string;
    icon: React.ReactNode;
    badge?: number;
    badgeColor?: string;
  }> = [
    { id: 'roadmap', label: 'Roadmap', icon: <GitBranch className="w-4 h-4" /> },
    { id: 'live', label: 'Live', icon: <History className="w-4 h-4" /> },
    { id: 'setup', label: 'Setup', icon: <Cpu className="w-4 h-4" /> },
    { id: 'context', label: 'Demo', icon: <Layers className="w-4 h-4" /> },
  ];

  return (
    <aside className="w-[240px] bg-[#111217] border-r border-[#2A2D37] flex flex-col justify-between select-none flex-shrink-0 z-20">
      {/* Header with Room dropdown */}
      <div className="relative border-b border-[#2A2D37]">
        <button
          onClick={() => setDropdownOpen(!dropdownOpen)}
          className="w-full h-14 px-4 flex items-center justify-between text-left hover:bg-[#16171D] transition-colors"
        >
          <div className="truncate">
            <h2 className="font-semibold text-sm text-[#E6E7EB] truncate">
              {room?.name || 'Loading room...'}
            </h2>
            <p className="text-[11px] text-[#8B8FA3] capitalize font-mono">
              Role: <span className="text-[#6366F1]">{myRole}</span>
            </p>
          </div>
          <ChevronDown
            className={`w-4 h-4 text-[#8B8FA3] transition-transform duration-200 ${
              dropdownOpen ? 'rotate-180' : ''
            }`}
          />
        </button>

        {dropdownOpen && (
          <div className="absolute top-full left-2 right-2 mt-1 bg-[#1D1F27] border border-[#2A2D37] rounded-lg p-1.5 shadow-xl z-50 text-xs">
            <button
              onClick={copyInviteCode}
              className="w-full flex items-center justify-between px-2.5 py-2 rounded hover:bg-[#2A2D37] text-[#E6E7EB] transition-colors"
            >
              <span className="flex items-center gap-2">
                <Copy className="w-3.5 h-3.5 text-[#8B8FA3]" />
                Copy invite code
              </span>
              <span className="font-mono text-[11px] text-[#6366F1] font-semibold">
                {copiedCode ? <Check className="w-3.5 h-3.5 text-[#22C55E]" /> : room?.invite_code}
              </span>
            </button>
            <button
              onClick={() => {
                onSelectView('settings');
                setDropdownOpen(false);
              }}
              className="w-full flex items-center gap-2 px-2.5 py-2 rounded hover:bg-[#2A2D37] text-[#8B8FA3] hover:text-[#E6E7EB] transition-colors"
            >
              <Settings className="w-3.5 h-3.5" />
              Room settings
            </button>
          </div>
        )}
      </div>

      {/* Nav items */}
      <nav className="flex-1 py-3 px-2 space-y-0.5 overflow-y-auto">
        {navItems.map((item) => {
          const isActive = activeView === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onSelectView(item.id)}
              className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-xs font-medium transition-all ${
                isActive
                  ? 'bg-[#1D1F27] text-[#E6E7EB] shadow-sm border border-[#2A2D37]'
                  : 'text-[#8B8FA3] hover:text-[#E6E7EB] hover:bg-[#16171D]'
              }`}
            >
              <span className="flex items-center gap-2.5 truncate">
                <span className={isActive ? 'text-[#6366F1]' : 'text-[#8B8FA3]'}>
                  {item.icon}
                </span>
                <span className="truncate">{item.label}</span>
              </span>

              {item.badge !== undefined && item.badge > 0 && (
                <span
                  className={`text-[10px] px-1.5 py-0.2 rounded-full font-mono ${
                    item.badgeColor || 'bg-[#2A2D37] text-[#E6E7EB]'
                  }`}
                >
                  {item.badge}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      {/* Footer: User profile */}
      <div className="h-14 border-t border-[#2A2D37] px-3 flex items-center gap-2.5 bg-[#0E0F13]">
        <div className="w-8 h-8 rounded-full bg-[#6366F1]/20 border border-[#6366F1]/40 flex items-center justify-center font-bold text-xs text-[#6366F1]">
          {currentUser?.display_name ? currentUser.display_name[0].toUpperCase() : 'U'}
        </div>
        <div className="truncate flex-1">
          <div className="text-xs font-medium text-[#E6E7EB] truncate">
            {currentUser?.display_name || 'Anonymous'}
          </div>
          <div className="text-[11px] text-[#8B8FA3] capitalize">
            {myRole}
          </div>
        </div>
        <button
          onClick={toggleTheme}
          title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          className="w-8 h-8 rounded-lg border border-[#2A2D37] bg-[#16171D] text-[#8B8FA3] hover:text-[#E6E7EB] hover:border-[#6366F1] flex items-center justify-center transition-colors"
        >
          {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
        </button>
      </div>
    </aside>
  );
};
