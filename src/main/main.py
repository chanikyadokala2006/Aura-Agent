import os
import sys
import json
import uuid
import time
import webview

# Add the project root to sys.path so we can import from agent
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.append(project_root)

from agent.MyAgent import setup_agent, retrieve_relevant_memories
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage

DB_PATH = os.path.join(project_root, "chats.json")

class SessionManager:
    def __init__(self):
        self.sessions = []
        self.load()

    def load(self):
        if os.path.exists(DB_PATH):
            try:
                with open(DB_PATH, "r", encoding="utf-8") as f:
                    self.sessions = json.load(f)
            except Exception as e:
                print(f"Failed to load sessions: {e}")
                self.sessions = []
        else:
            self.sessions = []

    def save(self):
        try:
            with open(DB_PATH, "w", encoding="utf-8") as f:
                json.dump(self.sessions, f, indent=2)
        except Exception as e:
            print(f"Failed to save sessions: {e}")

    def get_sessions(self):
        # Return basic info without huge message arrays
        return [{"id": s["id"], "title": s.get("title", "New Session"), "timestamp": s.get("timestamp", 0)} for s in self.sessions]

    def get_session(self, session_id):
        for s in self.sessions:
            if s["id"] == session_id:
                return s
        return None

    def create_session(self):
        s = {
            "id": str(uuid.uuid4()),
            "title": "New Session",
            "timestamp": int(time.time() * 1000),
            "messages": []
        }
        self.sessions.insert(0, s)
        self.save()
        return s

    def serialize_message(self, m):
        base = {"timestamp": int(time.time() * 1000)}
        if hasattr(m, "additional_kwargs") and "timestamp" in m.additional_kwargs:
            base["timestamp"] = m.additional_kwargs["timestamp"]
        else:
            if not hasattr(m, "additional_kwargs"):
                m.additional_kwargs = {}
            if "timestamp" not in m.additional_kwargs:
                m.additional_kwargs["timestamp"] = base["timestamp"]
            else:
                base["timestamp"] = m.additional_kwargs["timestamp"]

        if isinstance(m, HumanMessage):
            base.update({"role": "user", "content": str(m.content)})
        elif isinstance(m, SystemMessage):
            base.update({"role": "system", "content": str(m.content)})
        elif isinstance(m, AIMessage):
            base.update({"role": "assistant"})
            text = ""
            if isinstance(m.content, list):
                text_parts = [p.get("text", "") for p in m.content if isinstance(p, dict)]
                text = "".join(text_parts)
            else:
                text = str(m.content)
            base["content"] = text
            if hasattr(m, "tool_calls") and m.tool_calls:
                base["tool_calls"] = m.tool_calls
        elif isinstance(m, ToolMessage):
            base.update({
                "role": "tool",
                "name": m.name,
                "tool_call_id": m.tool_call_id,
                "content": str(m.content)
            })
        else:
            base.update({"role": "unknown", "content": str(m)})
            
        return base

    def update_session(self, session_id, langgraph_messages):
        for s in self.sessions:
            if s["id"] == session_id:
                serialized = [self.serialize_message(m) for m in langgraph_messages]
                
                # Title generation
                if len(serialized) > 0 and s["title"] == "New Session":
                    for msg in serialized:
                        if msg["role"] == "user":
                            s["title"] = msg["content"][:30] + "..."
                            break
                    
                s["messages"] = serialized
                self.save()
                return s
        return None

_global_agent = setup_agent()
_global_messages = []
_global_session_manager = SessionManager()
_global_active_session_id = None

