import { useEffect, useState } from "react";
import ProblemPanel from "./components/ProblemPanel.jsx";
import PromptEditor from "./components/PromptEditor.jsx";
import ResultsPanel from "./components/ResultsPanel.jsx";
import AttemptHistory from "./components/AttemptHistory.jsx";

export default function App() {
  const [question, setQuestion] = useState(null);
  const [loadError, setLoadError] = useState(null);

  const [prompt, setPrompt] = useState("");
  const [attempts, setAttempts] = useState([]);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState(null);

  // Load the first available question on mount.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const list = await fetch("/api/questions").then((r) => {
          if (!r.ok) throw new Error(`/api/questions returned ${r.status}`);
          return r.json();
        });
        if (!list.length) throw new Error("no questions configured on backend");
        const first = list[0];
        const q = await fetch(`/api/question/${first.id}`).then((r) => {
          if (!r.ok) throw new Error(`/api/question/${first.id} returned ${r.status}`);
          return r.json();
        });
        if (!cancelled) setQuestion(q);
      } catch (err) {
        if (!cancelled) setLoadError(err.message || String(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const latest = attempts.length ? attempts[attempts.length - 1] : null;
  const allPassed = latest?.response?.all_passed === true;

  async function handleRun() {
    if (!question || running) return;
    const trimmed = prompt.trim();
    if (!trimmed) {
      setRunError("write a prompt first");
      return;
    }
    setRunError(null);
    setRunning(true);
    const attemptNumber = attempts.length + 1;
    try {
      const resp = await fetch("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question_id: question.id,
          student_prompt: trimmed,
          attempt_number: attemptNumber,
        }),
      });
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(`server returned ${resp.status}: ${text}`);
      }
      const data = await resp.json();
      setAttempts((prev) => [
        ...prev,
        { attemptNumber, prompt: trimmed, response: data },
      ]);
    } catch (err) {
      setRunError(err.message || String(err));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="app">
      <header>
        <h1>GenCode</h1>
        <p>Teach the AI. Write prompts so precise that a literal model produces correct code.</p>
      </header>

      {loadError && <div className="error-bar">Could not load question: {loadError}</div>}

      {!loadError && !question && <div className="loading">Loading question…</div>}

      {question && (
        <>
          <ProblemPanel question={question} />

          <PromptEditor
            value={prompt}
            onChange={setPrompt}
            onRun={handleRun}
            disabled={running || allPassed}
            running={running}
            attemptNumber={attempts.length + 1}
            allPassed={allPassed}
          />

          {runError && <div className="error-bar">{runError}</div>}

          {latest && (
            <ResultsPanel
              attemptNumber={latest.attemptNumber}
              response={latest.response}
            />
          )}

          <AttemptHistory attempts={attempts} />
        </>
      )}
    </div>
  );
}
