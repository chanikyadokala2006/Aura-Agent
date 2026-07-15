import os
import sys
import json
import uuid
import time
import asyncio
import aiosqlite
import threading
import webview

# Add the project root to sys.path so we can import from agent
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.append(project_root)

from agent.MyAgent import setup_agent, retrieve_relevant_memories
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage

from db import SessionManager

DB_PATH = os.path.join(project_root, "agent_memory.db")

_global_agent = None
_global_messages = []
_global_session_manager = SessionManager(DB_PATH)
_global_active_session_id = None
_global_memory = None  # AsyncSqliteSaver held open for lifetime of app
_global_db_conn = None  # Persistent aiosqlite connection

# Single persistent event loop for all agent coroutines
_agent_loop = asyncio.new_event_loop()

def _start_agent_loop():
    _agent_loop.run_forever()

_agent_loop_thread = threading.Thread(target=_start_agent_loop, daemon=True)
_agent_loop_thread.start()


class Api:
    def get_sessions(self):
        return _global_session_manager.get_sessions()

    def get_artifact(self, filename):
        artifact_path = os.path.join(project_root, "agent", filename)
        if os.path.exists(artifact_path):
            with open(artifact_path, "r", encoding="utf-8") as f:
                return f.read()
        return "Artifact not found."

    def new_session(self):
        global _global_messages, _global_active_session_id
        _global_messages = []
        sess = _global_session_manager.create_session()
        _global_active_session_id = sess["id"]
        return sess

    def load_session(self, session_id):
        global _global_messages, _global_active_session_id
        sess_meta = _global_session_manager.get_session_metadata(session_id)
        if not sess_meta:
            return None
        _global_active_session_id = session_id
        
        try:
            state = _global_agent.get_state({"configurable": {"thread_id": session_id}})
            _global_messages = state.values.get("messages", []) if state and hasattr(state, "values") else []
        except Exception:
            _global_messages = []
            
        sess = dict(sess_meta)
        sess["messages"] = [_global_session_manager.serialize_message(m) for m in _global_messages]
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
        asyncio.run_coroutine_threadsafe(self._async_send_message(text), _agent_loop)

    async def _async_send_message(self, text):
        global _global_agent, _global_messages, _global_active_session_id, _global_session_manager
        
        if not _global_active_session_id:
            sess = self.new_session()
            _global_active_session_id = sess["id"]
            
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
                
                escaped_text = json.dumps(fast_resp.content)
                webview.windows[0].evaluate_js("window.startAgentResponse()")
                webview.windows[0].evaluate_js(f"window.appendFinalResponse({escaped_text})")
                return

            memories = retrieve_relevant_memories(text)
            input_messages = []
            if memories:
                input_messages.append(SystemMessage(content=memories))
            
            input_messages.append(HumanMessage(content=text))
            
            # Update title if it's the first real message
            sess_meta = _global_session_manager.get_session_metadata(_global_active_session_id)
            if sess_meta and sess_meta["title"] == "New Session":
                _global_session_manager.update_session_title(_global_active_session_id, text[:30] + "...")

            webview.windows[0].evaluate_js("window.startAgentResponse()")
            
            config = {"configurable": {"thread_id": _global_active_session_id}}
            final_state = None
            
            async for state in _global_agent.astream({"messages": input_messages}, config=config, stream_mode="values"):
                final_state = state
                if not state.get("messages"):
                    continue
                    
                last_msg = state["messages"][-1]
                
                if last_msg.type == "ai":
                    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                        for tc in last_msg.tool_calls:
                            tool_name = tc['name']
                            human_msg = f"Executing: {tool_name}"
                            if tool_name in ["list_dir", "list_directory", "list_files"]:
                                human_msg = f"👀 Looking at the files in the directory..."
                            elif tool_name in ["view_file", "read_file"]:
                                human_msg = f"📖 Reading the contents of a file..."
                            elif tool_name == "search_file":
                                human_msg = f"🔍 Searching for a file..."
                            elif tool_name == "computer_move_mouse":
                                human_msg = f"🖱️ Moving the mouse..."
                            elif tool_name == "computer_click":
                                human_msg = f"👆 Clicking on the screen..."
                            elif tool_name == "computer_type":
                                human_msg = f"⌨️ Typing text..."
                            elif tool_name == "run_command":
                                human_msg = f"🖥️ Running terminal command..."
                            elif tool_name in ["navigate_to_url", "extract_page_content", "browser_click_element", "browser_type_text"]:
                                human_msg = f"🌐 Operating Browser ({tool_name})..."
                            else:
                                human_msg = f"⚙️ Using tool {tool_name}..."

                            msg_text = json.dumps(human_msg)
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
                        msg_text = json.dumps(f"Tool {last_msg.name} completed.")
                        webview.windows[0].evaluate_js(f"window.appendReasoning({msg_text}, false)")

            if final_state and final_state.get("messages"):
                last_msg = final_state["messages"][-1]
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
            error_msg = json.dumps(f"Error: {str(e)}")
            webview.windows[0].evaluate_js(f"window.appendFinalResponse({error_msg})")


async def _init_agent():
    """Initialize the agent with AsyncSqliteSaver checkpointer."""
    global _global_agent, _global_memory, _global_db_conn
    try:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        # Open a persistent connection that lives for the entire app lifetime.
        # Using from_conn_string creates a context whose internal thread can
        # only be started once, causing RuntimeError on the second message.
        _global_db_conn = await aiosqlite.connect(DB_PATH)
        _global_memory = AsyncSqliteSaver(_global_db_conn)
        print("AsyncSqliteSaver checkpointer initialized.")
    except Exception as e:
        print(f"Warning: Could not initialize AsyncSqliteSaver: {e}")
        _global_memory = None
    _global_agent = setup_agent(memory=_global_memory)


if __name__ == "__main__":
    # Initialize agent with async checkpointer on the persistent loop, wait for it
    future = asyncio.run_coroutine_threadsafe(_init_agent(), _agent_loop)
    future.result()  # Block until agent is fully initialized

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
