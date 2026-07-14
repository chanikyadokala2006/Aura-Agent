import { 
  MessageSquare, 
  Settings, 
  TerminalSquare, 
  Cpu, 
  Network,
  Plus,
  MessageCircle
} from 'lucide-react';

export interface SessionMeta {
  id: string;
  title: string;
  timestamp: number;
}

interface SidebarProps {
  sessions: SessionMeta[];
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewSession: () => void;
}

export function Sidebar({ sessions, activeSessionId, onSelectSession, onNewSession }: SidebarProps) {
  return (
    <aside className="w-64 flex flex-col py-6 bg-[#0a0a0f] border-r border-[#232333] shrink-0">
      <div className="flex items-center gap-3 px-6 mb-8">
        <div className="w-10 h-10 rounded-xl bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400 shadow-[0_0_15px_rgba(6,182,212,0.15)] shrink-0">
          <Cpu size={24} />
        </div>
        <span className="font-mono-custom text-sm font-semibold text-slate-200">WORKSPACES</span>
      </div>
      
      <div className="px-4 mb-4">
        <button 
          onClick={onNewSession}
          className="w-full py-2.5 px-3 rounded border border-dashed border-cyan-500/30 text-cyan-400 flex items-center justify-center gap-2 hover:bg-cyan-500/10 transition-colors font-mono-custom text-xs uppercase tracking-wider font-semibold"
        >
          <Plus size={16} />
          New Chat
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-3 space-y-1">
        <div className="px-3 pb-2 text-[10px] font-mono-custom text-slate-500 uppercase tracking-widest">
          Recent Sessions
        </div>
        {sessions.map((sess) => (
          <button 
            key={sess.id}
            onClick={() => onSelectSession(sess.id)}
            className={`w-full text-left flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors group ${
              activeSessionId === sess.id 
                ? 'bg-[#181825] text-cyan-400 border border-cyan-500/20 shadow-sm' 
                : 'text-slate-400 hover:text-slate-200 hover:bg-[#181825]/50 border border-transparent'
            }`}
          >
            <MessageCircle size={16} className={`shrink-0 ${activeSessionId === sess.id ? 'text-cyan-400' : 'text-slate-500'}`} />
            <div className="flex-1 overflow-hidden">
              <div className="text-xs font-sans truncate font-medium">{sess.title}</div>
              <div className="text-[10px] text-slate-500 font-mono-custom mt-0.5">
                {new Date(sess.timestamp).toLocaleDateString()}
              </div>
            </div>
          </button>
        ))}
        {sessions.length === 0 && (
          <div className="text-center px-4 py-8 text-xs text-slate-500 font-mono-custom">
            No previous chats found.
          </div>
        )}
      </div>

      <nav className="flex items-center justify-around px-4 mt-auto pt-4 border-t border-[#232333]">
        <button className="p-2.5 rounded text-cyan-400 bg-[#181825] transition-colors shadow-sm border border-cyan-500/20">
          <MessageSquare size={18} />
        </button>
        <button className="p-2.5 rounded text-slate-500 hover:text-slate-300 hover:bg-[#181825] transition-colors">
          <TerminalSquare size={18} />
        </button>
        <button className="p-2.5 rounded text-slate-500 hover:text-slate-300 hover:bg-[#181825] transition-colors">
          <Network size={18} />
        </button>
        <button className="p-2.5 rounded text-slate-500 hover:text-slate-300 hover:bg-[#181825] transition-colors">
          <Settings size={18} />
        </button>
      </nav>
    </aside>
  );
}
