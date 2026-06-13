// Parses the requirements string ("- Heading: body\n- Heading: body...")
// into [{ heading, body }] so we can render each as its own row.
function parseRequirements(s) {
  const items = [];
  for (const raw of (s || "").split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const m = line.match(/^[-*•]\s+(.+)$/) || line.match(/^\d+[.)]\s+(.+)$/);
    if (!m) continue;
    const rest = m[1];
    const idx = rest.indexOf(":");
    if (idx === -1) {
      items.push({ heading: null, body: rest });
    } else {
      items.push({
        heading: rest.slice(0, idx).trim(),
        body: rest.slice(idx + 1).trim(),
      });
    }
  }
  return items;
}

export default function ProblemPanel({ question }) {
  const reqs = parseRequirements(question.requirements);
  return (
    <section className="panel">
      <h2>Problem</h2>
      <p className="problem-desc">{question.problem_description}</p>

      <h2 style={{ marginTop: 18 }}>What your prompt must cover</h2>
      <ul className="requirements">
        {reqs.map((r, i) => (
          <li key={i}>
            {r.heading && <b>{r.heading}: </b>}
            {r.body}
          </li>
        ))}
      </ul>

      <h2 style={{ marginTop: 18 }}>Sample tests</h2>
      <div className="sample-tests">
        {question.sample_tests.map((t, i) => (
          <div key={i} className="row">
            <span>{t.input}</span>
            <span className="arrow">→</span>
            <span>{t.expected}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
