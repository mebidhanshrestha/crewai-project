import { useEffect, useRef, useState } from "react";
import { useT } from "../i18n.js";

export default function Composer({ busy, onSend }) {
  const t = useT();
  const [text, setText] = useState("");
  const box = useRef(null);

  // Grow with the text, up to a limit.
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [text]);

  useEffect(() => {
    if (!busy) box.current?.focus();
  }, [busy]);

  function submit(e) {
    e?.preventDefault();
    if (!text.trim() || busy) return;
    onSend(text);
    setText("");
  }

  return (
    <form className="composer" onSubmit={submit}>
      <textarea
        ref={box}
        rows={1}
        value={text}
        placeholder={busy ? t.placeholderBusy : t.placeholder}
        aria-label={t.placeholder}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) submit(e);
        }}
      />
      <button type="submit" className="send" disabled={busy || !text.trim()} aria-label={t.send}>
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden>
          <path d="M4 12l16-8-6 16-2.5-6.5L4 12z" fill="currentColor" />
        </svg>
      </button>
      <p className="composer-note">{t.composerNote}</p>
    </form>
  );
}
