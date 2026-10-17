import { useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import { useT } from "../i18n.js";
import CouncilProgress from "./CouncilProgress.jsx";
import ReadingCard from "./ReadingCard.jsx";

function Avatar() {
  return <span className="avatar" aria-hidden>P</span>;
}

export default function ChatThread({ messages, busy, onSend }) {
  const t = useT();
  const end = useRef(null);
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, busy]);

  const last = messages.at(-1);
  const waitingForHost = busy && last?.type === "user";
  // Offer follow-ups once a reading has been answered and the host has replied.
  const showFollowUps = !busy && last?.type === "host" && messages.some((m) => m.type === "reading");

  return (
    <div className="thread" aria-live="polite">
      {messages.length === 0 && (
        <div className="welcome">
          <span className="welcome-mark" aria-hidden>✦</span>
          <h1>{t.welcomeTitle}</h1>
          <p>{t.welcomeBody}</p>
          <ol className="how">
            {t.steps.map((s, i) => <li key={s}><span>{i + 1}</span>{s}</li>)}
          </ol>
          <div className="suggestions">
            {t.suggestions.map((s) => (
              <button key={s} type="button" className="suggestion" onClick={() => onSend(s)}>{s}</button>
            ))}
          </div>
        </div>
      )}

      {messages.map((m) => {
        if (m.type === "user") {
          return <div key={m.id} className="msg user"><div className="bubble">{m.text}</div></div>;
        }
        if (m.type === "host") {
          return (
            <div key={m.id} className="msg host">
              <Avatar />
              <div className="bubble"><ReactMarkdown>{m.text}</ReactMarkdown></div>
            </div>
          );
        }
        if (m.type === "progress") {
          return (
            <div key={m.id} className="msg host wide">
              <Avatar />
              <CouncilProgress question={m.question} steps={m.steps} failed={m.failed} started={m.started} />
            </div>
          );
        }
        if (m.type === "reading") {
          return (
            <div key={m.id} className="msg host wide">
              <Avatar />
              <ReadingCard reading={m.reading} outputs={m.outputs} />
            </div>
          );
        }
        return (
          <div key={m.id} className={`msg notice ${m.tone ?? ""}`} role="alert">
            <span>{m.text}</span>
            {m.retry && !busy && (
              <button type="button" className="retry" onClick={() => onSend(m.retry)}>{t.retry}</button>
            )}
          </div>
        );
      })}

      {waitingForHost && (
        <div className="msg host">
          <Avatar />
          <div className="bubble typing" aria-label={t.typing}>
            <span /><span /><span />
          </div>
        </div>
      )}

      {showFollowUps && (
        <div className="followups">
          {t.followUps.map((q) => (
            <button key={q} type="button" className="chip-btn" onClick={() => onSend(q)}>{q}</button>
          ))}
        </div>
      )}
      <div ref={end} />
    </div>
  );
}
