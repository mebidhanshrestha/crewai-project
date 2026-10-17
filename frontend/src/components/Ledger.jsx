import { useState } from "react";
import { setOutcome } from "../api.js";
import { useT } from "../i18n.js";

export default function Ledger({ person, entries, onChange }) {
  const t = useT();
  const [saving, setSaving] = useState(null);

  async function record(id, outcome) {
    setSaving(id);
    try {
      await setOutcome(id, outcome);
      onChange();
    } finally {
      setSaving(null);
    }
  }

  const scored = entries.filter((e) => e.outcome);
  const hits = scored.filter((e) => e.outcome === "happened").length;

  return (
    <section className="panel ledger">
      <h2>{t.ledger}</h2>
      {!person || entries.length === 0 ? (
        <p className="panel-note">{t.ledgerEmpty}</p>
      ) : (
        <>
          {scored.length > 0 && <p className="accuracy">{t.ledgerScore(hits, scored.length)}</p>}
          <ul>
            {[...entries].reverse().map((e) => (
              <li key={e.id}>
                <p className="q">{e.question}</p>
                <div className="ledger-row">
                  <span className="when">{e.timestamp.slice(0, 10)}</span>
                  {e.outcome ? (
                    <span className={`state ${e.outcome === "happened" ? "done" : "failed"}`}>
                      {e.outcome === "happened" ? t.happened : t.didntHappen}
                    </span>
                  ) : (
                    <span className="feedback">
                      {t.cameTrue}
                      <button type="button" disabled={saving === e.id} onClick={() => record(e.id, "happened")}>{t.yes}</button>
                      <button type="button" disabled={saving === e.id} onClick={() => record(e.id, "did_not_happen")}>{t.no}</button>
                    </span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
