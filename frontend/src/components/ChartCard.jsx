import { useT } from "../i18n.js";

const ORDER = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"];

export default function ChartCard({ chart }) {
  const t = useT();
  if (!chart) return null;
  const { dasha } = chart;
  const c = t.chart;
  return (
    <div className="chart">
      <dl className="facts">
        <div><dt>{c.lagna}</dt><dd>{chart.lagna}</dd></div>
        <div><dt>{c.moon}</dt><dd>{chart.moon_sign}</dd></div>
        <div><dt>{c.nakshatra}</dt><dd>{chart.nakshatra}</dd></div>
        <div>
          <dt>{c.dasha}</dt>
          <dd>{dasha.mahadasha} / {dasha.antardasha}</dd>
          <span className="until">{c.until} {dasha.antardasha_until}</span>
        </div>
      </dl>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>{c.planet}</th><th>{c.sign}</th><th className="num">{c.degree}</th><th className="num">{c.house}</th><th>{c.dignity}</th></tr>
          </thead>
          <tbody>
            {ORDER.filter((p) => chart.planets[p]).map((p) => {
              const pl = chart.planets[p];
              return (
                <tr key={p}>
                  <td>{p}</td>
                  <td>{pl.sign}</td>
                  <td className="num">{pl.degree.toFixed(2)}°</td>
                  <td className="num">{pl.house}</td>
                  <td>{pl.dignity !== "neutral" && <span className={`dignity ${pl.dignity}`}>{pl.dignity}</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="chart-note">{c.note}</p>
    </div>
  );
}
