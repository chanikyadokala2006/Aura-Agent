import os
import sys

project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.append(project_root)

from agent.MyAgent import AgentModel
from langchain_core.messages import SystemMessage, HumanMessage

print("Invoking AgentModel...")
try:
    resp = AgentModel.invoke([
        SystemMessage(content="Hello"),
        HumanMessage(content="HELLO")
    ])
    print(resp.content)
except Exception as e:
    import traceback
    traceback.print_exc()
