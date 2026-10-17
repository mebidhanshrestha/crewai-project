import { useCallback, useEffect, useRef, useState } from "react";
import { forgetPerson, getLedger, sendChat } from "./api.js";
import { AGENTS } from "./agents.js";
import { I18nContext, LANGS, langName, strings } from "./i18n.js";
import ChatThread from "./components/ChatThread.jsx";
import Composer from "./components/Composer.jsx";
import Sidebar from "./components/Sidebar.jsx";

const idleCouncil = () => Object.fromEntries(AGENTS.map((a) => [a.key, "idle"]));
const newSessionId = () =>
  globalThis.crypto?.randomUUID?.() ?? `s-${Date.now()}-${Math.random().toString(16).slice(2)}`;
let nextId = 1;
const msgId = () => nextId++;

// Per-viewer preferences; storage can be unavailable (private mode), so never depend on it.
const load = (key, fallback) => {
  try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; }
};
const save = (key, value) => {
  try { localStorage.setItem(key, value); } catch { /* ignore */ }
};
const browserLang = () => {
  const l = (navigator.language || "en").slice(0, 2);
  return LANGS.some((x) => x.code === l) ? l : "en";
};
const systemTheme = () =>
  window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";

export default function App() {
  const [lang, setLang] = useState(() => load("jc-lang", browserLang()));
  const [theme, setTheme] = useState(() => load("jc-theme", systemTheme()));
  const [sessionId, setSessionId] = useState(newSessionId);
  const [messages, setMessages] = useState([]);
  const [busy, setBusy] = useState(false);
  const [council, setCouncil] = useState(idleCouncil);
  const [profile, setProfile] = useState({});
  const [missing, setMissing] = useState(["name", "date", "time", "place"]);
  const [ledger, setLedger] = useState([]);
  const [panelOpen, setPanelOpen] = useState(false);
  const progressId = useRef(null);
  const t = strings(lang);

  useEffect(() => {
    document.documentElement.lang = lang;
    save("jc-lang", lang);
  }, [lang]);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    save("jc-theme", theme);
  }, [theme]);

  const refreshLedger = useCallback(async (name) => {
    setLedger(name ? await getLedger(name) : []);
  }, []);

  const patch = (id, fn) => setMessages((ms) => ms.map((m) => (m.id === id ? fn(m) : m)));

  async function send(text) {
    const message = text.trim();
    if (!message || busy) return;
    setBusy(true);
    setPanelOpen(false);
    setMessages((ms) => [...ms.filter((m) => !m.retry), { id: msgId(), type: "user", text: message }]);

    let name = profile.name;
    await sendChat(sessionId, message, langName(lang), (event, data) => {
      switch (event) {
        case "profile":
        case "end":
          setProfile(data.profile);
          setMissing(data.missing);
          name = data.profile.name;
          break;
        case "council_started": {
          const id = msgId();
          progressId.current = id;
          setCouncil(idleCouncil());
          setMessages((ms) => [...ms, {
            id, type: "progress", question: data.question, started: Date.now(),
            steps: idleCouncil(), outputs: {},
          }]);
          break;
        }
        case "agent":
          setCouncil((c) => ({ ...c, [data.agent]: data.state }));
          patch(progressId.current, (m) => ({
            ...m,
            steps: { ...m.steps, [data.agent]: data.state },
            outputs: data.output ? { ...m.outputs, [data.agent]: data.output } : m.outputs,
          }));
          break;
        case "reading":
          patch(progressId.current, (m) => ({ ...m, type: "reading", reading: data }));
          break;
        case "council_failed":
          patch(progressId.current, (m) => ({ ...m, failed: data.message }));
          setCouncil((c) => Object.fromEntries(
            Object.entries(c).map(([k, v]) => [k, v === "working" ? "failed" : v])));
          break;
        case "reply":
          setMessages((ms) => [...ms, { id: msgId(), type: "host", text: data.text }]);
          break;
        case "ledger":
          refreshLedger(name);
          break;
        case "error":
          setMessages((ms) => [...ms, {
            id: msgId(), type: "notice", retry: message,
            text: data.message ?? strings(lang).serverError(data.status),
          }]);
          break;
        default:
      }
    }).catch(() =>
      setMessages((ms) => [...ms, { id: msgId(), type: "notice", retry: message, text: t.serverError("—") }]));

    setBusy(false);
    if (name) refreshLedger(name);
  }

  function newConversation() {
    setSessionId(newSessionId());
    setMessages([]);
    setCouncil(idleCouncil());
    setProfile({});
    setMissing(["name", "date", "time", "place"]);
    setLedger([]);
  }

  async function forgetMe() {
    const name = profile.name;
    if (!name || !window.confirm(t.forgetConfirm(name))) return;
    try {
      const r = await forgetPerson(name);
      newConversation();
      setMessages([{ id: msgId(), type: "notice", tone: "ok", text: t.forgetDone(name, r.readings_deleted, r.chats_deleted) }]);
    } catch (err) {
      setMessages((ms) => [...ms, { id: msgId(), type: "notice", text: err.message }]);
    }
  }

  return (
    <I18nContext.Provider value={t}>
      <div className="app">
        <header className="topbar">
          <div className="brand">
            <span className="logo" aria-hidden>✦</span>
            <div>
              <strong>Jyotisha Council</strong>
              <span className="tagline">{t.tagline}</span>
            </div>
          </div>
          <div className="topbar-actions">
            <div className="lang-switch" role="group" aria-label="Language">
              {LANGS.map((l) => (
                <button key={l.code} type="button" lang={l.code} aria-pressed={lang === l.code}
                  className={lang === l.code ? "on" : ""} onClick={() => setLang(l.code)}>
                  {l.label}
                </button>
              ))}
            </div>
            <button type="button" className="icon-btn" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              aria-label={theme === "dark" ? t.themeLight : t.themeDark} title={theme === "dark" ? t.themeLight : t.themeDark}>
              {theme === "dark" ? "☀" : "☾"}
            </button>
            <button type="button" className="ghost panel-toggle" onClick={() => setPanelOpen((o) => !o)}
              aria-expanded={panelOpen}>
              {t.council}
            </button>
            <button type="button" className="ghost" onClick={newConversation} disabled={busy}>
              {t.newChat}
            </button>
          </div>
        </header>

        <div className="workspace">
          <main className="chat">
            <ChatThread messages={messages} busy={busy} onSend={send} />
            <Composer busy={busy} onSend={send} />
          </main>
          <Sidebar
            open={panelOpen}
            onClose={() => setPanelOpen(false)}
            council={council}
            profile={profile}
            missing={missing}
            ledger={ledger}
            onLedgerChange={() => refreshLedger(profile.name)}
            onForget={forgetMe}
          />
        </div>
      </div>
    </I18nContext.Provider>
  );
}
