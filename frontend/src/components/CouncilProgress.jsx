import { useEffect, useState } from "react";
import { AGENTS } from "../agents.js";
import { useT } from "../i18n.js";

// Inline card shown in the chat while the council works: the visible soft handoff.
export default function CouncilProgress({ question, steps, failed, started }) {
  const t = useT();
  const [now, setNow] = useState(Date.now());
  const running = !failed && Object.values(steps).some((s) => s !== "done" && s !== "skipped");

  // A reading takes about a minute and a half, so show that time is passing.
  useEffect(() => {
    if (!running) return undefined;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [running]);

  const doneCount = Object.values(steps).filter((s) => s === "done" || s === "skipped").length;
  return (
    <div className="card progress-card">
      <p className="progress-title">
        {t.progressTitle}
        <span className="progress-q">“{question}”</span>
      </p>
      <div className="progress-bar" role="progressbar" aria-valuemin={0} aria-valuemax={AGENTS.length}
        aria-valuenow={doneCount}>
        <span style={{ width: `${(doneCount / AGENTS.length) * 100}%` }} />
      </div>
      <ol className="stepper">
        {AGENTS.map((a) => {
          const state = steps[a.key];
          return (
            <li key={a.key} className={`step ${state}`}>
              <span className="step-dot" aria-hidden>{state === "done" ? "✓" : a.glyph}</span>
              <span className="step-name">{a.name}</span>
              <span className="step-verb">
                {state === "working" ? `${t.verbs[a.key]}…` : t.stepState[state]}
              </span>
            </li>
          );
        })}
      </ol>
      {running && <p className="progress-hint">{t.progressHint(Math.round((now - started) / 1000))}</p>}
      {failed && <p className="progress-failed">{failed}</p>}
    </div>
  );
}
