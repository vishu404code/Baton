import React, { useState, useMemo } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  Node,
  Edge,
  Position,
  MarkerType,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  FileCheck,
  GitBranch,
  Bot,
  User,
  History,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Sparkles,
} from 'lucide-react';
import { TraceResponse, TraceNode, TraceEdge, BatonRecord } from '../api/types';
import { api } from '../api/client';
import { formatTimeAgo, formatTimestamp } from '../lib/utils';
import { useQuery } from '@tanstack/react-query';

interface TraceViewProps {
  roomId: string;
}

// Custom node rendering
function CustomNodeComponent({ data }: { data: TraceNode }) {
  const isStale = data.status === 'stale' || data.is_current === false;
  const isApproved = data.status === 'approved' || data.is_current === true;

  const getBorderColor = () => {
    if (isStale) return 'border-[#F59E0B] shadow-[#F59E0B]/20';
    if (isApproved) return 'border-[#22C55E] shadow-[#22C55E]/20';
    if (data.color) return `border-[${data.color}]`;
    return 'border-[#2A2D37]';
  };

  return (
    <div
      className={`px-3 py-2 rounded-xl bg-[#1D1F27] border-2 shadow-lg min-w-[140px] max-w-[200px] text-xs transition-all ${getBorderColor()}`}
    >
      <div className="flex items-center gap-1.5 mb-1">
        {data.kind === 'agent' ? (
          <Bot className="w-3.5 h-3.5 text-[#F59E0B]" />
        ) : data.kind === 'user' ? (
          <User className="w-3.5 h-3.5 text-[#6366F1]" />
        ) : (
          <GitBranch className="w-3.5 h-3.5 text-[#22C55E]" />
        )}
        <span className="font-semibold text-[#E6E7EB] truncate">{data.label}</span>
      </div>

      {data.subtitle && (
        <div className="text-[10px] text-[#8B8FA3] truncate mb-1">{data.subtitle}</div>
      )}

      {data.status && (
        <div className="flex items-center gap-1 text-[9px] font-mono uppercase">
          {isStale ? (
            <span className="text-[#F59E0B] font-bold flex items-center gap-0.5">
              <AlertTriangle className="w-2.5 h-2.5" /> stale
            </span>
          ) : (
            <span className="text-[#22C55E] font-bold flex items-center gap-0.5">
              <CheckCircle2 className="w-2.5 h-2.5" /> current
            </span>
          )}
        </div>
      )}
    </div>
  );
}

const nodeTypes = {
  custom: CustomNodeComponent,
};

