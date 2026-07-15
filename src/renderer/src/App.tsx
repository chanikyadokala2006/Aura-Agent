import React, { useState, useEffect, useRef } from 'react';
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
  timestamp: number;
}

export default function App() {
  const [sessions, setSessions] = useState<any[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputText, setInputText] = useState('');
  const [isResponding, setIsResponding] = useState(false);
  const [currentReasoning, setCurrentReasoning] = useState<ReasoningStep[]>([]);
  
  const [activeTab, setActiveTab] = useState('Overview');
  const [artifactContent, setArtifactContent] = useState('');

  const chatEndRef = useRef<HTMLDivElement>(null);
  const reasoningRef = useRef<ReasoningStep[]>([]);
  reasoningRef.current = currentReasoning;

  const fetchSessions = async () => {
    try {
      if ((window as any).pywebview?.api?.get_sessions) {
        const sessList = await (window as any).pywebview.api.get_sessions();
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
    
    let attempts = 0;
    const checkApi = setInterval(() => {
      if ((window as any).pywebview?.api) {
        clearInterval(checkApi);
        init();
      } else if (attempts > 10) {
        clearInterval(checkApi);
      }
      attempts++;
    }, 200);
    
    return () => clearInterval(checkApi);
  }, []);

  const handleSelectSession = async (id: string) => {
    if (!(window as any).pywebview?.api) return;
    setIsResponding(true);
    try {
      const sess = await (window as any).pywebview.api.load_session(id);
      if (sess) {
        setActiveSessionId(id);
        const uiMsgs: Message[] = sess.messages.map((m: any, idx: number) => ({
          id: `${id}-${idx}`,
          role: m.role,
          text: m.content || m.text || '',
          timestamp: sess.timestamp
        }));
        setMessages(uiMsgs.length > 0 ? uiMsgs : [{
          id: 'welcome', role: 'assistant', text: 'Neural Link established.', timestamp: Date.now()
        }]);
      }
    } catch(err) { console.error(err); } finally {
      setIsResponding(false);
    }
  };

  const handleNewSession = async () => {
    if (!(window as any).pywebview?.api) return;
    const sess = await (window as any).pywebview.api.new_session();
    setActiveSessionId(sess.id);
    setMessages([{
      id: 'welcome', role: 'assistant', text: 'System initialized and online.', timestamp: Date.now()
    }]);
    await fetchSessions();
  };

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isResponding, currentReasoning]);

  useEffect(() => {
    const handleStart = () => {
      setCurrentReasoning([]);
      setIsResponding(true);
    };

    const handleReasoning = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      setCurrentReasoning(prev => {
        if (prev.length > 0 && prev[prev.length - 1].text === detail.text) return prev;
        return [...prev, { text: detail.text, isTool: detail.isTool, id: Math.random().toString() }];
      });
    };

    const handleFinal = (e: Event) => {
      const text = (e as CustomEvent).detail;
      setMessages(prev => [...prev, {
        id: Math.random().toString(),
        role: 'assistant',
        text: text,
        reasoning: [...reasoningRef.current],
        timestamp: Date.now()
      }]);
      setIsResponding(false);
      fetchSessions();
      
      if (text.includes(".md") && (window as any).pywebview?.api?.get_artifact) {
         const matches = text.match(/([a-zA-Z0-9_-]+\.md)/);
         if (matches) {
            (window as any).pywebview.api.get_artifact(matches[1]).then((res: string) => {
                setArtifactContent(res);
                setActiveTab("Solutions");
            });
         }
      }
    };

    window.addEventListener('agent-start', handleStart);
    window.addEventListener('agent-reasoning', handleReasoning);
    window.addEventListener('agent-final', handleFinal);

    return () => {
      window.removeEventListener('agent-start', handleStart);
      window.removeEventListener('agent-reasoning', handleReasoning);
      window.removeEventListener('agent-final', handleFinal);
    };
  }, []);

  const handleSendMessage = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!inputText.trim() || isResponding) return;

    const userText = inputText;
    setInputText('');
    
    setMessages(prev => [...prev, {
      id: Math.random().toString(),
      role: 'user',
      text: userText,
      timestamp: Date.now()
    }]);
    setIsResponding(true);

    try {
      if ((window as any).pywebview?.api?.send_message) {
        await (window as any).pywebview.api.send_message(userText);
      }
    } catch (err) {
      console.error(err);
      setIsResponding(false);
    }
  };

  const tabs = ['Overview', 'Review', 'Analysis Results', 'Implementation Plan', 'Solutions'];

  return (
    <div className="flex h-screen w-screen bg-deep-base text-on-surface font-body-sm overflow-hidden">
      
      {/* Left Pane: Navigation & History */}
      <aside className="pane w-[280px] flex-shrink-0 flex flex-col justify-between">
        {/* Header & CTA */}
        <div className="p-4 border-b border-border-subtle">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-8 h-8 rounded bg-surface-elevated border border-border-subtle flex items-center justify-center text-primary">
              <span className="material-symbols-outlined text-[20px]">api</span>
            </div>
            <div>
              <h1 className="font-headline-sm text-headline-sm font-bold text-primary">AI Lab</h1>
              <p className="font-body-sm text-body-sm text-on-surface-variant">Technical Workspace</p>
            </div>
          </div>
          <button onClick={handleNewSession} className="w-full flex items-center justify-center gap-2 bg-primary-container hover:bg-inverse-primary text-white font-label-md text-label-md py-2 px-4 rounded transition-colors duration-200">
            <span className="material-symbols-outlined text-[18px]">add</span>
            New Conversation
          </button>
        </div>
        
        {/* History List */}
        <div className="flex-1 overflow-y-auto py-2">
          <div className="px-4 py-2 font-label-md text-label-md text-on-surface-variant uppercase tracking-wider mb-1">
            Recent Sessions
          </div>
          <ul className="space-y-[1px]">
            {sessions.map(s => (
              <li 
                key={s.id}
                onClick={() => handleSelectSession(s.id)}
                className={`relative cursor-pointer group transition-colors duration-200 ${s.id === activeSessionId ? 'bg-surface-overlay text-white' : 'text-on-surface-variant hover:bg-surface-overlay'}`}
              >
                {s.id === activeSessionId && <div className="absolute left-0 top-0 bottom-0 w-[2px] bg-primary-container"></div>}
                <div className="flex items-center gap-3 px-4 py-2 pl-5">
                  <div className={`w-2 h-2 rounded-full transition-colors ${s.id === activeSessionId ? 'bg-primary-container' : 'bg-border-subtle group-hover:bg-outline-variant'}`}></div>
                  <span className="font-body-md text-body-md truncate">{s.title || "New Session"}</span>
                </div>
              </li>
            ))}
          </ul>
        </div>
        
        {/* Footer / Settings */}
        <div className="p-2 border-t border-border-subtle">
        </div>
      </aside>

      {/* Center Pane: Chat Canvas */}
      <main className="pane flex-1 flex flex-col bg-deep-base">
        {/* Chat Area */}
        <div className="flex-1 overflow-y-auto p-6 flex flex-col gap-6">
          {messages.map(msg => (
            <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[85%] ${msg.role === 'user' ? 'bg-surface-elevated border border-border-subtle rounded-lg rounded-tr-none p-4' : 'flex flex-col gap-2'}`}>
                
                {msg.role === 'assistant' && msg.reasoning && msg.reasoning.length > 0 && (
                  <div className="flex items-center gap-2 text-on-surface-variant font-body-sm text-body-sm">
                    <span className="material-symbols-outlined text-[14px] text-primary-container">autorenew</span>
                    <span>Worked for {msg.reasoning.length} steps</span>
                    <span className="material-symbols-outlined text-[14px]">chevron_right</span>
                  </div>
                )}
                
                <div className={`${msg.role === 'assistant' ? 'bg-transparent p-1' : ''}`}>
                  {msg.role === 'assistant' ? (
                     <div className="font-body-md text-body-md text-on-surface mb-4 leading-relaxed prose prose-invert max-w-none">
                       <MessageMarkdown content={msg.text} />
                     </div>
                  ) : (
                     <p className="font-body-md text-body-md text-on-surface">{msg.text}</p>
                  )}
                </div>
                
              </div>
            </div>
          ))}

          {/* Loading Indicator */}
          {isResponding && (
            <div className="flex justify-start">
              <div className="max-w-[85%] flex flex-col gap-2">
                <div className="flex items-center gap-2 text-primary-container font-body-sm text-body-sm">
                  <span className="material-symbols-outlined text-[14px] animate-spin">progress_activity</span>
                  <span>{currentReasoning.length > 0 ? currentReasoning[currentReasoning.length - 1].text : "Generating response..."}</span>
                </div>
              </div>
            </div>
          )}
          
          <div ref={chatEndRef} className="h-4"></div>
        </div>

        {/* Input Area */}
        <div className="p-4 border-t border-border-subtle bg-deep-base">
          <form onSubmit={handleSendMessage} className="flex flex-col gap-2">
            <div className="flex items-center bg-surface-elevated border border-border-subtle rounded-lg p-2 focus-within:border-primary-container transition-colors duration-200">
              <input 
                type="text" 
                value={inputText}
                onChange={e => setInputText(e.target.value)}
                disabled={isResponding}
                className="flex-1 bg-transparent border-none text-white font-body-md focus:ring-0 focus:outline-none placeholder:text-on-surface-variant px-2" 
                placeholder="Message or command..." 
              />
              <div className="flex items-center gap-2 pr-1">
                <button type="submit" disabled={isResponding || !inputText.trim()} className="p-2 bg-primary-container hover:bg-inverse-primary disabled:opacity-50 text-white rounded-md transition-colors flex items-center justify-center">
                  <span className="material-symbols-outlined text-[18px]">arrow_upward</span>
                </button>
              </div>
            </div>
            <div className="text-center mt-1 text-on-surface-variant font-body-sm text-body-sm opacity-50">
                Shift + Enter to add a new line
            </div>
          </form>
        </div>
      </main>

      {/* Right Pane: Artifacts & Inspector */}
      <aside className="pane w-[500px] flex-shrink-0 bg-surface-elevated">
        {/* Top App Bar / Tabs */}
        <div className="flex justify-between items-center px-4 w-full h-12 sticky top-0 z-50 bg-surface/80 backdrop-blur-sm border-b border-border-subtle">
          <div className="flex items-center gap-4 h-full">
            {tabs.map(tab => (
              <div 
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`h-full flex items-center cursor-pointer transition-colors duration-200 ${activeTab === tab ? 'text-primary border-b-2 border-primary pt-[2px]' : 'text-on-surface-variant hover:text-on-surface'}`}
              >
                <span className="font-label-md text-label-md uppercase tracking-wider">{tab}</span>
              </div>
            ))}
          </div>
          <div className="flex items-center gap-2">
          </div>
        </div>

        {/* Editor/Viewer Content */}
        <div className="flex-1 flex flex-col overflow-hidden bg-deep-base p-4">
          <div className="flex justify-between items-center mb-3">
            <h2 className="font-title-md text-title-md font-medium text-white">{activeTab === 'Solutions' && artifactContent ? 'generated_artifact.md' : 'Inspector'}</h2>
          </div>
          
          <div className="flex-1 bg-deep-base border border-border-subtle rounded overflow-y-auto p-4 custom-scrollbar font-code-md text-code-md text-on-surface prose prose-invert max-w-none">
            {artifactContent ? (
               <MessageMarkdown content={artifactContent} />
            ) : (
               <div className="text-on-surface-variant text-center mt-20 font-body-md">No artifact selected or generated.</div>
            )}
          </div>
        </div>
      </aside>
    </div>
  );
}
