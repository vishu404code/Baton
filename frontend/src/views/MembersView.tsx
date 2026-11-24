import React, { useState } from 'react';
import {
  Users,
  Bot,
  Plus,
  Copy,
  Check,
  Trash2,
  Key,
  Shield,
  FileCode,
  Radio,
  ExternalLink,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { Member, Agent, Role, ToolType, AgentRole, AgentConfigResponse } from '../api/types';
import { api } from '../api/client';
import { AgentBadge } from '../components/common/AgentBadge';
import { formatTimeAgo } from '../lib/utils';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

interface MembersViewProps {
  roomId: string;
  myRole: Role;
  inviteCode: string;
  currentUserId: string;
}

export const MembersView: React.FC<MembersViewProps> = ({
  roomId,
  myRole,
  inviteCode,
  currentUserId,
}) => {
  const queryClient = useQueryClient();
  const [copiedInvite, setCopiedInvite] = useState(false);
  const [showConnectModal, setShowConnectModal] = useState(false);
  const [showConfigModal, setShowConfigModal] = useState<AgentConfigResponse | null>(null);

  // New agent form
  // 'api:<provider>' = Baton runs it through that AI's API; 'tool:<name>' = a tool you run yourself (MCP).
  const [runsOn, setRunsOn] = useState<string>('api:anthropic');
  const tool: ToolType = runsOn.startsWith('tool:') ? (runsOn.slice(5) as ToolType) : 'other';
  const [agentRole, setAgentRole] = useState<AgentRole>('planner');
  const [agentName, setAgentName] = useState('');
  const [connectStep, setConnectStep] = useState<'form' | 'snippets'>('form');
  const [createdAgentData, setCreatedAgentData] = useState<{
    agent: Agent;
    token: string;
    config: AgentConfigResponse;
  } | null>(null);
  const [copiedToken, setCopiedToken] = useState(false);
  const [copiedSnippet, setCopiedSnippet] = useState<string | null>(null);
  const [activeSnippetTab, setActiveSnippetTab] = useState<string>('claude_code');
  const [showInstructions, setShowInstructions] = useState(false);
  const [connectLoading, setConnectLoading] = useState(false);

  const isOwner = myRole === 'owner';

  // Fetch members
  const { data: membersData } = useQuery<{ members: Member[] }>({
    queryKey: ['members', roomId],
    queryFn: () => api.getMembers(roomId),
  });

  // Fetch agents
  const { data: agentsData } = useQuery<{ agents: Agent[] }>({
    queryKey: ['agents', roomId],
    queryFn: () => api.getAgents(roomId),
  });

  const members = membersData?.members || [];
  const agents = agentsData?.agents || [];

  const copyInvite = () => {
    navigator.clipboard.writeText(inviteCode);
    setCopiedInvite(true);
    setTimeout(() => setCopiedInvite(false), 2000);
  };

  const copyToClipboard = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedSnippet(id);
    setTimeout(() => setCopiedSnippet(null), 2000);
  };

  // Change member role
  const handleRoleChange = async (userId: string, newRole: string) => {
    try {
      await api.updateMemberRole(roomId, userId, newRole);
      queryClient.invalidateQueries({ queryKey: ['members', roomId] });
    } catch (e: any) {
      alert(e.message || 'Failed to update member role');
    }
  };

  // Revoke agent
  const handleRevokeAgent = async (agentId: string) => {
    if (!confirm('Are you sure you want to revoke this agent?')) return;
    try {
      await api.revokeAgent(roomId, agentId);
      queryClient.invalidateQueries({ queryKey: ['agents', roomId] });
    } catch (e: any) {
      alert(e.message || 'Failed to revoke agent');
    }
  };

  // Show config for existing agent
  const handleShowConfig = async (agentId: string) => {
    try {
      const config = await api.getAgentConfig(roomId, agentId);
      setShowConfigModal(config);
      setActiveSnippetTab(config.tool);
    } catch (e: any) {
      alert(e.message || 'Failed to fetch agent config');
    }
  };

  // Create agent
  const handleCreateAgent = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setConnectLoading(true);
      const isApi = runsOn.startsWith('api:');
      const provider = isApi ? runsOn.slice(4) : undefined;
      const labels: Record<string, string> = { anthropic: 'Claude', openai: 'ChatGPT', deepseek: 'DeepSeek', gemini: 'Gemini', mock: 'Demo model' };
      const name = agentName.trim() || (isApi ? `${labels[provider!] ?? provider} ${agentRole}` : `${tool.replace('_', ' ')} ${agentRole}`);
      const res = await api.createAgent(roomId, isApi ? { name, role: agentRole, provider } : { name, tool, role: agentRole });

      queryClient.invalidateQueries({ queryKey: ['agents', roomId] });
      if (isApi) {
        // Baton runs this agent itself: nothing to paste anywhere.
        setShowConnectModal(false);
        setAgentName('');
        if (res.agent.runnable === false) {
          alert(`${name} is created, but ${labels[provider!]} has no API key yet. Add it in AI Models, then press Run on a task.`);
        }
        return;
      }
      setCreatedAgentData(res);
      setActiveSnippetTab(tool);
      setConnectStep('snippets');
    } catch (e: any) {
      alert(e.message || 'Failed to create agent');
    } finally {
      setConnectLoading(false);
    }
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-[#16171D] overflow-hidden select-none">
      {/* Header bar */}
      <div className="h-16 px-6 border-b border-[#2A2D37] flex items-center justify-between flex-shrink-0">
        <div>
          <h1 className="text-base font-bold text-[#E6E7EB] flex items-center gap-2">
            <Users className="w-4 h-4 text-[#6366F1]" />
            <span>Members & Agents</span>
          </h1>
          <p className="text-xs text-[#8B8FA3]">
            Teammates and their AI agents connected over MCP.
          </p>
        </div>

        <button
          onClick={() => {
            setConnectStep('form');
            setCreatedAgentData(null);
            setShowConnectModal(true);
          }}
          className="px-3.5 py-1.5 bg-[#6366F1] hover:bg-[#4F46E5] text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors shadow-sm"
        >
          <Bot className="w-4 h-4" />
          <span>Connect an Agent</span>
        </button>
      </div>

      {/* Main Content Area */}
      <div className="flex-1 overflow-y-auto p-6 space-y-8">
        {/* Invite Box */}
        <div className="p-5 rounded-2xl bg-[#111217] border border-[#2A2D37] flex items-center justify-between shadow-sm">
          <div>
            <div className="text-xs font-semibold text-[#E6E7EB] mb-1">
              Share room invite code
            </div>
            <div className="text-xs text-[#8B8FA3]">
              Anyone with this code can join the room and connect their own AI agents.
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className="px-4 py-2 bg-[#1D1F27] border border-[#2A2D37] rounded-xl font-mono text-sm font-bold text-[#6366F1] tracking-wider">
              {inviteCode}
            </span>
            <button
              onClick={copyInvite}
              className="p-2.5 bg-[#1D1F27] hover:bg-[#2A2D37] border border-[#2A2D37] rounded-xl text-[#8B8FA3] hover:text-[#E6E7EB] transition-colors"
              title="Copy invite code"
            >
              {copiedInvite ? (
                <Check className="w-4 h-4 text-[#22C55E]" />
              ) : (
                <Copy className="w-4 h-4" />
              )}
            </button>
          </div>
        </div>

        {/* Members Table */}
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-[#8B8FA3]">
            <Users className="w-4 h-4 text-[#6366F1]" />
            <span>Human Teammates ({members.length})</span>
          </div>

          <div className="border border-[#2A2D37] rounded-xl overflow-hidden bg-[#111217]/60">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="border-b border-[#2A2D37] bg-[#16171D] text-[11px] font-semibold uppercase tracking-wider text-[#8B8FA3]">
                  <th className="py-3 px-4">Member</th>
                  <th className="py-3 px-4">Role</th>
                  <th className="py-3 px-4">Connected Agents</th>
                  <th className="py-3 px-4">Joined</th>
                  {isOwner && <th className="py-3 px-4 text-right">Actions</th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-[#2A2D37]">
                {members.map((m) => {
                  const memberAgents = agents.filter(
                    (a) => a.user_id === m.user.id || m.agent_ids?.includes(a.id)
                  );

                  return (
                    <tr key={m.user.id} className="hover:bg-[#1D1F27]/50">
                      <td className="py-3.5 px-4">
                        <div className="flex items-center gap-2.5">
                          <span
                            className={`w-2 h-2 rounded-full ${
                              m.online ? 'bg-[#22C55E]' : 'bg-[#6B7280]'
                            }`}
                          />
                          <span className="font-medium text-[#E6E7EB]">
                            {m.user.display_name}
                          </span>
                        </div>
                      </td>

                      <td className="py-3.5 px-4">
                        {isOwner && m.role !== 'owner' ? (
                          <select
                            value={m.role}
                            onChange={(e) => handleRoleChange(m.user.id, e.target.value)}
                            className="bg-[#111217] border border-[#2A2D37] rounded-lg px-2.5 py-1 text-xs text-[#E6E7EB] capitalize focus:outline-none focus:border-[#6366F1]"
                          >
                            <option value="member">Member</option>
                            <option value="mentor">Mentor</option>
                          </select>
                        ) : (
                          <span className="capitalize font-mono text-[11px] text-[#6366F1] font-semibold">
                            {m.role}
                          </span>
                        )}
                      </td>

                      <td className="py-3.5 px-4">
                        <div className="flex flex-wrap gap-1.5">
                          {memberAgents.length > 0 ? (
                            memberAgents.map((agt) => (
                              <AgentBadge key={agt.id} agent={agt} size="sm" />
                            ))
                          ) : (
                            <span className="text-[#8B8FA3] italic text-[11px]">None</span>
                          )}
                        </div>
                      </td>

                      <td className="py-3.5 px-4 text-[#8B8FA3] font-mono text-[11px]">
                        {formatTimeAgo(m.joined_at)}
                      </td>

                      {isOwner && <td className="py-3.5 px-4 text-right" />}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Agents Table */}
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-[#8B8FA3]">
            <Bot className="w-4 h-4 text-[#22D3EE]" />
            <span>AI Agents ({agents.length})</span>
          </div>

          <div className="border border-[#2A2D37] rounded-xl overflow-hidden bg-[#111217]/60">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="border-b border-[#2A2D37] bg-[#16171D] text-[11px] font-semibold uppercase tracking-wider text-[#8B8FA3]">
                  <th className="py-3 px-4">Agent</th>
                  <th className="py-3 px-4">Tool</th>
                  <th className="py-3 px-4">Role</th>
                  <th className="py-3 px-4">Owner</th>
                  <th className="py-3 px-4">Current Task</th>
                  <th className="py-3 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#2A2D37]">
                {agents.map((agt) => (
                  <tr key={agt.id} className="hover:bg-[#1D1F27]/50">
                    <td className="py-3.5 px-4">
                      <div className="flex items-center gap-2">
                        <span
                          className={`w-2 h-2 rounded-full ${
                            agt.online ? 'bg-[#22C55E]' : 'bg-[#6B7280]'
                          }`}
                        />
                        <AgentBadge agent={agt} size="sm" />
                      </div>
                    </td>

                    <td className="py-3.5 px-4 font-mono text-[11px] text-[#8B8FA3] uppercase">
                      {agt.provider ? (
                        <span title={agt.runnable ? 'Ready to run' : 'No API key yet. Add it in AI Models'}>
                          {agt.provider} · {agt.model}
                          {!agt.runnable && <span className="text-[#F59E0B] normal-case"> · needs key</span>}
                        </span>
                      ) : (
                        agt.tool.replace('_', ' ')
                      )}
                    </td>

                    <td className="py-3.5 px-4 font-mono text-[11px] capitalize text-[#E6E7EB]">
                      {agt.role}
                    </td>

                    <td className="py-3.5 px-4 text-[#8B8FA3]">
                      {agt.user_name || 'Teammate'}
                    </td>

                    <td className="py-3.5 px-4">
                      {agt.working_on ? (
                        <span className="text-[#818CF8] text-[11px] font-mono">
                          {agt.working_on.label}: {agt.working_on.title}
                        </span>
                      ) : (
                        <span className="text-[#8B8FA3] italic text-[11px]">idle</span>
                      )}
                    </td>

                    <td className="py-3.5 px-4 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => handleShowConfig(agt.id)}
                          className="px-2.5 py-1 rounded bg-[#1D1F27] hover:bg-[#2A2D37] border border-[#2A2D37] text-[11px] text-[#E6E7EB] transition-colors"
                        >
                          Config
                        </button>
                        {(isOwner || agt.user_id === currentUserId) && (
                          <button
                            onClick={() => handleRevokeAgent(agt.id)}
                            className="p-1 rounded hover:bg-[#EF4444]/20 text-[#8B8FA3] hover:text-[#EF4444] transition-colors"
                            title="Revoke agent token"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Connect an Agent Dialog */}
      {showConnectModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-[#1D1F27] border border-[#2A2D37] rounded-2xl w-full max-w-2xl p-6 shadow-2xl space-y-4 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-[#2A2D37] pb-3">
              <div>
                <h3 className="text-base font-semibold text-[#E6E7EB]">
                  {connectStep === 'form' ? 'Connect an Agent' : 'Ready to Connect'}
                </h3>
                <p className="text-xs text-[#8B8FA3]">
                  {connectStep === 'form'
                    ? 'Register your AI coding tool with an exclusive role in this room.'
                    : 'Paste these snippets into your agent configuration.'}
                </p>
              </div>
            </div>

            {connectStep === 'form' ? (
              <form onSubmit={handleCreateAgent} className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-[#8B8FA3] mb-1">
                    Which AI?
                  </label>
                  <select
                    value={runsOn}
                    onChange={(e) => setRunsOn(e.target.value)}
                    className="w-full px-3 py-2 bg-[#111217] border border-[#2A2D37] rounded-lg text-[#E6E7EB] text-xs focus:outline-none focus:border-[#6366F1]"
                  >
                    <optgroup label="Baton runs it for you (needs an API key in AI Models)">
                      <option value="api:anthropic">Claude (Anthropic)</option>
                      <option value="api:openai">ChatGPT (OpenAI)</option>
                      <option value="api:deepseek">DeepSeek</option>
                      <option value="api:gemini">Gemini (Google)</option>
                      <option value="api:mock">Demo model (offline, no key)</option>
                    </optgroup>
                    <optgroup label="A tool you run yourself (connects over MCP)">
                      <option value="tool:antigravity">Antigravity</option>
                      <option value="tool:claude_code">Claude Code (CLI)</option>
                      <option value="tool:codex">Codex (CLI)</option>
                      <option value="tool:gemini_cli">Gemini CLI</option>
                      <option value="tool:cursor">Cursor</option>
                      <option value="tool:other">Other MCP client</option>
                    </optgroup>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-medium text-[#8B8FA3] mb-1">
                    Agent Name
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. Claude planner"
                    value={agentName}
                    onChange={(e) => setAgentName(e.target.value)}
                    className="w-full px-3 py-2 bg-[#111217] border border-[#2A2D37] rounded-lg text-[#E6E7EB] text-xs focus:outline-none focus:border-[#6366F1]"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-[#8B8FA3] mb-1">
                    Role in Room
                  </label>
                  <div className="grid grid-cols-3 gap-2">
                    {[
                      {
                        id: 'planner',
                        name: 'Planner',
                        desc: 'Can claim planner tasks and write drafts.',
                      },
                      {
                        id: 'reviewer',
                        name: 'Reviewer',
                        desc: 'Reviews drafts and submits approval verdicts.',
                      },
                      {
                        id: 'observer',
                        name: 'Observer',
                        desc: 'Read-only access to room records.',
                      },
                    ].map((r) => (
                      <button
                        type="button"
                        key={r.id}
                        onClick={() => setAgentRole(r.id as AgentRole)}
                        className={`p-3 rounded-xl border text-left transition-all ${
                          agentRole === r.id
                            ? 'bg-[#6366F1]/15 border-[#6366F1] text-[#E6E7EB]'
                            : 'bg-[#111217] border-[#2A2D37] text-[#8B8FA3] hover:text-[#E6E7EB]'
                        }`}
                      >
                        <div className="font-semibold text-xs text-[#E6E7EB]">
                          {r.name}
                        </div>
                        <div className="text-[10px] mt-1 leading-snug">{r.desc}</div>
                      </button>
                    ))}
                  </div>
                </div>

                <div className="flex justify-end gap-3 pt-3">
                  <button
                    type="button"
                    onClick={() => setShowConnectModal(false)}
                    className="px-4 py-2 text-xs text-[#8B8FA3] hover:text-[#E6E7EB]"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={connectLoading}
                    className="px-4 py-2 bg-[#6366F1] hover:bg-[#4F46E5] text-white rounded-lg text-xs font-semibold"
                  >
                    {connectLoading ? 'Generating Token...' : 'Create & Get Config'}
                  </button>
                </div>
              </form>
            ) : (
              <div className="space-y-4">
                {/* Red Token Box */}
                {createdAgentData && (
                  <div className="p-3.5 rounded-xl bg-[#EF4444]/10 border border-[#EF4444] space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold text-[#EF4444] flex items-center gap-1.5">
                        <Key className="w-4 h-4" />
                        Copy this token now. It won't be shown again.
                      </span>
                      <button
                        onClick={() => {
                          navigator.clipboard.writeText(createdAgentData.token);
                          setCopiedToken(true);
                          setTimeout(() => setCopiedToken(false), 2000);
                        }}
                        className="px-2.5 py-1 bg-[#EF4444]/20 hover:bg-[#EF4444]/30 rounded text-xs font-mono text-[#EF4444] flex items-center gap-1 transition-colors"
                      >
                        {copiedToken ? (
                          <Check className="w-3.5 h-3.5 text-[#22C55E]" />
                        ) : (
                          <Copy className="w-3.5 h-3.5" />
                        )}
                        <span>{copiedToken ? 'Copied' : 'Copy Token'}</span>
                      </button>
                    </div>
                    <div className="p-2 bg-[#0B0C0F] rounded font-mono text-xs text-[#E6E7EB] truncate select-all">
                      {createdAgentData.token}
                    </div>
                  </div>
                )}

                {/* 3 Numbered Steps */}
                <div className="space-y-3 text-xs">
                  <div className="font-semibold text-[#E6E7EB]">Setup in 3 steps:</div>

                  {/* Step 1 */}
                  <div className="p-3 bg-[#111217] rounded-xl border border-[#2A2D37] space-y-1.5">
                    <div className="font-semibold text-[#6366F1]">
                      1. Select your tool configuration
                    </div>
                    <div className="flex gap-2">
                      {['claude_code', 'codex', 'gemini_cli'].map((t) => (
                        <button
                          key={t}
                          onClick={() => setActiveSnippetTab(t)}
                          className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                            activeSnippetTab === t
                              ? 'bg-[#6366F1]/20 border-[#6366F1] text-[#E6E7EB]'
                              : 'bg-[#1D1F27] border-[#2A2D37] text-[#8B8FA3]'
                          }`}
                        >
                          {t === 'claude_code'
                            ? 'Claude Code'
                            : t === 'codex'
                            ? 'Codex'
                            : 'Gemini CLI'}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Step 2: Config snippet */}
                  <div className="p-3 bg-[#111217] rounded-xl border border-[#2A2D37] space-y-2">
                    <div className="flex items-center justify-between font-semibold text-[#6366F1]">
                      <span>2. Paste into your tool config</span>
                      <button
                        onClick={() => {
                          const snip =
                            createdAgentData?.config.snippets[activeSnippetTab] ||
                            JSON.stringify(
                              {
                                mcpServers: {
                                  baton: {
                                    url: `${api.getBaseUrl()}/mcp`,
                                    headers: {
                                      Authorization: `Bearer ${
                                        createdAgentData?.token || '<BATON_TOKEN>'
                                      }`,
                                    },
                                  },
                                },
                              },
                              null,
                              2
                            );
                          copyToClipboard(snip, 'snippet');
                        }}
                        className="flex items-center gap-1 text-[11px] text-[#8B8FA3] hover:text-[#E6E7EB]"
                      >
                        {copiedSnippet === 'snippet' ? (
                          <Check className="w-3.5 h-3.5 text-[#22C55E]" />
                        ) : (
                          <Copy className="w-3.5 h-3.5" />
                        )}
                        <span>{copiedSnippet === 'snippet' ? 'Copied' : 'Copy'}</span>
                      </button>
                    </div>

                    <pre className="p-3 bg-[#0B0C0F] border border-[#2A2D37] rounded-lg text-[11px] font-mono text-[#E6E7EB] overflow-x-auto whitespace-pre">
                      {createdAgentData?.config.snippets[activeSnippetTab] ||
                        JSON.stringify(
                          {
                            mcpServers: {
                              baton: {
                                url: `${api.getBaseUrl()}/mcp`,
                                headers: {
                                  Authorization: `Bearer ${
                                    createdAgentData?.token || '<BATON_TOKEN>'
                                  }`,
                                },
                              },
                            },
                          },
                          null,
                          2
                        )}
                    </pre>
                  </div>

                  {/* Step 3: Instructions markdown */}
                  <div className="p-3 bg-[#111217] rounded-xl border border-[#2A2D37] space-y-2">
                    <button
                      onClick={() => setShowInstructions(!showInstructions)}
                      className="w-full flex items-center justify-between text-xs font-semibold text-[#6366F1]"
                    >
                      <span>3. Paste into CLAUDE.md / AGENTS.md (optional)</span>
                      {showInstructions ? (
                        <ChevronUp className="w-3.5 h-3.5" />
                      ) : (
                        <ChevronDown className="w-3.5 h-3.5" />
                      )}
                    </button>

                    {showInstructions && (
                      <pre className="p-3 bg-[#0B0C0F] border border-[#2A2D37] rounded-lg text-[11px] font-mono text-[#E6E7EB] overflow-x-auto whitespace-pre">
                        {createdAgentData?.config.instructions_md ||
                          '# Baton Coordination\nUse get_room_context, list_tasks, claim_task, and submit_result to coordinate with teammates.'}
                      </pre>
                    )}
                  </div>
                </div>

                {/* Live connection status indicator */}
                <div className="p-3 bg-[#111217] rounded-xl border border-[#2A2D37] flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2 text-[#8B8FA3]">
                    <span className="w-2 h-2 rounded-full bg-[#F59E0B] animate-ping" />
                    <span>Waiting for the agent to connect over MCP...</span>
                  </div>
                  <button
                    onClick={() => setShowConnectModal(false)}
                    className="px-4 py-1.5 bg-[#6366F1] hover:bg-[#4F46E5] text-white font-medium rounded-lg"
                  >
                    Done
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Existing Agent Config Modal */}
      {showConfigModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-[#1D1F27] border border-[#2A2D37] rounded-2xl w-full max-w-xl p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-[#2A2D37] pb-3">
              <h3 className="text-base font-semibold text-[#E6E7EB]">
                Agent Configuration Snippets
              </h3>
              <button
                onClick={() => setShowConfigModal(null)}
                className="text-xs text-[#8B8FA3] hover:text-[#E6E7EB]"
              >
                Close
              </button>
            </div>

            <div className="p-2.5 bg-[#F59E0B]/10 border border-[#F59E0B]/30 rounded-lg text-xs text-[#F59E0B]">
              Tokens are only shown at creation. Replace <code className="font-mono">&lt;BATON_TOKEN&gt;</code> with your token or reconnect the agent.
            </div>

            <div className="space-y-3">
              <div className="flex gap-2">
                {Object.keys(showConfigModal.snippets || { claude_code: '', codex: '' }).map((k) => (
                  <button
                    key={k}
                    onClick={() => setActiveSnippetTab(k)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                      activeSnippetTab === k
                        ? 'bg-[#6366F1]/20 border-[#6366F1] text-[#E6E7EB]'
                        : 'bg-[#111217] border-[#2A2D37] text-[#8B8FA3]'
                    }`}
                  >
                    {k}
                  </button>
                ))}
              </div>

              <pre className="p-3 bg-[#0B0C0F] border border-[#2A2D37] rounded-lg text-[11px] font-mono text-[#E6E7EB] overflow-x-auto whitespace-pre">
                {showConfigModal.snippets[activeSnippetTab] ||
                  showConfigModal.snippets[showConfigModal.tool] ||
                  'No snippet'}
              </pre>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
