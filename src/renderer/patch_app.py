import os
import re

app_file = r"C:\Projects\Agent_project\my-ollama-project\src\renderer\src\App.tsx"
with open(app_file, "r", encoding="utf-8") as f:
    content = f.read()

# Replace Sidebar import
content = content.replace("import { Sidebar } from './components/Sidebar';", "import { Sidebar, SessionMeta } from './components/Sidebar';")

# Add state and functions inside App()
state_code = """
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
          text: m.text,
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
"""

# Insert inside export default function App() {
content = content.replace("export default function App() {\n", "export default function App() {\n" + state_code)

# Add fetchSessions() in handleFinal
content = content.replace("setIsResponding(false);\n    };", "setIsResponding(false);\n      fetchSessions();\n    };")

# Replace <Sidebar /> with <Sidebar sessions={sessions} activeSessionId={activeSessionId} onSelectSession={handleSelectSession} onNewSession={handleNewSession} />
content = content.replace("<Sidebar />", "<Sidebar sessions={sessions} activeSessionId={activeSessionId} onSelectSession={handleSelectSession} onNewSession={handleNewSession} />")

with open(app_file, "w", encoding="utf-8") as f:
    f.write(content)

print("Patched App.tsx successfully.")
