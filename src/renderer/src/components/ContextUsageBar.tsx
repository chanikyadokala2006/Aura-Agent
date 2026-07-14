import { Activity, Database, Clock } from 'lucide-react';

export function ContextUsageBar() {
  return (
    <div className="bg-[#101017] border-t border-[#232333] px-4 py-2 flex items-center justify-between text-[10px] font-mono-custom text-slate-500">
      <div className="flex items-center gap-6">
        <div className="flex items-center gap-2" title="Memory Context">
          <Database size={14} className="text-cyan-500/70" />
          <span>CONTEXT: <span className="text-slate-300">12.4K</span> / 128K</span>
        </div>
        <div className="flex items-center gap-2" title="System Load">
          <Activity size={14} className="text-emerald-500/70" />
          <span>LOAD: <span className="text-emerald-400">14%</span></span>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Clock size={14} className="text-slate-600" />
        <span>UPTIME: <span className="text-slate-300">00:14:23</span></span>
      </div>
    </div>
  );
}
