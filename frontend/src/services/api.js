
const API_BASE_URL = (
  import.meta.env.VITE_API_URL || ""
).replace(/\/$/, "");

async function handleResponse(response, fallbackMessage) {
  if (!response.ok) {
    let message = fallbackMessage;

    try {
      const data = await response.json();
      if (typeof data.detail === "string") {
        message = data.detail;
      }
    } catch {
      // Keep the fallback message if the response isn't JSON.
    }

    throw new Error(message);
  }

  return response.json();
}

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

  return handleResponse(
    response,
    "Failed to communicate with scheduling API"
  );
}

export async function getConversation(threadId) {
  const response = await fetch(
    `${API_BASE_URL}/api/v1/conversations/${encodeURIComponent(threadId)}`
  );

  return handleResponse(
    response,
    "Failed to retrieve conversation"
  );
}
