import React, { useState } from 'react';
import { Plus, LogIn, Database } from 'lucide-react';
import { Room } from '../../api/types';

interface LeftRailProps {
  rooms: Room[];
  selectedRoomId: string | null;
  onSelectRoom: (roomId: string) => void;
  onCreateRoom: (name: string) => Promise<void>;
  onJoinRoom: (code: string) => Promise<void>;
  isMockMode: boolean;
}

export const LeftRail: React.FC<LeftRailProps> = ({
  rooms,
  selectedRoomId,
  onSelectRoom,
  onCreateRoom,
  onJoinRoom,
  isMockMode,
}) => {
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showJoinModal, setShowJoinModal] = useState(false);
  const [roomName, setRoomName] = useState('');
  const [inviteCode, setInviteCode] = useState('CAMPUS-7KQ2');
  const [errorMsg, setErrorMsg] = useState('');
  const [loading, setLoading] = useState(false);

  const getInitials = (name: string) => {
    return name
      .split(' ')
      .map((w) => w[0])
      .join('')
      .toUpperCase()
      .slice(0, 2);
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!roomName.trim()) return;
    try {
      setLoading(true);
      setErrorMsg('');
      await onCreateRoom(roomName.trim());
      setRoomName('');
      setShowCreateModal(false);
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to create room');
    } finally {
      setLoading(false);
    }
  };

  const handleJoin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inviteCode.trim()) return;
    try {
      setLoading(true);
      setErrorMsg('');
      await onJoinRoom(inviteCode.trim().toUpperCase());
      setShowJoinModal(false);
    } catch (err: any) {
      setErrorMsg(err.message || 'Code not found');
    } finally {
      setLoading(false);
    }
  };

  return (
    <aside className="w-[72px] bg-[#0B0C0F] border-r border-[#2A2D37] flex flex-col items-center py-3 select-none flex-shrink-0 z-30">
      {/* Brand icon */}
      <div className="w-12 h-12 rounded-2xl bg-[#6366F1]/10 border border-[#6366F1]/40 flex items-center justify-center text-[#6366F1] font-bold text-lg mb-4 shadow-sm">
        B
      </div>

      <div className="w-8 h-[1px] bg-[#2A2D37] mb-3" />

      {/* Room list */}
      <div className="flex-1 w-full flex flex-col items-center gap-3 overflow-y-auto px-1">
        {rooms.map((room) => {
          const isSelected = room.id === selectedRoomId;
          const initials = getInitials(room.name);
          const hasStale = (room.counts?.stale ?? 0) > 0;
          const hasPending = (room.counts?.pending_approvals ?? 0) > 0;

          return (
            <div key={room.id} className="relative group flex items-center justify-center w-full">
              {/* Selected pill on left edge */}
              {isSelected && (
                <div className="absolute left-0 w-1 h-9 bg-[#6366F1] rounded-r-full" />
              )}

              <button
                onClick={() => onSelectRoom(room.id)}
                title={room.name}
                className={`relative w-12 h-12 rounded-[18px] flex items-center justify-center font-semibold text-sm transition-all duration-200 ${
                  isSelected
                    ? 'bg-[#6366F1] text-white rounded-[14px]'
                    : 'bg-[#1D1F27] text-[#8B8FA3] hover:bg-[#2A2D37] hover:text-[#E6E7EB] hover:rounded-[14px]'
                }`}
              >
                <span>{initials}</span>

                {/* Stale amber dot */}
                {hasStale && (
                  <span
                    className="absolute -top-1 -right-1 w-3.5 h-3.5 bg-[#F59E0B] rounded-full border-2 border-[#0B0C0F] animate-pulse"
                    title={`${room.counts.stale} stale outputs`}
                  />
                )}

                {/* Pending approvals red dot */}
                {!hasStale && hasPending && (
                  <span
                    className="absolute -top-1 -right-1 w-3.5 h-3.5 bg-[#EF4444] rounded-full border-2 border-[#0B0C0F]"
                    title={`${room.counts.pending_approvals} approvals pending`}
                  />
                )}
              </button>
            </div>
          );
        })}

        {/* Action buttons */}
        <button
          onClick={() => {
            setErrorMsg('');
            setShowCreateModal(true);
          }}
          title="Create a room"
          className="w-12 h-12 rounded-[18px] bg-[#1D1F27] hover:bg-[#22C55E]/20 text-[#22C55E] hover:rounded-[14px] flex items-center justify-center transition-all duration-200"
        >
          <Plus className="w-5 h-5" />
        </button>

        <button
          onClick={() => {
            setErrorMsg('');
            setInviteCode('CAMPUS-7KQ2');
            setShowJoinModal(true);
          }}
          title="Join with invite code"
          className="w-12 h-12 rounded-[18px] bg-[#1D1F27] hover:bg-[#6366F1]/20 text-[#6366F1] hover:rounded-[14px] flex items-center justify-center transition-all duration-200"
        >
          <LogIn className="w-5 h-5" />
        </button>
      </div>

      {/* Mock data indicator */}
      {isMockMode && (
        <div
          className="mt-auto px-1.5 py-1 bg-[#F59E0B]/10 border border-[#F59E0B]/30 rounded text-[9px] font-mono text-[#F59E0B] flex flex-col items-center gap-0.5"
          title="Running in mock mode"
        >
          <Database className="w-3 h-3" />
          <span>MOCK</span>
        </div>
      )}

      {/* Create Room Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-[#1D1F27] border border-[#2A2D37] rounded-xl w-full max-w-md p-6 shadow-2xl">
            <h3 className="text-lg font-semibold text-[#E6E7EB] mb-2">Create a room</h3>
            <p className="text-sm text-[#8B8FA3] mb-4">
              A room is a shared project where teammates and agents collaborate.
            </p>

            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-[#8B8FA3] mb-1">
                  Room Name
                </label>
                <input
                  type="text"
                  autoFocus
                  placeholder="e.g. Campus App Launch"
                  value={roomName}
                  onChange={(e) => setRoomName(e.target.value)}
                  className="w-full px-3 py-2 bg-[#111217] border border-[#2A2D37] rounded-lg text-[#E6E7EB] text-sm focus:outline-none focus:border-[#6366F1]"
                />
              </div>

              {errorMsg && (
                <div className="text-xs text-[#EF4444] bg-[#EF4444]/10 border border-[#EF4444]/30 p-2 rounded">
                  {errorMsg}
                </div>
              )}

              <div className="flex justify-end gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="px-3.5 py-2 text-sm text-[#8B8FA3] hover:text-[#E6E7EB] transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={loading || !roomName.trim()}
                  className="px-4 py-2 bg-[#6366F1] hover:bg-[#4F46E5] disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors"
                >
                  {loading ? 'Creating...' : 'Create Room'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Join Room Modal */}
      {showJoinModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-[#1D1F27] border border-[#2A2D37] rounded-xl w-full max-w-md p-6 shadow-2xl">
            <h3 className="text-lg font-semibold text-[#E6E7EB] mb-2">Join with invite code</h3>
            <p className="text-sm text-[#8B8FA3] mb-4">
              Enter the invite code given to you by a room mentor.
            </p>

            <form onSubmit={handleJoin} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-[#8B8FA3] mb-1">
                  Invite Code
                </label>
                <input
                  type="text"
                  autoFocus
                  placeholder="e.g. CAMPUS-7KQ2"
                  value={inviteCode}
                  onChange={(e) => setInviteCode(e.target.value)}
                  className="w-full px-3 py-2 bg-[#111217] border border-[#2A2D37] rounded-lg text-[#E6E7EB] font-mono text-sm uppercase tracking-wider focus:outline-none focus:border-[#6366F1]"
                />
              </div>

              {errorMsg && (
                <div className="text-xs text-[#EF4444] bg-[#EF4444]/10 border border-[#EF4444]/30 p-2 rounded">
                  {errorMsg}
                </div>
              )}

              <div className="flex justify-end gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setShowJoinModal(false)}
                  className="px-3.5 py-2 text-sm text-[#8B8FA3] hover:text-[#E6E7EB] transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={loading || !inviteCode.trim()}
                  className="px-4 py-2 bg-[#6366F1] hover:bg-[#4F46E5] disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors"
                >
                  {loading ? 'Joining...' : 'Join Room'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </aside>
  );
};
