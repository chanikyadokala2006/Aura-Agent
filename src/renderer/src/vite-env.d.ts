/// <reference types="vite/client" />

interface Window {
  pywebview?: {
    api: {
      send_message: (text: string) => Promise<void>;
      approve_plan: () => Promise<void>;
      reject_plan: (feedback: string) => Promise<void>;
      get_sessions: () => Promise<any[]>;
      new_session: () => Promise<any>;
      load_session: (id: string) => Promise<any>;
    };
  };
  startAgentResponse?: () => void;
  appendReasoning?: (text: string, isTool: boolean) => void;
  appendScreenshot?: (base64Data: string) => void;
  appendFinalResponse?: (text: string) => void;
}
