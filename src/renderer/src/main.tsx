import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'
import './index.css'

// Set up global window event dispatchers for pywebview to communicate with React
window.startAgentResponse = () => {
  window.dispatchEvent(new CustomEvent('agent-start'));
};

window.appendReasoning = (text: string, isTool: boolean) => {
  window.dispatchEvent(new CustomEvent('agent-reasoning', { detail: { text, isTool } }));
};

window.appendScreenshot = (base64Data: string) => {
  window.dispatchEvent(new CustomEvent('agent-screenshot', { detail: base64Data }));
};

window.appendFinalResponse = (text: string) => {
  window.dispatchEvent(new CustomEvent('agent-final', { detail: text }));
};

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
