export default function AttemptHistory({ attempts }) {
  // Show oldest first, skip the latest (it lives in ResultsPanel above).
  const past = attempts.slice(0, -1);

  return (
    <section className="panel">
      <h2>Attempt history</h2>
      {past.length === 0 ? (
        <div className="history-empty">
          No prior attempts yet. Your past tries will show up here.
        </div>
      ) : (
        past.map((a) => {
          const r = a.response;
          return (
            <div className="history-row" key={a.attemptNumber}>
              <span className="attempt">#{a.attemptNumber}</span>
              <span className="summary" title={a.prompt}>
                {a.prompt}
              </span>
              <span className="tests-count">
                {r.passed_count}/{r.total}
              </span>
              <span className="score">{r.overall_score.toFixed(1)}</span>
            </div>
          );
        })
      )}
    </section>
  );
}
