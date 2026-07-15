import asyncio
import time
from langchain_core.messages import HumanMessage
import json

class BackgroundScheduler:
    def __init__(self, db, agent, loop):
        self.db = db
        self.agent = agent
        self.loop = loop
        self.running = False
        
    async def _scheduler_loop(self):
        print("Background scheduler started.")
        while self.running:
            try:
                tasks = await self.db.get_scheduled_tasks()
                current_time = int(time.time() * 1000)
                
                for task in tasks:
                    if not task["active"]:
                        continue
                        
                    interval_ms = task["interval_minutes"] * 60 * 1000
                    last_run = task["last_run"]
                    
                    if current_time - last_run >= interval_ms:
                        print(f"Triggering scheduled task: {task['id']}")
                        
                        # Create headless session
                        sess = await self.db.create_session()
                        session_id = sess["id"]
                        
                        # Inject prompt
                        prompt = task["prompt"]
                        messages = [HumanMessage(content=prompt)]
                        
                        # We don't block the scheduler on this, we let the agent run in a separate task
                        config = {"configurable": {"thread_id": session_id}}
                        
                        # Fire and forget execution logic for headless
                        async def run_headless_agent(session_id, messages, config):
                            try:
                                async for _ in self.agent.astream({"messages": messages}, config=config, stream_mode="values"):
                                    pass
                                print(f"Headless task completed for session {session_id}")
                            except Exception as e:
                                print(f"Headless task failed for session {session_id}: {e}")
                                
                        self.loop.create_task(run_headless_agent(session_id, messages, config))
                        
                        # Update last_run
                        await self.db.update_task_last_run(task["id"], current_time)
                        
            except Exception as e:
                print(f"Error in scheduler loop: {e}")
                
            # Check every minute
            await asyncio.sleep(60)

    def start(self):
        if not self.running:
            self.running = True
            self.loop.create_task(self._scheduler_loop())

    def stop(self):
        self.running = False