export const TraceView: React.FC<TraceViewProps> = ({ roomId }) => {
  const [selectedRecordId, setSelectedRecordId] = useState<string>('');

  // Fetch available outputs / records to trace
  const { data: recordsData } = useQuery<{ records: BatonRecord[] }>({
    queryKey: ['records', roomId],
    queryFn: () => api.getRecords(roomId),
  });

  const records = recordsData?.records || [];
  const traceableRecords = records.filter(
    (r) => r.type === 'draft' || r.type === 'review' || r.type === 'task' || r.type === 'decision'
  );

  // Set default selection
  const activeRecordId = selectedRecordId || traceableRecords[0]?.id || 'rec_draft1';

  // Fetch trace graph for active record
  const { data: traceData, isLoading } = useQuery<TraceResponse>({
    queryKey: ['trace', activeRecordId],
    queryFn: () => api.getTrace(activeRecordId),
    enabled: !!activeRecordId,
  });

  // Convert API nodes & edges into React Flow format (Left-to-Right layout)
  const { flowNodes, flowEdges } = useMemo(() => {
    if (!traceData || !traceData.nodes) return { flowNodes: [], flowEdges: [] };

    // Layout left-to-right columns based on kind or level
    const kindOrder: Record<string, number> = {
      user: 0,
      decision: 1,
      revision: 2,
      agent: 3,
      draft: 4,
    };

    const nodesByKind: Record<string, TraceNode[]> = {};
    traceData.nodes.forEach((n) => {
      const k = n.kind === 'revision' && n.label.includes('Decision') ? 'decision' : n.kind;
      if (!nodesByKind[k]) nodesByKind[k] = [];
      nodesByKind[k].push(n);
    });

    const flowNodes: Node[] = [];
    let colIdx = 0;

    // Arrange nodes in columns
    ['user', 'decision', 'revision', 'agent'].forEach((kind) => {
      const list = nodesByKind[kind] || [];
      list.forEach((n, rowIdx) => {
        flowNodes.push({
          id: n.id,
          type: 'custom',
          position: {
            x: colIdx * 220 + 30,
            y: rowIdx * 110 + 50,
          },
          data: { ...n } as Record<string, unknown>,
          sourcePosition: Position.Right,
          targetPosition: Position.Left,
        });
      });
      if (list.length > 0) colIdx++;
    });

    const flowEdges: Edge[] = (traceData.edges || []).map((e, idx) => {
      const isStaleEdge = e.kind === 'supersedes' || e.label?.includes('stale');
      return {
        id: `e-${e.from}-${e.to}-${idx}`,
        source: e.from,
        target: e.to,
        label: e.kind.replace('_', ' '),
        animated: e.kind === 'based_on',
        style: {
          stroke: isStaleEdge ? '#F59E0B' : '#6366F1',
          strokeWidth: 2,
        },
        labelStyle: {
          fill: '#8B8FA3',
          fontSize: 10,
          fontFamily: 'monospace',
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: isStaleEdge ? '#F59E0B' : '#6366F1',
        },
      };
    });

    return { flowNodes, flowEdges };
  }, [traceData]);

  return (
    <div className="flex-1 flex flex-col h-full bg-[#16171D] overflow-hidden select-none">
      {/* Header bar */}
      <div className="h-16 px-6 border-b border-[#2A2D37] flex items-center justify-between flex-shrink-0">
        <div>
          <h1 className="text-base font-bold text-[#E6E7EB] flex items-center gap-2">
            <FileCheck className="w-4 h-4 text-[#6366F1]" />
            <span>Evidence Trace Graph</span>
          </h1>
          <p className="text-xs text-[#8B8FA3]">
            Trace an output left-to-right back to decisions, cited sources, and teammate actions.
          </p>
        </div>

        {/* Record selector */}
        {traceableRecords.length > 0 && (
          <div className="flex items-center gap-2 text-xs">
            <span className="text-[#8B8FA3]">Tracing output:</span>
            <select
              value={activeRecordId}
              onChange={(e) => setSelectedRecordId(e.target.value)}
              className="bg-[#111217] border border-[#2A2D37] rounded-lg px-3 py-1.5 text-xs text-[#E6E7EB] focus:outline-none focus:border-[#6366F1]"
            >
              {traceableRecords.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label}: {r.title}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* Main Body: Graph + Story Panel */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left: React Flow Graph canvas */}
        <div className="flex-1 h-full relative bg-[#0E0F13]">
          {isLoading ? (
            <div className="h-full flex items-center justify-center text-xs text-[#8B8FA3]">
              Generating evidence graph...
            </div>
          ) : (
            <ReactFlow
              nodes={flowNodes}
              edges={flowEdges}
              nodeTypes={nodeTypes}
              fitView
              className="bg-[#0B0C0F]"
            >
              <Background color="#1D1F27" gap={16} size={1} />
              <Controls className="bg-[#1D1F27] border border-[#2A2D37] rounded-lg text-white" />
            </ReactFlow>
          )}
        </div>

        {/* Right: Story panel */}
        <div className="w-[320px] border-l border-[#2A2D37] bg-[#111217] p-5 flex flex-col overflow-y-auto flex-shrink-0">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-[#8B8FA3] mb-4">
            <History className="w-4 h-4 text-[#6366F1]" />
            <span>Provenance Story</span>
          </div>

          <div className="space-y-4">
            {traceData?.story && traceData.story.length > 0 ? (
              traceData.story.map((item, i) => (
                <div key={i} className="relative pl-5 border-l border-[#2A2D37] space-y-1">
                  <span className="absolute -left-1.5 top-1 w-3 h-3 rounded-full bg-[#1D1F27] border-2 border-[#6366F1]" />
                  <div className="flex items-center justify-between text-[10px] text-[#8B8FA3] font-mono">
                    <span>{formatTimestamp(item.at)}</span>
                    <span>#{item.seq}</span>
                  </div>
                  <p className="text-xs text-[#E6E7EB] leading-relaxed">{item.text}</p>
                </div>
              ))
            ) : (
              <div className="text-xs text-[#8B8FA3] italic">
                Trace story is unavailable for this item.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
