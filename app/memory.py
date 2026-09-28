from llama_index.core.llms import ChatMessage


class ConversationMemory:
    """In-memory conversation history for the scheduling agent."""

    def __init__(self):
        self.history: list[ChatMessage] = []

    def add(self, role: str, content: str) -> None:
        self.history.append(
            ChatMessage(
                role=role,
                content=content,
            )
        )

    def get(self) -> list[ChatMessage]:
        return self.history

    def clear(self) -> None:
        self.history = []