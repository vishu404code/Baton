import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { ToolType, Status, Role, AgentRole } from '../api/types';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatTimeAgo(dateString: string): string {
  try {
    const date = new Date(dateString);
    const now = new Date();
    const diffSeconds = Math.floor((now.getTime() - date.getTime()) / 1000);

    if (diffSeconds < 5) return 'just now';
    if (diffSeconds < 60) return `${diffSeconds}s ago`;
    const diffMinutes = Math.floor(diffSeconds / 60);
    if (diffMinutes < 60) return `${diffMinutes}m ago`;
    const diffHours = Math.floor(diffMinutes / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    return date.toLocaleDateString();
  } catch {
    return dateString;
  }
}

export function formatTimestamp(dateString: string): string {
  try {
    const date = new Date(dateString);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return dateString;
  }
}

export function getToolBadgeInfo(tool?: ToolType) {
  switch (tool) {
    case 'claude_code':
      return { name: 'Claude Code', bg: 'bg-[#F59E0B]/10', border: 'border-[#F59E0B]/30', text: 'text-[#F59E0B]', color: '#F59E0B' };
    case 'codex':
      return { name: 'Codex', bg: 'bg-[#22D3EE]/10', border: 'border-[#22D3EE]/30', text: 'text-[#22D3EE]', color: '#22D3EE' };
    case 'gemini_cli':
      return { name: 'Gemini CLI', bg: 'bg-[#60A5FA]/10', border: 'border-[#60A5FA]/30', text: 'text-[#60A5FA]', color: '#60A5FA' };
    case 'cursor':
      return { name: 'Cursor', bg: 'bg-[#A78BFA]/10', border: 'border-[#A78BFA]/30', text: 'text-[#A78BFA]', color: '#A78BFA' };
    default:
      return { name: 'Agent', bg: 'bg-[#8B8FA3]/10', border: 'border-[#8B8FA3]/30', text: 'text-[#8B8FA3]', color: '#8B8FA3' };
  }
}

export function getStatusInfo(status: Status) {
  switch (status) {
    case 'approved':
      return { label: 'Approved', color: '#22C55E', bg: 'bg-[#22C55E]/10', border: 'border-[#22C55E]/30', text: 'text-[#22C55E]' };
    case 'stale':
      return { label: 'Stale', color: '#F59E0B', bg: 'bg-[#F59E0B]/10', border: 'border-[#F59E0B]/30', text: 'text-[#F59E0B]' };
    case 'rejected':
      return { label: 'Rejected', color: '#EF4444', bg: 'bg-[#EF4444]/10', border: 'border-[#EF4444]/30', text: 'text-[#EF4444]' };
    case 'claimed':
      return { label: 'In progress', color: '#6366F1', bg: 'bg-[#6366F1]/10', border: 'border-[#6366F1]/30', text: 'text-[#818CF8]' };
    case 'in_review':
      return { label: 'Needs approval', color: '#818CF8', bg: 'bg-[#818CF8]/10', border: 'border-[#818CF8]/30', text: 'text-[#818CF8]' };
    case 'open':
    default:
      return { label: 'Open', color: '#6B7280', bg: 'bg-[#6B7280]/10', border: 'border-[#6B7280]/30', text: 'text-[#9CA3AF]' };
  }
}
