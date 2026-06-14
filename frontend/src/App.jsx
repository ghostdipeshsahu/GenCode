import { useEffect, useState } from "react";
import ProblemPanel from "./components/ProblemPanel.jsx";
import PromptEditor from "./components/PromptEditor.jsx";
import ResultsPanel from "./components/ResultsPanel.jsx";
import AttemptHistory from "./components/AttemptHistory.jsx";

export default function App() {
  const [questions, setQuestions] = useState([]); // [{id, title}, ...]
  const [selectedId, setSelectedId] = useState(null);
  const [question, setQuestion] = useState(null);
  const [loadError, setLoadError] = useState(null);

  const [prompt, setPrompt] = useState("");
  const [attempts, setAttempts] = useState([]);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState(null);

  // Load the question list once at mount; select the first one.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const list = await fetch("/api/questions").then((r) => {
          if (!r.ok) throw new Error(`/api/questions returned ${r.status}`);
          return r.json();
        });
        if (cancelled) return;
        if (!list.length) throw new Error("no questions configured on backend");
        setQuestions(list);
        setSelectedId(list[0].id);
      } catch (err) {
        if (!cancelled) setLoadError(err.message || String(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Load the selected question and reset session state whenever the
  // selection changes.
  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    setQuestion(null);
    setPrompt("");
    setAttempts([]);
    setRunError(null);
    (async () => {
      try {
        const q = await fetch(`/api/question/${selectedId}`).then((r) => {
          if (!r.ok) throw new Error(`/api/question/${selectedId} returned ${r.status}`);
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
  }, [selectedId]);

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

      {questions.length > 0 && (
        <div className="question-picker">
          <label htmlFor="qpicker">Question</label>
          <select
            id="qpicker"
            value={selectedId || ""}
            onChange={(e) => setSelectedId(e.target.value)}
            disabled={running}
          >
            {questions.map((q) => (
              <option key={q.id} value={q.id}>
                {q.id} — {q.title}
              </option>
            ))}
          </select>
        </div>
      )}

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
