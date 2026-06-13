export default function PromptEditor({
  value,
  onChange,
  onRun,
  disabled,
  running,
  attemptNumber,
  allPassed,
}) {
  function onKeyDown(e) {
    // Ctrl/Cmd+Enter submits.
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      if (!disabled) onRun();
    }
  }

  return (
    <section className="panel editor">
      <h2>Your prompt</h2>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder="Describe the function in plain English. Be precise — vague prompts produce broken code."
        disabled={running}
      />
      <div className="editor-controls">
        <div className="meta">
          {allPassed
            ? "All tests passed. Done."
            : `Attempt #${attemptNumber} · Ctrl/Cmd+Enter to run`}
        </div>
        <button className="run-button" onClick={onRun} disabled={disabled}>
          {running ? "Grading…" : "Run"}
        </button>
      </div>
    </section>
  );
}
