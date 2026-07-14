import os
import importlib.util
import logging
from langchain.tools import BaseTool

logger = logging.getLogger(__name__)

class SkillsManager:
    """
    A dynamic plugin system inspired by Open-Cowork's skill runtime.
    Loads Python files from a skills directory and registers them as LangChain tools.
    """
    def __init__(self, skills_dir: str):
        self.skills_dir = skills_dir
        self.loaded_tools: list[BaseTool] = []
        
        if not os.path.exists(skills_dir):
            os.makedirs(skills_dir)
            logger.info(f"Created skills directory at {skills_dir}")

    def load_skills(self) -> list[BaseTool]:
        """Scans the skills directory and imports valid LangChain tools."""
        self.loaded_tools = []
        for filename in os.listdir(self.skills_dir):
            if filename.endswith(".py") and not filename.startswith("__"):
                path = os.path.join(self.skills_dir, filename)
                try:
                    spec = importlib.util.spec_from_file_location(filename[:-3], path)
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        
                        # Find tools in the module
                        for attr_name in dir(module):
                            attr = getattr(module, attr_name)
                            if isinstance(attr, BaseTool) or (hasattr(attr, "name") and hasattr(attr, "description") and hasattr(attr, "_run")):
                                self.loaded_tools.append(attr)
                                logger.info(f"Loaded skill tool: {attr.name}")
                except Exception as e:
                    logger.error(f"Failed to load skill from {filename}: {e}")
                    
        return self.loaded_tools

    def get_tools(self) -> list[BaseTool]:
        return self.loaded_tools
