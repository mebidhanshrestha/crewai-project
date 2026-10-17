import { AGENTS } from "../agents.js";
import { LANGS, langCode, useT } from "../i18n.js";
import Ledger from "./Ledger.jsx";

const FIELDS = ["name", "date", "time", "place", "language"];

export default function Sidebar({ open, onClose, council, profile, missing, ledger, onLedgerChange, onForget }) {
  const t = useT();
  const shown = (key) => key === "language" && profile.language
    ? LANGS.find((l) => l.code === langCode(profile.language))?.label
    : profile[key];

  return (
    <>
      {open && <button type="button" className="scrim" aria-label={t.close} onClick={onClose} />}
      <aside className={`sidebar ${open ? "open" : ""}`} aria-label={t.theCouncil}>
        <button type="button" className="panel-close" onClick={onClose}>{t.close}</button>
        <section className="panel">
          <h2>{t.theCouncil}</h2>
          <ul className="roster">
            {AGENTS.map((a) => (
              <li key={a.key} className={council[a.key]}>
                <span className="roster-glyph" aria-hidden>{a.glyph}</span>
                <div className="roster-text">
                  <strong>{a.name} <em>{t.agents[a.key][0]}</em></strong>
                  <span>{t.agents[a.key][1]}</span>
                </div>
                <span className={`state ${council[a.key]}`}>{t.rosterState[council[a.key]]}</span>
              </li>
            ))}
          </ul>
        </section>

        <section className="panel">
          <h2>{t.yourDetails}</h2>
          <dl className="details">
            {FIELDS.map((key) => (
              <div key={key}>
                <dt>{t.fields[key]}</dt>
                <dd className={profile[key] ? "" : "missing"}>
                  {shown(key) || (missing.includes(key) ? t.notShared : "—")}
                </dd>
              </div>
            ))}
          </dl>
          <p className="panel-note">{t.detailsNote}</p>
          {profile.name && (
            <button type="button" className="forget" onClick={onForget}>{t.forget}</button>
          )}
        </section>

        <Ledger person={profile.name} entries={ledger} onChange={onLedgerChange} />

        <section className="panel guardrails">
          <h2>{t.guardrails}</h2>
          <ul>{t.guardrailItems.map((g) => <li key={g}>{g}</li>)}</ul>
        </section>
      </aside>
    </>
  );
}
