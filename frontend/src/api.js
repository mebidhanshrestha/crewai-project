// Thin client for the FastAPI backend.

export async function getLedger(name) {
  const res = await fetch(`/api/ledger?name=${encodeURIComponent(name)}`);
  return res.ok ? res.json() : [];
}

export async function setOutcome(id, outcome) {
  const res = await fetch(`/api/ledger/${id}/outcome`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ outcome }),
  });
  if (!res.ok) throw new Error("Could not save feedback");
  return res.json();
}

// Delete-on-request: birth details, readings and chat transcripts for this name.
export async function forgetPerson(name) {
  const res = await fetch(`/api/person?name=${encodeURIComponent(name)}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Could not delete your data");
  return res.json();
}

// POST /api/chat streams Server-Sent Events for one turn. Calls onEvent(type, data) for each.
// `language` is the interface language; a message written in Nepali or Japanese overrides it.
export async function sendChat(sessionId, message, language, onEvent) {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message, language }),
  });
  if (!res.ok || !res.body) {
    onEvent("error", { status: res.status });
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let split;
    while ((split = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, split);
      buffer = buffer.slice(split + 2);
      const event = block.match(/^event: (.*)$/m)?.[1];
      const data = block.match(/^data: (.*)$/m)?.[1];
      if (event && data) onEvent(event, JSON.parse(data));
    }
  }
}
