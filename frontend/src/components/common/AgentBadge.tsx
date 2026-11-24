import React from 'react';
import { Bot, Terminal, Sparkles, Cpu } from 'lucide-react';
import { ToolType, Actor } from '../../api/types';
import { getToolBadgeInfo } from '../../lib/utils';

interface AgentBadgeProps {
  agent?: Partial<Actor> | null;
  name?: string;
  tool?: ToolType;
  color?: string;
  size?: 'sm' | 'md';
  showToolName?: boolean;
}

export const AgentBadge: React.FC<AgentBadgeProps> = ({
  agent,
  name,
  tool,
  color,
  size = 'md',
  showToolName = false,
}) => {
  const effectiveName = name || agent?.name || 'Agent';
  const effectiveTool = tool || (agent?.tool as ToolType) || 'other';
  const badgeInfo = getToolBadgeInfo(effectiveTool);
  const effectiveColor = color || agent?.color || badgeInfo.color;

  const getIcon = () => {
    switch (effectiveTool) {
      case 'claude_code':
        return <Bot className={size === 'sm' ? 'w-3 h-3' : 'w-3.5 h-3.5'} />;
      case 'codex':
        return <Terminal className={size === 'sm' ? 'w-3 h-3' : 'w-3.5 h-3.5'} />;
      case 'gemini_cli':
        return <Sparkles className={size === 'sm' ? 'w-3 h-3' : 'w-3.5 h-3.5'} />;
      default:
        return <Cpu className={size === 'sm' ? 'w-3 h-3' : 'w-3.5 h-3.5'} />;
    }
  };

  return (
    <span
      className={`inline-flex items-center gap-1.5 font-medium rounded-full border transition-all ${
        size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-xs'
      }`}
      style={{
        backgroundColor: `${effectiveColor}15`,
        borderColor: `${effectiveColor}40`,
        color: effectiveColor,
      }}
    >
      <span className="flex-shrink-0" style={{ color: effectiveColor }}>
        {getIcon()}
      </span>
      <span className="truncate max-w-[140px]">{effectiveName}</span>
      {showToolName && (
        <span className="opacity-70 text-[10px] uppercase font-mono tracking-wider ml-0.5">
          ({badgeInfo.name})
        </span>
      )}
    </span>
  );
};
