# Aura (Cognitive OS)

A desktop AI agent that can actually see and use your screen — not just chat about it.

Aura pairs a LangGraph agent with a native pywebview UI, so instead of a chatbot that tells you what to click, it takes screenshots, figures out where the buttons are, and clicks them itself. It also keeps a running memory of what it's learned across sessions instead of forgetting everything on restart.

## What it actually does

- **Screen understanding + control** — grabs a screenshot, uses `pywinauto` to find UI elements, draws bounding boxes/IDs over them (Set-of-Marks style), and sends the whole thing to the model so it can decide what to click. This part works well and is the core of the project.
- **Long-term memory** — every session gets synced into a local ChromaDB store, and the agent pulls back relevant memories on future runs. Fully working, not just a stub.
- **Loop protection** — a custom `LoopGuardMiddleware` sits in the agent graph and stops it from retrying the same failing action forever. This has saved me more API credits than I'd like to admit.
- **Live reasoning in the UI** — the agent's thinking streams into the frontend in real time via pywebview's JS bridge, so you can watch it work instead of staring at a spinner.
- **Tool schema patching** — some open-source models hallucinate malformed JSON (trailing commas, mostly). A middleware catches and fixes this before it breaks tool calls.
- **Windows integration** — opening/closing files and tracking processes uses `os.startfile` and `psutil` directly, so it behaves like a native app rather than shelling out to scripts.
- **MCP support** — turns out this was more built than I gave it credit for. It reads `mcp_config.json`, spawns MCP servers as subprocesses, and wires their tools in as LangChain `StructuredTool`s. Works today, not just planned.
- **SQLite-backed checkpointing** — agent state persists via `AsyncSqliteSaver` rather than flat JSON files.

## What's half-built or missing

Being upfront here so nobody's surprised:

- **"Semantic" codebase search isn't semantic yet.** File search currently does exact-match string/glob matching via `os.walk`. The vector memory exists, but code search doesn't use it yet — that's next.
- **Cross-language code execution is minimal.** There's a generic terminal/command tool and basic file I/O, but the sandboxed multi-language execution I want (via WSL) is imported and wired up, just not actually used in practice yet.
- **Browser automation is scaffolded, not driving.** Playwright tooling is loaded dynamically and heavily guarded against failure, but it doesn't yet take over real navigation/auth flows. Treat it as "present but not trustworthy."
- **No local model fallback.** Everything currently routes through a hosted API. If that key is missing or the service is down, the agent just fails — there's no offline/local model path yet.

## Setup

**Backend**
```bash
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

**Frontend**
```bash
cd src\renderer
npm install
```

**Environment variables** — create a `.env` in the root:
```
AICREDITS_API_KEY=your_key_here
# Optional, defaults to C:\ if unset
AGENT_SANDBOX_ROOT=C:\your\preferred\sandbox\path
```

The `AICREDITS_API_KEY` is required — it's what authenticates both the LLM calls (routed to Claude Sonnet) and the embedding calls (OpenAI embeddings). Without it, the agent won't start.

## Running it

Double-click `Launch_Aura.bat` in the root. It'll spin up the Vite dev server for the frontend in the background, automatically activate your Python virtual environment, and start the Python agent/pywebview shell natively.
## Roadmap

Some of what I originally planned as "future work" turned out to get built along the way. Current honest state:

- [x] MCP integration — working
- [x] SQLite-backed memory — working
- [x] Playwright web automation — working
- [ ] Local SLM fallback — not started, everything's API-dependent right now
- [ ] Real semantic code search (vector-backed, not string match)
- [ ] `.env.example`

## 🎯 10 Example Tasks

If you're testing Aura out, try these commands to push the limits of what the agent can do:

1. **"Open my project folder, find any file that mentions 'TODO', and list them with the line it appears on."** (Tests file system navigation + text search + reading)
2. **"Open Notepad, draft a short status update summarizing what changed in this project this week, and save it as status.txt in the project root."** (Tests OS integration, typing/UI control, and file I/O together)
3. **"Check my C: drive free space and my current running processes, and tell me if anything looks like it's eating memory."** (Tests native OS command execution)
4. **"Take a screenshot of my current desktop, tell me what windows are open, and bring the file explorer to the front if it's not already."** (Tests Set-of-Marks vision parsing + pywinauto UI control)
5. **"Remember that I prefer commit messages in the format `type: description`."** (Followed by asking it to commit something, testing ChromaDB long-term memory persistence)
6. **"Open the .env file, tell me which environment variables are set versus missing compared to what the README expects, without printing any secret values."** (Tests file reading + reasoning)
7. **"List the MCP servers currently configured and tell me which tools each one exposes."** (Tests the working MCP subprocess/tool-wiring feature)
8. **"Open two apps side by side — Notepad and File Explorer — and arrange them so I can see both."** (Tests multi-window pywinauto control)
9. **"Watch what I'm doing for the next minute and tell me what task you think I'm working on."** (Tests live reasoning stream + repeated screenshot/SoM cycle)
10. **"If something you tried fails twice in a row, stop and tell me what you tried instead of continuing to retry."** (Tests LoopGuardMiddleware)

## Stack

React 19 + Tailwind + Vite for the UI, rendered natively via `pywebview`. Python backend on LangGraph/LangChain, ChromaDB for memory, `pywinauto`/`pyautogui`/`PIL` for screen perception and control.