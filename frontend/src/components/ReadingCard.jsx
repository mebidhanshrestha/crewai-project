import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { AGENTS } from "../agents.js";
import { useT } from "../i18n.js";
import ChartCard from "./ChartCard.jsx";

const RULE_ID = /R-[A-Z]{3}-[A-Z0-9]{2,3}/g;
// Section headings the writer is told to use, in English, Nepali and Japanese (see tasks.yaml).
const HEADINGS = [
  "Direct answer", "Why \\(Evidence Mode\\)", "Timing", "Confidence", "Practical suggestion",
  "सीधा उत्तर", "किन \\(प्रमाण\\)", "समय", "विश्वास स्तर", "व्यावहारिक सुझाव",
  "結論", "根拠（エビデンス）", "タイミング", "確信度", "実践的なアドバイス",
].join("|");
const HEADING_LINE = new RegExp(`^\\s*(\\d\\.\\s*)?\\**\\s*(${HEADINGS})\\s*[:：]\\**\\s*`, "gm");

// Turn "[R-CAR-01, R-DAS-SAT]" into markdown links that render as tappable chips,
// and put each section heading on its own bold line.
function prepare(text) {
  return text
    .replace(/\(\s*supported by\s*([^)]*)\)/gi, "$1")
    .replace(/\bsupported by\s*/gi, "")
    .replace(/\[([^\]]*?R-[A-Z]{3}-[A-Z0-9]{2,3}[^\]]*?)\]/g, "$1")
    .replace(RULE_ID, (id) => `[${id}](#rule:${id})`)
    .replace(HEADING_LINE, "\n**$2**\n\n");
}

// Plain text for the clipboard: rule codes become their labels.
function plainText(reading) {
  return reading.answer
    .replace(/\[([^\]]*?R-[A-Z]{3}-[A-Z0-9]{2,3}[^\]]*?)\]/g, "($1)")
    .replace(RULE_ID, (id) => reading.rules?.[id]?.label ?? id)
    .concat(`\n\n${reading.disclaimer}`);
}

// Ganita's note starts with the raw chart JSON; keep only the summary after it.
function readable(text = "") {
  const lastBrace = text.lastIndexOf("}\n");
  return text.trimStart().startsWith("{") && lastBrace > 0 ? text.slice(lastBrace + 1).trim() : text;
}

function RuleChip({ id, rule }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const box = useRef(null);
  const share = typeof rule?.how_common === "number" ? Math.round(rule.how_common * 100) : null;

  // Close on a tap outside or Escape (on phones the popup is a bottom sheet over the page).
  useEffect(() => {
    if (!open) return undefined;
    const away = (e) => { if (!box.current?.contains(e.target)) setOpen(false); };
    const esc = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("pointerdown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  return (
    <span className="rule" ref={box}>
      <button type="button" className={`rule-chip ${rule?.tone ?? ""}`} aria-expanded={open}
        onClick={() => setOpen((o) => !o)}>
        <span aria-hidden>{rule?.tone === "caution" ? "◆" : "✦"}</span> {rule?.label ?? id}
      </button>
      {open && (
        <span className="rule-pop" role="note">
          <button type="button" className="rule-close" aria-label={t.close} onClick={() => setOpen(false)}>✕</button>
          {rule ? (
            <>
              <strong>{rule.label}</strong>
              <span>{rule.reading}</span>
              <span className="rule-evidence">{t.inYourChart}: {rule.evidence.join("; ")}</span>
              {share !== null && (
                <span className={`rule-share ${share >= 40 ? "common" : ""}`}>
                  {t.fits(share)}{share >= 40 ? t.saysLittle : ""}
                </span>
              )}
              <span className="rule-tech">{t.classicalRule} {id} · {rule.name}</span>
            </>
          ) : id}
        </span>
      )}
    </span>
  );
}

function Strength({ strength }) {
  const t = useT();
  const entries = Object.entries(strength || {}).filter(([, s]) => s.percentile !== null);
  if (!entries.length) return null;
  // Show the most specific topic the council looked at.
  const [topic, s] = entries.sort((a, b) => b[1].percentile - a[1].percentile)[0];
  return (
    <p className={`strength ${s.strength}`} title={s.explanation}>
      <strong>{t.strength[s.strength] ?? s.strength}</strong>
      <span>{t.moreSpecific(t.topics[topic] ?? topic, s.percentile)}</span>
    </p>
  );
}

export default function ReadingCard({ reading, outputs }) {
  const t = useT();
  const [copied, setCopied] = useState(false);
  const ruleCount = Object.keys(reading.rules || {}).length;
  const m = reading.metrics;

  async function copy() {
    try {
      await navigator.clipboard.writeText(plainText(reading));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* clipboard unavailable */ }
  }

  return (
    <article className="card reading">
      <header className="reading-head">
        <div>
          <p className="reading-kicker">{t.readingKicker}</p>
          <h3>{reading.question}</h3>
        </div>
        <div className="reading-actions">
          <span className="verified">{t.verified}</span>
          <button type="button" className="ghost small" onClick={copy}>{copied ? t.copied : t.copy}</button>
        </div>
      </header>
      <Strength strength={reading.strength} />

      <div className="prose">
        <ReactMarkdown components={{
          a: ({ href = "", children }) => href.startsWith("#rule:")
            ? <RuleChip id={href.slice(6)} rule={reading.rules?.[href.slice(6)]} />
            : <a href={href}>{children}</a>,
        }}>
          {prepare(reading.answer)}
        </ReactMarkdown>
      </div>
      <p className="hint">{t.hint(ruleCount)}</p>

      <details className="fold">
        <summary>{t.seeChart}</summary>
        <ChartCard chart={reading.chart} />
      </details>

      <details className="fold">
        <summary>{t.howReached}</summary>
        <ol className="notes">
          {AGENTS.map((a) => outputs?.[a.key] && (
            <li key={a.key}>
              <p className="note-head">
                <span aria-hidden>{a.glyph}</span> {a.name} · {t.agents[a.key][0]}
                {m?.seconds_by_agent?.[a.key] !== undefined && (
                  <span className="note-time">
                    {m.seconds_by_agent[a.key]}s
                    {m.tokens_by_agent?.[a.key] !== undefined && ` · ${m.tokens_by_agent[a.key].toLocaleString()} ${t.tokens}`}
                  </span>
                )}
              </p>
              <div className="note-body"><ReactMarkdown>{readable(outputs[a.key])}</ReactMarkdown></div>
            </li>
          ))}
        </ol>
        {m && (
          <p className="metrics">
            {m.seconds_total}s · {m.llm_calls} {t.llmCalls} · {m.total_tokens.toLocaleString()} {t.tokens}
            {" "}({m.prompt_tokens.toLocaleString()} in / {m.completion_tokens.toLocaleString()} out) · {m.model}
          </p>
        )}
      </details>

      <p className="disclaimer">{reading.disclaimer}</p>
    </article>
  );
}
