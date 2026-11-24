import React from 'react';
import { AlertTriangle, X } from 'lucide-react';

interface StaleBannerProps {
  alert: { message: string; count: number } | null;
  onDismiss: () => void;
  onViewDecisions?: () => void;
}

export const StaleBanner: React.FC<StaleBannerProps> = ({
  alert,
  onDismiss,
  onViewDecisions,
}) => {
  if (!alert) return null;

  return (
    <div className="bg-[#F59E0B]/15 border-b border-[#F59E0B]/40 px-4 py-2.5 flex items-center justify-between text-xs text-[#F59E0B] shadow-sm animate-fadeIn">
      <div className="flex items-center gap-2.5">
        <AlertTriangle className="w-4 h-4 flex-shrink-0 animate-bounce" />
        <span className="font-semibold">{alert.message}</span>
        {onViewDecisions && (
          <button
            onClick={onViewDecisions}
            className="underline hover:text-white ml-2 transition-colors font-medium"
          >
            View in Decisions →
          </button>
        )}
      </div>

      <button
        onClick={onDismiss}
        className="p-1 hover:bg-[#F59E0B]/20 rounded transition-colors text-[#F59E0B]"
        title="Dismiss alert"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  );
};
