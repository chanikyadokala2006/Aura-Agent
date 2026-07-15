# Codebase Architecture Context

## My Agent (`C:\Projects\Agent_project\my-ollama-project`)
- **Type**: Python-based LangGraph desktop application.
- **Frontend**: React + Vite (located in `src/renderer`), served via `pywebview` to act as a desktop app.
- **Backend**: `src/main/main.py` handles the Pywebview API and session management (currently using JSON). `src/main/agent/MyAgent.py` contains the LangGraph logic, ChromaDB memory integration, and basic tools (file searching, opening, moving mouse).
- **Strengths**: Highly customizable logic loop, custom `LoopGuardMiddleware` to prevent getting stuck, and ChromaDB vector search for long-term memory.
- **Weaknesses**: Monolithic `main.py`, synchronous UI loop blocking rendering, and lack of true native vision-based browser automation (relies on coordinate guessing with Llama-3.3).

## Claude Co-work (`C:\Users\Venkat\Downloads\open-cowork-main\open-cowork-main`)
- **Type**: TypeScript-based Electron desktop application.
- **Architecture**: Highly modular. Separated into `src/main`, `src/renderer`, `src/shared`. 
- **Features**: 
  - Native Model Context Protocol (MCP) integration.
  - Deep sandboxing via WSL or Lima for safe tool execution.
  - Advanced memory extraction (`experience-memory-store.ts`).
  - Native integration with Anthropic's Computer Use API, allowing it to natively "see" the screen and map coordinates accurately.
- **Database**: Uses `better-sqlite3` for blazing fast, asynchronous local storage.

## Comparison & Goal
My Agent aims to achieve the performance and feature set of Claude Co-work. The roadmap to achieve this involves migrating to an SQLite database, making the Python execution loop asynchronous, integrating Playwright for text-based web browsing, and overhauling the React UI to match a state-of-the-art 3-pane layout.
