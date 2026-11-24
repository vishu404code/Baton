import React from 'react';
import { CheckCircle2, AlertTriangle, XCircle, Clock, CircleDot, HelpCircle } from 'lucide-react';
import { Status } from '../../api/types';
import { getStatusInfo } from '../../lib/utils';

interface StatusChipProps {
  status: Status;
  label?: string;
  size?: 'sm' | 'md';
}

export const StatusChip: React.FC<StatusChipProps> = ({ status, label, size = 'md' }) => {
  const info = getStatusInfo(status);
  const text = label || info.label;

  const renderIcon = () => {
    const iconClass = size === 'sm' ? 'w-3 h-3' : 'w-3.5 h-3.5';
    switch (status) {
      case 'approved':
        return <CheckCircle2 className={`${iconClass} text-[#22C55E]`} />;
      case 'stale':
        return <AlertTriangle className={`${iconClass} text-[#F59E0B]`} />;
      case 'rejected':
        return <XCircle className={`${iconClass} text-[#EF4444]`} />;
      case 'claimed':
        return (
          <span className="relative flex h-2 w-2 mr-0.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#6366F1] opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-[#6366F1]"></span>
          </span>
        );
      case 'in_review':
        return <Clock className={`${iconClass} text-[#818CF8]`} />;
      case 'open':
      default:
        return <CircleDot className={`${iconClass} text-[#9CA3AF]`} />;
    }
  };

  return (
    <span
      className={`inline-flex items-center gap-1.5 font-medium rounded-full border ${info.bg} ${info.border} ${info.text} ${
        size === 'sm' ? 'px-2 py-0.5 text-[11px]' : 'px-2.5 py-1 text-xs'
      }`}
    >
      {renderIcon()}
      <span>{text}</span>
    </span>
  );
};
