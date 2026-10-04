const API_BASE_URL = "http://localhost:8000";

export async function sendMessage(query, threadId) {
  const response = await fetch(
    `${API_BASE_URL}/api/v1/schedule`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        query,
        thread_id: threadId,
      }),
    }
  );

  if (!response.ok) {
    throw new Error("Failed to communicate with scheduling API");
  }

  return response.json();
}

export async function getConversation(threadId) {
  const response = await fetch(
    `${API_BASE_URL}/api/v1/conversations/${threadId}`
  );

  if (!response.ok) {
    throw new Error("Failed to retrieve conversation");
  }

  return response.json();
}