import os

from dotenv import load_dotenv
from langchain_groq import ChatGroq


load_dotenv()


def setup_llm() -> ChatGroq:
    """
    Initialize and return the Groq chat model.
    """

    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        raise ValueError(
            "GROQ_API_KEY is not configured. "
            "Add it to your .env file."
        )

    llm = ChatGroq(
        model="openai/gpt-oss-120b",
        temperature=0,
        api_key=api_key,
    )

    return llm