class Api:
    def get_sessions(self):
        return _global_session_manager.get_sessions()

    def new_session(self):
        global _global_messages, _global_active_session_id
        _global_messages = []
        sess = _global_session_manager.create_session()
        _global_active_session_id = sess["id"]
        return sess

    def load_session(self, session_id):
        global _global_messages, _global_active_session_id
        sess = _global_session_manager.get_session(session_id)
        if not sess:
            return None
        _global_active_session_id = session_id
        
        # Reconstruct LangGraph history
        _global_messages = []
        for m in sess["messages"]:
            role = m.get("role")
            content = m.get("content", "")
            additional_kwargs = {"timestamp": m.get("timestamp", int(time.time() * 1000))}
            
            if role == "user":
                _global_messages.append(HumanMessage(content=content, additional_kwargs=additional_kwargs))
            elif role == "system":
                _global_messages.append(SystemMessage(content=content, additional_kwargs=additional_kwargs))
            elif role == "assistant":
                tool_calls = m.get("tool_calls", [])
                _global_messages.append(AIMessage(content=content, tool_calls=tool_calls, additional_kwargs=additional_kwargs))
            elif role == "tool":
                _global_messages.append(ToolMessage(content=content, name=m.get("name", ""), tool_call_id=m.get("tool_call_id", ""), additional_kwargs=additional_kwargs))
        
        return sess

    def approve_plan(self):
        try:
            from agent.MyAgent import tool_batch_approval_event, tool_batch_approval_result, tool_batch_waiting
            if tool_batch_waiting:
                print("Tool batch plan approved by user.")
                tool_batch_approval_result["approved"] = True
                tool_batch_approval_event.set()
                return
        except Exception as e:
            pass
            
        print("General plan approved by user.")
        self.send_message("Approved.")

    def reject_plan(self, feedback):
        try:
            from agent.MyAgent import tool_batch_approval_event, tool_batch_approval_result, tool_batch_waiting
            if tool_batch_waiting:
                print(f"Tool batch plan rejected: {feedback}")
                tool_batch_approval_result["approved"] = False
                tool_batch_approval_result["feedback"] = feedback
                tool_batch_approval_event.set()
                return
        except Exception as e:
            pass
            
        print(f"Plan rejected: {feedback}")
        self.send_message(f"Rejected. Please modify the plan based on this feedback: {feedback}")

    def send_message(self, text):
        global _global_agent, _global_messages, _global_active_session_id, _global_session_manager
        
        if not _global_active_session_id:
            self.new_session()
            
        if not isinstance(text, str):
            text = str(text)
            
        print(f"UI sent message: {text}")
        
        try:
            greetings = ["hi", "hello", "hey", "greetings", "yo", "morning", "afternoon", "evening", "who are you", "what's up", "how are you"]
            lower_input = text.lower().strip()
            is_greeting = any(lower_input.startswith(g) or lower_input == g for g in greetings)
            
            if is_greeting:
                from agent.MyAgent import AgentModel
                fast_resp = AgentModel.invoke([
                    SystemMessage(content="You are a friendly AI assistant. Keep it brief and conversational."),
                    HumanMessage(content=text)
                ])
                
                _global_messages.append(HumanMessage(content=text))
                _global_messages.append(AIMessage(content=fast_resp.content))
                _global_session_manager.update_session(_global_active_session_id, _global_messages)
                
                escaped_text = json.dumps(fast_resp.content)
                webview.windows[0].evaluate_js("window.startAgentResponse()")
                webview.windows[0].evaluate_js(f"window.appendFinalResponse({escaped_text})")
                return

            memories = retrieve_relevant_memories(text)
            if memories:
                _global_messages.append(SystemMessage(content=memories))
            
            _global_messages.append(HumanMessage(content=text))
            
            # Save the message immediately so user sees it in DB
            _global_session_manager.update_session(_global_active_session_id, _global_messages)
            
            if len(_global_messages) > 30:
                slice_idx = len(_global_messages) - 30
                while slice_idx < len(_global_messages):
                    if isinstance(_global_messages[slice_idx], HumanMessage):
                        break
                    slice_idx += 1
                if slice_idx < len(_global_messages):
                    _global_messages = _global_messages[slice_idx:]
                else:
                    _global_messages = _global_messages[-30:]

            webview.windows[0].evaluate_js("window.startAgentResponse()")
            
            final_state = None
            for state in _global_agent.stream({"messages": _global_messages}, stream_mode="values"):
                final_state = state
                if not state.get("messages"):
                    continue
                    
                # Save intermediate states to json (captures tool execution)
                _global_session_manager.update_session(_global_active_session_id, state["messages"])
                
                last_msg = state["messages"][-1]
                
                if last_msg.type == "ai":
                    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                        for tc in last_msg.tool_calls:
                            args_str = ""
                            if tc.get("args"):
                                args_str = ", ".join(f"{k}={json.dumps(v)}" for k, v in tc["args"].items())
                                if len(args_str) > 150:
                                    args_str = args_str[:150] + "..."
                            msg_text = json.dumps(f"Executing: {tc['name']}({args_str})")
                            webview.windows[0].evaluate_js(f"window.appendReasoning({msg_text}, true)")
                    elif last_msg.content and isinstance(last_msg.content, str):
                        if len(last_msg.content.strip()) > 0:
                            msg_text = json.dumps(last_msg.content.strip())
                            webview.windows[0].evaluate_js(f"window.appendReasoning({msg_text}, false)")
                            
                elif last_msg.type == "tool":
                    if last_msg.name == "take_screenshot":
                        try:
                            import base64
                            screenshot_path = os.path.join(project_root, "agent", "screenshot.png")
                            if not os.path.exists(screenshot_path):
                                screenshot_path = "screenshot.png"
                            
                            with open(screenshot_path, "rb") as f:
                                b64 = base64.b64encode(f.read()).decode('utf-8')
                                webview.windows[0].evaluate_js(f"window.appendScreenshot('{b64}')")
                            msg_text = json.dumps(f"Captured screenshot.")
                            webview.windows[0].evaluate_js(f"window.appendReasoning({msg_text}, false)")
                        except Exception as e:
                            print(f"Screenshot load error: {e}")
                    else:
                        tool_output = last_msg.content
                        if isinstance(tool_output, str):
                            if len(tool_output) > 200:
                                tool_output = tool_output[:200] + "..."
                        else:
                            tool_output = str(tool_output)[:200]
                        msg_text = json.dumps(f"Tool {last_msg.name} completed. Output: {tool_output}")
                        webview.windows[0].evaluate_js(f"window.appendReasoning({msg_text}, false)")

            if final_state and final_state.get("messages"):
                _global_messages = final_state["messages"]
                _global_session_manager.update_session(_global_active_session_id, _global_messages)
                
                last_msg = _global_messages[-1]
                
                final_text = ""
                if isinstance(last_msg.content, list):
                    text_parts = [part["text"] for part in last_msg.content if isinstance(part, dict) and "text" in part]
                    final_text = "".join(text_parts)
                else:
                    final_text = str(last_msg.content)
                
                escaped_text = json.dumps(final_text)
                webview.windows[0].evaluate_js(f"window.appendFinalResponse({escaped_text})")
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"Error in send_message: {e}")
            error_msg = json.dumps(f"Error: {str(e)}")
            webview.windows[0].evaluate_js(f"window.appendFinalResponse({error_msg})")


if __name__ == "__main__":
    html_path = os.path.join(project_root, "index.html")
    api = Api()
    
    window = webview.create_window(
        title='NEURAL_LINK_v4.2', 
        url='http://localhost:5173',
        js_api=api,
        width=1000,
        height=800,
        background_color='#131313'
    )
    
    webview.start(debug=True)
