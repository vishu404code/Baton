import React from 'react';

interface RevisionPillProps {
  label: string;
  revision: number;
  isCurrent?: boolean;
  onClick?: () => void;
}

export const RevisionPill: React.FC<RevisionPillProps> = ({
  label,
  revision,
  isCurrent = true,
  onClick,
}) => {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!onClick}
      className={`inline-flex items-center gap-1 font-mono text-xs px-2 py-0.5 rounded border transition-colors ${
        isCurrent
          ? 'bg-[#1D1F27] border-[#2A2D37] text-[#E6E7EB] hover:border-[#6366F1]/50'
          : 'bg-[#F59E0B]/10 border-[#F59E0B]/40 text-[#F59E0B] hover:bg-[#F59E0B]/20'
      } ${onClick ? 'cursor-pointer' : 'cursor-default'}`}
    >
      <span>{label}</span>
      <span className="opacity-60">·</span>
      <span>v{revision}</span>
      {!isCurrent && (
        <span className="ml-1 text-[10px] bg-[#F59E0B]/20 text-[#F59E0B] px-1 rounded uppercase">
          stale
        </span>
      )}
    </button>
  );
};
