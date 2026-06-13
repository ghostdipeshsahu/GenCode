function ScoreCard({ label, value, kind }) {
  return (
    <div className={`score-card ${kind || ""}`}>
      <div className="label">{label}</div>
      <div className="value">{value.toFixed(1)}</div>
    </div>
  );
}

function TestRow({ t }) {
  const isHidden = t.input === "(hidden)";
  return (
    <div className={`row ${isHidden ? "hidden" : ""}`}>
      <span className={`flag ${t.passed ? "pass" : "fail"}`}>
        {t.passed ? "PASS" : "FAIL"}
      </span>
      <span className="body">
        {isHidden ? (
          <>
            <span className="label">hidden edge case</span>
            {t.edge_label ? ` · ${t.edge_label}` : null}
          </>
        ) : (
          <>
            <span className="label">in </span>
            {t.input}
            <span className="label"> · expected </span>
            {t.expected}
            <span className="label"> · got </span>
            {t.actual}
          </>
        )}
        {t.error && <span className="err">{t.error}</span>}
      </span>
    </div>
  );
}

export default function ResultsPanel({ attemptNumber, response }) {
  const {
    overall_score,
    requirement_quality,
    output_quality,
    requirement_findings,
    feedback,
    test_results,
    passed_count,
    total,
    all_passed,
  } = response;

  return (
    <section className="panel">
      <h2>Result · attempt #{attemptNumber}</h2>

      {all_passed && (
        <div className="celebration">
          All {total} tests passed. Final score {overall_score.toFixed(1)} / 10.
        </div>
      )}

      <div className="scores">
        <ScoreCard label="Overall" value={overall_score} kind="overall" />
        <ScoreCard label="Requirement quality" value={requirement_quality} />
        <ScoreCard label="Output quality" value={output_quality} />
      </div>

      <div className="feedback">{feedback}</div>

      <h2>Per-requirement findings</h2>
      <ul className="findings">
        {requirement_findings.map((f, i) => (
          <li key={i} className={f.status}>
            <span className={`badge ${f.status}`}>{f.status}</span>
            <span className="req-text">{f.requirement}</span>
            <span className="evidence">{f.evidence}</span>
          </li>
        ))}
      </ul>

      <h2>
        Tests · {passed_count} / {total} passed
      </h2>
      <div className="tests">
        {test_results.map((t, i) => (
          <TestRow key={i} t={t} />
        ))}
      </div>
    </section>
  );
}
