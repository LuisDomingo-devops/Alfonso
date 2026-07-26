from typing import Protocol, Any, Dict, List

class LLMPort(Protocol):
    async def generate(self, prompt: str, **kwargs) -> str:
        """Generates a text completion for a prompt."""
        ...

    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """Sends a full chat structure and returns the text response."""
        ...
