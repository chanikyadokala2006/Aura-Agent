import React, { useState, useEffect, useRef } from 'react';
import { Sidebar } from './components/Sidebar';
import type { SessionMeta } from './components/Sidebar';
import { ContextUsageBar } from './components/ContextUsageBar';
import { SubagentTracker } from './components/SubagentTracker';
import { MessageMarkdown } from './components/MessageMarkdown';

interface ReasoningStep {
  text: string;
  isTool: boolean;
  id: string;
}

interface Message {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  reasoning?: ReasoningStep[];
  screenshot?: string;
  timestamp: number;
}

export default function App() {

  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);

  const fetchSessions = async () => {
    try {
      if (window.pywebview?.api?.get_sessions) {
        const sessList = await window.pywebview.api.get_sessions();
        setSessions(sessList);
        return sessList;
      }
    } catch (err) {
      console.error(err);
    }
    return [];
  };

  useEffect(() => {
    const init = async () => {
      const sessList = await fetchSessions();
      if (sessList.length > 0) {
        handleSelectSession(sessList[0].id);
      } else {
        handleNewSession();
      }
    };
    
    // Check if pywebview is already loaded, otherwise poll
    let attempts = 0;
    const checkApi = setInterval(() => {
      if (window.pywebview?.api) {
        clearInterval(checkApi);
        init();
      } else if (attempts > 10) {
        clearInterval(checkApi);
        // Fallback for mock environment
        console.warn("pywebview api not detected after 2s.");
      }
      attempts++;
    }, 200);
    
    return () => clearInterval(checkApi);
  }, []);

  const handleSelectSession = async (id: string) => {
    if (!window.pywebview?.api) return;
    setIsResponding(true);
    try {
      const sess = await window.pywebview.api.load_session(id);
      if (sess) {
        setActiveSessionId(id);
        const uiMsgs: Message[] = sess.messages.map((m: any, idx: number) => ({
          id: `${id}-${idx}`,
          role: m.role,
          text: m.content || m.text || '',
          timestamp: sess.timestamp
        }));
        setMessages(uiMsgs.length > 0 ? uiMsgs : [{
          id: 'welcome', role: 'assistant', text: 'Neural Link established. Session loaded.', timestamp: Date.now()
        }]);
      }
    } catch(err) { console.error(err); } finally {
      setIsResponding(false);
    }
  };

  const handleNewSession = async () => {
    if (!window.pywebview?.api) return;
    const sess = await window.pywebview.api.new_session();
    setActiveSessionId(sess.id);
    setMessages([{
      id: 'welcome', role: 'assistant', text: 'Neural Link established. System initialized and online.', timestamp: Date.now()
    }]);
    await fetchSessions();
  };
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 'welcome',
      role: 'assistant',
      text: 'Neural Link established. System initialized and online. How can I assist you with your project today?',
      timestamp: Date.now()
    }
  ]);
  const [inputText, setInputText] = useState('');
  const [isResponding, setIsResponding] = useState(false);
  const [currentReasoning, setCurrentReasoning] = useState<ReasoningStep[]>([]);
  const [currentScreenshot, setCurrentScreenshot] = useState<string | null>(null);
  
  // Dialog / Modal state for Plan Rejection
  const [showRejectModal, setShowRejectModal] = useState(false);
  const [rejectFeedback, setRejectFeedback] = useState('');

  // Refs to avoid stale closures in event listeners
  const reasoningRef = useRef<ReasoningStep[]>([]);
  reasoningRef.current = currentReasoning;

  const screenshotRef = useRef<string | null>(null);
  screenshotRef.current = currentScreenshot;

  const chatEndRef = useRef<HTMLDivElement>(null);
  const reasoningEndRef = useRef<HTMLDivElement>(null);

  // Auto scroll chat and reasoning
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isResponding]);

  useEffect(() => {
    reasoningEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [currentReasoning]);

  useEffect(() => {
    // Event listener: Agent starts executing
    const handleStart = () => {
      setCurrentReasoning([]);
      setCurrentScreenshot(null);
      setIsResponding(true);
    };

    // Event listener: Real-time reasoning logs
    const handleReasoning = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      setCurrentReasoning(prev => {
        // Prevent duplicate logs next to each other
        if (prev.length > 0 && prev[prev.length - 1].text === detail.text) {
          return prev;
        }
        return [...prev, {
          text: detail.text,
          isTool: detail.isTool,
          id: Math.random().toString()
        }];
      });
    };

    // Event listener: Agent captures screenshot
    const handleScreenshot = (e: Event) => {
      const base64Data = (e as CustomEvent).detail;
      setCurrentScreenshot(`data:image/png;base64,${base64Data}`);
    };

    // Event listener: Final agent answer completes
    const handleFinal = (e: Event) => {
      const text = (e as CustomEvent).detail;
      setMessages(prev => [
        ...prev,
        {
          id: Math.random().toString(),
          role: 'assistant',
          text: text,
          reasoning: [...reasoningRef.current],
          screenshot: screenshotRef.current || undefined,
          timestamp: Date.now()
        }
      ]);
      setIsResponding(false);
      fetchSessions();
    };

    window.addEventListener('agent-start', handleStart);
    window.addEventListener('agent-reasoning', handleReasoning);
    window.addEventListener('agent-screenshot', handleScreenshot);
    window.addEventListener('agent-final', handleFinal);

    return () => {
      window.removeEventListener('agent-start', handleStart);
      window.removeEventListener('agent-reasoning', handleReasoning);
      window.removeEventListener('agent-screenshot', handleScreenshot);
      window.removeEventListener('agent-final', handleFinal);
    };
  }, []);

  const handleSendMessage = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!inputText.trim() || isResponding) return;

    const userText = inputText;
    setInputText('');
    
    // Add user message to UI
    setMessages(prev => [
      ...prev,
      {
        id: Math.random().toString(),
        role: 'user',
        text: userText,
        timestamp: Date.now()
      }
    ]);
    setIsResponding(true);

    try {
      if (window.pywebview?.api?.send_message) {
        await window.pywebview.api.send_message(userText);
      } else {
        // Fallback for browser-only preview testing
        console.warn("pywebview api not detected. Running browser-only mock response.");
        setTimeout(() => {
          window.dispatchEvent(new CustomEvent('agent-start'));
          setTimeout(() => {
            window.dispatchEvent(new CustomEvent('agent-reasoning', { detail: { text: "Locating workspace directories...", isTool: true } }));
            setTimeout(() => {
              window.dispatchEvent(new CustomEvent('agent-reasoning', { detail: { text: "Proposed plan ready.", isTool: false } }));
              window.dispatchEvent(new CustomEvent('agent-final', { detail: "<plan>\nVerify system environment\n<tasks>\n- [ ] Step 1\n- [/] Step 2\n- [x] Step 3\n</tasks>\n</plan>\nPlan created. Please review." }));
            }, 1000);
          }, 1000);
        }, 500);
      }
    } catch (err) {
      console.error("Failed to send message to backend:", err);
      setIsResponding(false);
    }
  };

  const handleApprovePlan = async () => {
    setIsResponding(true);
    try {
      if (window.pywebview?.api?.approve_plan) {
        await window.pywebview.api.approve_plan();
      } else {
        console.warn("pywebview api not detected. Mocking plan approval.");
        setTimeout(() => {
          window.dispatchEvent(new CustomEvent('agent-start'));
          setTimeout(() => {
            window.dispatchEvent(new CustomEvent('agent-reasoning', { detail: { text: "Executing task modifications...", isTool: true } }));
            window.dispatchEvent(new CustomEvent('agent-final', { detail: "All plan tasks completed successfully!" }));
          }, 1000);
        }, 500);
      }
    } catch (err) {
      console.error("Failed to approve plan:", err);
      setIsResponding(false);
    }
  };

  const handleRejectPlan = async () => {
    if (!rejectFeedback.trim()) return;
    const feedback = rejectFeedback;
    setShowRejectModal(false);
    setRejectFeedback('');
    setIsResponding(true);

    try {
      if (window.pywebview?.api?.reject_plan) {
        await window.pywebview.api.reject_plan(feedback);
      } else {
        console.warn("pywebview api not detected. Mocking plan rejection.");
        setTimeout(() => {
          window.dispatchEvent(new CustomEvent('agent-start'));
          setTimeout(() => {
            window.dispatchEvent(new CustomEvent('agent-reasoning', { detail: { text: "Revising plan based on feedback...", isTool: false } }));
            window.dispatchEvent(new CustomEvent('agent-final', { detail: "Plan revised. Ready for review." }));
          }, 1000);
        }, 500);
      }
    } catch (err) {
      console.error("Failed to reject plan:", err);
      setIsResponding(false);
    }
  };

  // Helper to parse plan blocks and render checklist
  const renderMessageContent = (content: string) => {
    const planMatch = content.match(/<plan>([\s\S]*?)<\/plan>/);
    if (!planMatch) {
      return <MessageMarkdown content={content} />;
    }

    const startIndex = content.indexOf('<plan>');
    const endIndex = content.indexOf('</plan>') + 7;
    const preText = content.substring(0, startIndex);
    const postText = content.substring(endIndex);

    const planText = planMatch[1];
    const tasksMatch = planText.match(/<tasks>([\s\S]*?)<\/tasks>/);
    let description = planText;
    let tasks: Array<{ text: string, status: 'todo' | 'doing' | 'done' }> = [];

    if (tasksMatch) {
      description = planText.replace(/<tasks>[\s\S]*?<\/tasks>/, '');
      const lines = tasksMatch[1].split('\n');
      lines.forEach(line => {
        const trimmed = line.trim();
        if (trimmed.startsWith('- [ ]')) {
          tasks.push({ text: trimmed.substring(5).trim(), status: 'todo' });
        } else if (trimmed.startsWith('- [/]')) {
          tasks.push({ text: trimmed.substring(5).trim(), status: 'doing' });
        } else if (trimmed.startsWith('- [x]') || trimmed.startsWith('- [X]')) {
          tasks.push({ text: trimmed.substring(5).trim(), status: 'done' });
        }
      });
    }

    return (
      <div className="space-y-3">
        {preText && <MessageMarkdown content={preText} />}
        <div className="border border-cyan-500/30 bg-cyan-950/10 rounded-lg p-4 space-y-3 shadow-[0_0_15px_rgba(6,182,212,0.05)] select-text">
          <div className="flex items-center gap-2 text-cyan-400 font-semibold border-b border-cyan-500/20 pb-2">
            <span className="material-symbols-outlined text-base">assignment</span>
            <span className="tracking-wider uppercase text-xs font-mono-custom">PROPOSED PLAN</span>
          </div>
          <div className="text-sm text-slate-300 font-sans leading-relaxed">
            <MessageMarkdown content={description.trim()} />
          </div>
          {tasks.length > 0 && (
            <div className="space-y-2 pt-2 border-t border-cyan-500/10">
              <span className="text-[10px] font-mono-custom text-slate-400 uppercase tracking-widest block mb-1">Checklist:</span>
              <div className="space-y-1.5">
                {tasks.map((task, idx) => (
                  <div key={idx} className="flex items-start gap-2.5 text-xs font-mono-custom">
                    {task.status === 'done' && (
                      <span className="material-symbols-outlined text-emerald-400 text-base select-none">check_box</span>
                    )}
                    {task.status === 'doing' && (
                      <span className="material-symbols-outlined text-cyan-400 text-base select-none animate-spin">progress_activity</span>
                    )}
                    {task.status === 'todo' && (
                      <span className="material-symbols-outlined text-slate-600 text-base select-none">check_box_outline_blank</span>
                    )}
                    <span className={`leading-normal ${task.status === 'done' ? 'line-through text-slate-500' : 'text-slate-300'}`}>
                      {task.text}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
        {postText && <MessageMarkdown content={postText} />}
      </div>
    );
  };

  // Check if the last assistant response contains a pending plan
  const lastMessage = messages[messages.length - 1];
  const hasPendingPlan = 
    lastMessage && 
    lastMessage.role === 'assistant' && 
    lastMessage.text.includes('<plan>') && 
    !isResponding;

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-[#0d0d12] text-[#e2e8f0]">
      
      {/* Top Banner Header */}
      <header className="flex items-center justify-between px-6 py-4 border-b border-[#232333] bg-[#101017]">
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center w-8 h-8 rounded border border-cyan-500/30 bg-cyan-950/20 text-cyan-400">
            <span className="material-symbols-outlined text-base">leak_add</span>
          </div>
          <div>
            <h1 className="text-sm font-semibold tracking-wider font-mono-custom text-cyan-400">NEURAL_LINK_v4.2</h1>
            <p className="text-[10px] text-slate-500 font-mono-custom">LOCAL_AGENT_SANDBOX: ACTIVE</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-cyan-500/20 bg-cyan-950/15 text-[10px] font-mono-custom text-cyan-400">
            <span className={`w-1.5 h-1.5 rounded-full bg-cyan-400 ${isResponding ? 'animate-ping' : ''}`}></span>
            {isResponding ? 'EXECUTING_NODE' : 'STANDBY'}
          </div>
        </div>
      </header>

      {/* Main Container Area */}
      <div className="flex flex-1 overflow-hidden">
        
        <Sidebar sessions={sessions} activeSessionId={activeSessionId} onSelectSession={handleSelectSession} onNewSession={handleNewSession} />

        {/* Left Section: Conversational Stream */}
        <section className="flex flex-col flex-1 border-r border-[#232333] bg-[#0e0e14] relative overflow-hidden">
          {/* Active Process Indicator */}
          {isResponding && (
            <div className="absolute top-0 left-0 right-0 h-[3px] bg-cyan-900/30 overflow-hidden z-50">
              <div className="h-full w-full bg-cyan-400 animate-progress shadow-[0_0_12px_rgba(6,182,212,1)]"></div>
            </div>
          )}
          
          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            {messages.map((msg) => (
              <div 
                key={msg.id} 
                className={`flex flex-col max-w-[85%] ${msg.role === 'user' ? 'ml-auto items-end' : 'mr-auto items-start'}`}
              >
                {/* Message Meta */}
                <span className="text-[9px] font-mono-custom text-slate-500 mb-1 px-1">
                  {msg.role === 'user' ? 'USER_PROMPT' : 'AGENT_CORE'} @ {new Date(msg.timestamp).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit', second:'2-digit'})}
                </span>

                {/* Message Bubble */}
                <div 
                  className={`rounded-lg px-4 py-3.5 border text-sm font-sans leading-relaxed shadow-sm select-text ${
                    msg.role === 'user' 
                      ? 'bg-[#181825] border-cyan-500/15 text-slate-200' 
                      : 'bg-[#13131c] border-[#232333] text-slate-300'
                  }`}
                >
                  {msg.role === 'assistant' ? renderMessageContent(msg.text) : msg.text}

                  {/* Execution Log summary embedded inside completed turn */}
                  {msg.role === 'assistant' && ((msg.reasoning && msg.reasoning.length > 0) || msg.screenshot) && (
                    <details className="mt-3 pt-3 border-t border-[#232333] text-xs font-mono-custom group">
                      <summary className="flex items-center gap-1.5 text-slate-500 hover:text-cyan-400 cursor-pointer select-none">
                        <span className="material-symbols-outlined text-sm transition-transform group-open:rotate-90">chevron_right</span>
                        View Execution Context ({msg.reasoning?.length || 0} steps)
                      </summary>
                      <div className="mt-2.5 pl-3 py-2 border-l border-cyan-500/20 space-y-2 bg-[#0c0c12]/50 rounded">
                        {msg.reasoning?.map((step, idx) => (
                          <div key={step.id} className={`text-[11px] ${step.isTool ? 'text-cyan-400/90' : 'text-slate-400'}`}>
                            <span className="text-slate-600 mr-1.5">[{idx + 1}]</span>
                            {step.text}
                          </div>
                        ))}
                        {msg.screenshot && (
                          <div className="mt-2">
                            <span className="text-[10px] text-slate-500 block mb-1">Visual Capture:</span>
                            <img 
                              src={msg.screenshot} 
                              alt="Step Capture" 
                              className="max-h-40 rounded border border-[#232333] hover:max-h-none transition-all duration-300 cursor-zoom-in"
                            />
                          </div>
                        )}
                      </div>
                    </details>
                  )}
                </div>
              </div>
            ))}

            {/* Live streaming status inside bubble */}
            {isResponding && currentReasoning.length === 0 && (
              <div className="flex flex-col max-w-[80%] mr-auto items-start">
                <span className="text-[9px] font-mono-custom text-slate-500 mb-1 px-1">AGENT_CORE @ THINKING...</span>
                <div className="rounded-lg px-4 py-3 bg-[#13131c] border border-cyan-500/20 text-slate-400 text-sm flex items-center gap-2">
                  <span className="material-symbols-outlined animate-spin text-cyan-400 text-sm">progress_activity</span>
                  Establishing connection and fetching context...
                </div>
              </div>
            )}

            <div ref={chatEndRef} />
          </div>

          <ContextUsageBar />

          {/* Action Footer: Approvability & Inputs */}
          <footer className="p-4 bg-[#101017]">
            {hasPendingPlan ? (
              <div className="flex flex-col p-4 border border-cyan-500/30 bg-cyan-950/10 rounded-lg space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="material-symbols-outlined text-cyan-400 text-base animate-pulse">lock</span>
                    <span className="text-xs font-mono-custom text-slate-300 font-semibold uppercase tracking-wider">
                      WAITING FOR APPROVAL BEFORE RUNNING SCRIPTS
                    </span>
                  </div>
                </div>
                <div className="flex gap-3">
                  <button 
                    onClick={handleApprovePlan}
                    className="flex-1 flex items-center justify-center gap-1.5 py-2 px-4 rounded font-mono-custom text-xs font-semibold bg-emerald-500/20 hover:bg-emerald-500/35 border border-emerald-500/40 text-emerald-300 hover:text-emerald-200 transition-colors"
                  >
                    <span className="material-symbols-outlined text-sm">done</span>
                    APPROVE PLAN
                  </button>
                  <button 
                    onClick={() => setShowRejectModal(true)}
                    className="flex-1 flex items-center justify-center gap-1.5 py-2 px-4 rounded font-mono-custom text-xs font-semibold bg-rose-500/20 hover:bg-rose-500/35 border border-rose-500/40 text-rose-300 hover:text-rose-200 transition-colors"
                  >
                    <span className="material-symbols-outlined text-sm">close</span>
                    REJECT WITH FEEDBACK
                  </button>
                </div>
              </div>
            ) : (
              <form onSubmit={handleSendMessage} className="flex gap-2">
                <input 
                  type="text"
                  value={inputText}
                  onChange={(e) => setInputText(e.target.value)}
                  disabled={isResponding}
                  placeholder={isResponding ? "Agent is working..." : "Provide instructions, scripts, or ask a question..."}
                  className="flex-1 min-h-[44px] px-4 py-2 bg-[#13131c] border border-[#232333] focus:border-cyan-500/40 rounded text-slate-200 text-sm font-sans focus:outline-none transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                />
                <button 
                  type="submit"
                  disabled={!inputText.trim() || isResponding}
                  className="flex items-center justify-center px-5 rounded border border-cyan-500/30 bg-cyan-950/20 text-cyan-400 hover:bg-cyan-500/10 hover:text-cyan-300 transition-all font-mono-custom text-xs font-semibold tracking-wider disabled:opacity-40 disabled:hover:bg-transparent disabled:cursor-not-allowed"
                >
                  TRANSMIT
                </button>
              </form>
            )}
          </footer>
        </section>

        {/* Right Section: Real-time Telemetry Monitor */}
        <section className="w-[40%] flex flex-col bg-[#0b0b10]">
          <SubagentTracker steps={currentReasoning} isResponding={isResponding} screenshot={currentScreenshot} />
        </section>
      </div>

      {/* Reject Plan Dialog Modal */}
      {showRejectModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="w-full max-w-md bg-[#13131c] border border-[#ff3b30]/30 rounded-lg p-5 space-y-4 shadow-xl">
            <div className="flex items-center gap-2 text-rose-400 font-semibold border-b border-[#232333] pb-2">
              <span className="material-symbols-outlined">assignment_return</span>
              <span className="font-mono-custom text-xs uppercase tracking-wider">Reject Plan & Provide Feedback</span>
            </div>
            
            <div className="space-y-1.5">
              <label className="text-[10px] font-mono-custom text-slate-400 uppercase tracking-wider block">
                Provide instructions or why this plan was rejected:
              </label>
              <textarea 
                value={rejectFeedback}
                onChange={(e) => setRejectFeedback(e.target.value)}
                placeholder="Describe what needs to be changed in the plan (e.g. use a different library, avoid this directory, check this file...)"
                rows={4}
                className="w-full px-3 py-2 bg-[#0c0c12] border border-[#232333] focus:border-rose-500/40 focus:outline-none rounded text-slate-200 text-sm font-sans resize-none"
              />
            </div>

            <div className="flex gap-2 justify-end text-xs font-mono-custom">
              <button 
                onClick={() => {
                  setShowRejectModal(false);
                  setRejectFeedback('');
                }}
                className="py-1.5 px-3.5 rounded border border-[#232333] text-slate-400 hover:text-slate-300 hover:bg-[#1c1c28]"
              >
                CANCEL
              </button>
              <button 
                onClick={handleRejectPlan}
                disabled={!rejectFeedback.trim()}
                className="py-1.5 px-4 rounded border border-[#ff3b30]/30 bg-[#ff3b30]/15 hover:bg-[#ff3b30]/25 text-rose-300 hover:text-rose-200 disabled:opacity-40 disabled:hover:bg-[#ff3b30]/15 disabled:cursor-not-allowed"
              >
                SUBMIT FEEDBACK
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
