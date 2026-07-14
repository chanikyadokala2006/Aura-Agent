import { useEffect, useRef } from 'react';
import { Terminal, Code2, CheckCircle2, Image as ImageIcon } from 'lucide-react';

interface ReasoningStep {
  text: string;
  isTool: boolean;
  id: string;
}

interface SubagentTrackerProps {
  steps: ReasoningStep[];
  isResponding: boolean;
  screenshot: string | null;
}

export function SubagentTracker({ steps, isResponding, screenshot }: SubagentTrackerProps) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [steps, screenshot]);

  return (
    <div className="flex-1 flex flex-col bg-[#0b0b10] overflow-hidden border-l border-[#232333]">
      <div className="px-4 py-3 bg-[#101017] border-b border-[#232333] flex items-center justify-between shadow-sm z-10">
        <span className="text-[10px] font-mono-custom text-slate-400 uppercase tracking-widest flex items-center gap-2">
          <Terminal size={14} className="text-cyan-500/70" />
          Execution Tracker
        </span>
        {isResponding && (
          <div className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-cyan-500/10 border border-cyan-500/20 text-[9px] text-cyan-400 font-mono-custom">
            <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-ping"></span>
            ACTIVE
          </div>
        )}
      </div>
      
      <div className="flex-1 p-4 overflow-y-auto space-y-4">
        {steps.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-slate-600 font-mono-custom text-xs">
            <Terminal size={32} className="mb-3 opacity-20" />
            <p>Awaiting execution sequence...</p>
          </div>
        ) : (
          <div className="space-y-4 relative before:absolute before:inset-y-0 before:left-[11px] before:w-px before:bg-[#232333]">
            {steps.map((step) => (
              <div key={step.id} className="relative flex gap-3 group">
                <div className="flex-shrink-0 mt-0.5 z-10 relative">
                  <div className={`w-[22px] h-[22px] rounded-full border flex items-center justify-center bg-[#0b0b10]
                    ${step.isTool 
                      ? 'border-cyan-500/40 text-cyan-400 shadow-[0_0_8px_rgba(6,182,212,0.15)]' 
                      : 'border-[#232333] text-slate-500 group-hover:border-slate-600'
                    }`}
                  >
                    {step.isTool ? <Code2 size={10} /> : <CheckCircle2 size={10} />}
                  </div>
                </div>
                <div className={`flex-1 pt-0.5 text-xs font-mono-custom ${step.isTool ? 'text-cyan-400/90' : 'text-slate-400'}`}>
                  {step.text}
                </div>
              </div>
            ))}
          </div>
        )}
        
        {screenshot && (
          <div className="relative flex gap-3 mt-4">
            <div className="flex-shrink-0 mt-0.5 z-10 relative">
              <div className="w-[22px] h-[22px] rounded-full border border-purple-500/40 text-purple-400 flex items-center justify-center bg-[#0b0b10] shadow-[0_0_8px_rgba(168,85,247,0.15)]">
                <ImageIcon size={10} />
              </div>
            </div>
            <div className="flex-1">
              <span className="text-[10px] text-purple-400 font-mono-custom uppercase tracking-wider mb-2 block">
                Visual State Capture
              </span>
              <img 
                src={screenshot} 
                alt="State capture" 
                className="max-h-32 rounded border border-[#232333] shadow cursor-zoom-in hover:max-h-[300px] transition-all duration-300"
              />
            </div>
          </div>
        )}

        <div ref={endRef} />
      </div>
    </div>
  );
}
