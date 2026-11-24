import React, { useState, useEffect } from 'react';
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from '@tanstack/react-query';
import { LeftRail } from './components/layout/LeftRail';
import { RoomSidebar, ActiveView } from './components/layout/RoomSidebar';
import { RightPanel } from './components/layout/RightPanel';
import { StaleBanner } from './components/layout/StaleBanner';
import { WelcomeModal } from './views/WelcomeModal';
import { BoardView } from './views/BoardView';
import { DecisionsView } from './views/DecisionsView';
import { VerificationView } from './views/VerificationView';
import { TraceView } from './views/TraceView';
import { RecoveryView } from './views/RecoveryView';
import { TimelineView } from './views/TimelineView';
import { MembersView } from './views/MembersView';
import { SettingsView } from './views/SettingsView';
import { ModelsView } from './views/ModelsView';
import { ContextView } from './views/ContextView';
import { RoadmapView } from './views/RoadmapView';
import { LiveView } from './views/LiveView';
import { SetupView } from './views/SetupView';
import { api } from './api/client';
import { useRoomWebSocket } from './api/useWebSocket';
import { Room, Member, Agent, Event } from './api/types';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 2000,
      retry: 1,
    },
  },
});

function BatonApp() {
  const qc = useQueryClient();
  const [currentUser, setCurrentUser] = useState<{ id: string; display_name: string } | null>(null);
  const [selectedRoomId, setSelectedRoomId] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<ActiveView>('roadmap');
  const [isMockMode, setIsMockMode] = useState<boolean>(api.getIsMockMode());
  const [manualStaleAlert, setManualStaleAlert] = useState<{ message: string; count: number } | null>(null);

  // Health check on load
  useEffect(() => {
    api.setMockModeListener(setIsMockMode);
    api.checkHealth();
  }, []);

  // Sign in: reuse the saved session; otherwise, in the desktop app, sign in as the local owner.
  const [authChecked, setAuthChecked] = useState(false);
  useEffect(() => {
    const signInLocally = async () => {
      const local = await api.localSession();
      if (local) {
        setCurrentUser(local.user);
        setSelectedRoomId(local.room_id);
      }
      setAuthChecked(true);
    };
    const token = api.getToken();
    if (token) {
      api
        .getMe()
        .then((res) => {
          if (res?.user) setCurrentUser(res.user);
          setAuthChecked(true);
        })
        .catch(() => {
          api.setToken(null);
          signInLocally();
        });
    } else {
      signInLocally();
    }
  }, []);

  // Fetch rooms list
  const { data: roomsData, refetch: refetchRooms } = useQuery<{ rooms: Room[] }>({
    queryKey: ['rooms'],
    queryFn: () => api.getRooms(),
    enabled: !!currentUser,
  });

  const rooms = roomsData?.rooms || [];

  // Auto-select first room or "Campus App Launch"
  useEffect(() => {
    if (rooms.length > 0 && !selectedRoomId) {
      const demoRoom = rooms.find((r) => r.invite_code === 'CAMPUS-7KQ2' || r.name.includes('Campus'));
      setSelectedRoomId(demoRoom ? demoRoom.id : rooms[0].id);
    }
  }, [rooms, selectedRoomId]);

  const selectedRoom = rooms.find((r) => r.id === selectedRoomId) || null;

  // WebSocket for current room
  const {
    status: wsStatus,
    liveEvents,
    staleAlert: wsStaleAlert,
    clearStaleAlert: clearWsStaleAlert,
  } = useRoomWebSocket(selectedRoomId);

  // Presence & Members for right panel
  const { data: membersData } = useQuery<{ members: Member[] }>({
    queryKey: ['members', selectedRoomId],
    queryFn: () => api.getMembers(selectedRoomId!),
    enabled: !!selectedRoomId,
  });

  const { data: agentsData } = useQuery<{ agents: Agent[] }>({
    queryKey: ['agents', selectedRoomId],
    queryFn: () => api.getAgents(selectedRoomId!),
    enabled: !!selectedRoomId,
  });

  const { data: eventsData } = useQuery<{ events: Event[] }>({
    queryKey: ['events', selectedRoomId],
    queryFn: () => api.getEvents(selectedRoomId!, 40),
    enabled: !!selectedRoomId,
  });

  const members = membersData?.members || [];
  const agents = agentsData?.agents || [];
  // Merge live WS events with historical events
  const combinedEvents = [...liveEvents, ...(eventsData?.events || [])];
  // Deduplicate by seq / id
  const seenSeqs = new Set<string>();
  const uniqueEvents = combinedEvents.filter((ev) => {
    const key = `${ev.seq || ''}-${ev.id || ''}`;
    if (!key || key === '-') return true;
    if (seenSeqs.has(key)) return false;
    seenSeqs.add(key);
    return true;
  });

  // Effective alert (from manual decision edit or from WebSocket)
  const effectiveStaleAlert = manualStaleAlert || wsStaleAlert;

  const handleCreateRoom = async (name: string) => {
    const newRoom = await api.createRoom(name);
    await refetchRooms();
    setSelectedRoomId(newRoom.id);
  };

  const handleJoinRoom = async (code: string) => {
    const joinedRoom = await api.joinRoom(code);
    await refetchRooms();
    setSelectedRoomId(joinedRoom.id);
  };

  if (!authChecked) {
    return <div className="h-screen w-screen bg-[#0B0C0F] flex items-center justify-center text-xs text-[#8B8FA3]">Starting Baton…</div>;
  }

  if (!currentUser) {
    return (
      <WelcomeModal
        onSignedIn={(user) => {
          setCurrentUser(user);
          refetchRooms();
        }}
      />
    );
  }

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#0B0C0F] text-[#E6E7EB]">
      {/* 1. Left Rail (72px) */}
      <LeftRail
        rooms={rooms}
        selectedRoomId={selectedRoomId}
        onSelectRoom={(id) => setSelectedRoomId(id)}
        onCreateRoom={handleCreateRoom}
        onJoinRoom={handleJoinRoom}
        isMockMode={isMockMode}
      />

      {/* 2. Room Sidebar (240px) */}
      <RoomSidebar
        room={selectedRoom}
        activeView={activeView}
        onSelectView={(v) => setActiveView(v)}
        currentUser={currentUser}
        myRole={selectedRoom?.my_role || 'member'}
      />

      {/* 3. Main Center Area */}
      <main className="flex-1 flex flex-col h-full min-w-0 bg-[#16171D] overflow-hidden relative">
        {/* Amber Stale Banner */}
        <StaleBanner
          alert={effectiveStaleAlert}
          onDismiss={() => {
            setManualStaleAlert(null);
            clearWsStaleAlert();
          }}
          onViewDecisions={() => setActiveView('decisions')}
        />

        {/* View Switcher */}
        {selectedRoomId ? (
          <>
            {activeView === 'roadmap' && <RoadmapView roomId={selectedRoomId} />}
            {activeView === 'live' && <LiveView roomId={selectedRoomId} />}
            {activeView === 'setup' && <SetupView roomId={selectedRoomId} />}
            {activeView === 'board' && (
              <BoardView
                roomId={selectedRoomId}
                myRole={selectedRoom?.my_role || 'member'}
              />
            )}
            {activeView === 'decisions' && (
              <DecisionsView
                roomId={selectedRoomId}
                myRole={selectedRoom?.my_role || 'member'}
                onDecisionSaved={(alert) => setManualStaleAlert(alert)}
              />
            )}
            {activeView === 'verification' && (
              <VerificationView roomId={selectedRoomId} />
            )}
            {activeView === 'trace' && (
              <TraceView roomId={selectedRoomId} />
            )}
            {activeView === 'recovery' && (
              <RecoveryView roomId={selectedRoomId} />
            )}
            {activeView === 'timeline' && (
              <TimelineView roomId={selectedRoomId} />
            )}
            {activeView === 'members' && (
              <MembersView
                roomId={selectedRoomId}
                myRole={selectedRoom?.my_role || 'member'}
                inviteCode={selectedRoom?.invite_code || ''}
                currentUserId={currentUser.id}
              />
            )}
            {activeView === 'context' && selectedRoomId && <ContextView
                roomId={selectedRoomId}
                demoRoomId={rooms.find((r) => r.name.startsWith('Live demo'))?.id}
                onOpenKeys={() => setActiveView('setup')}
                onOpenDemo={() => setSelectedRoomId(rooms.find((r) => r.name.startsWith('Live demo'))!.id)}
              />}
            {activeView === 'models' && <ModelsView roomId={selectedRoomId} />}
            {activeView === 'settings' && (
              <SettingsView
                room={selectedRoom}
                myRole={selectedRoom?.my_role || 'member'}
              />
            )}
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-sm text-[#8B8FA3]">
            Select or create a room to get started.
          </div>
        )}
      </main>

      {/* 4. Right Panel (300px collapsible) */}
      {!['context', 'board', 'models', 'roadmap', 'live', 'setup'].includes(activeView) && (
        <RightPanel
          members={members}
          agents={agents}
          events={uniqueEvents}
          wsStatus={wsStatus}
        />
      )}
    </div>
  );
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BatonApp />
    </QueryClientProvider>
  );
}

export default App;
