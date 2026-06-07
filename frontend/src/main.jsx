import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const WEBSOCKET_URL = "ws://localhost:8000/ws";
const API_BASE_URL = "http://localhost:8000";

function getRiskColor(score) {
  if (score > 0.7) {
    return "#ef4444";
  }

  if (score >= 0.4) {
    return "#f59e0b";
  }

  return "#22c55e";
}

function buildUtterance(alert) {
  return {
    id: alert.message_id,
    text: alert.text,
    tactic: alert.tactic,
    score: Number(alert.score ?? 0),
    playbookMatch: alert.playbook_match ?? "",
  };
}

function App() {
  const [connectionStatus, setConnectionStatus] = useState("connecting");
  const [knownScammerMessage, setKnownScammerMessage] = useState("");
  const [coachingTip, setCoachingTip] = useState("");
  const [utterances, setUtterances] = useState([]);
  const [riskScore, setRiskScore] = useState(0);
  const [callOutcome, setCallOutcome] = useState(null);
  const [isStartingCall, setIsStartingCall] = useState(false);
  const [isEndingCall, setIsEndingCall] = useState(false);

  function applyAlert(alert) {
    const nextScore = Number(alert.score ?? 0);
    setRiskScore((current) => Math.max(current, nextScore));
    setUtterances((current) => {
      const utterance = buildUtterance(alert);
      const withoutDuplicate = current.filter((item) => item.id !== utterance.id);
      return [...withoutDuplicate, utterance].slice(-10);
    });
  }

  async function handleStartSimulation() {
    setIsStartingCall(true);
    setCallOutcome(null);
    setCoachingTip("");
    setUtterances([]);
    setRiskScore(0);

    try {
      const response = await fetch(`${API_BASE_URL}/simulate`, { method: "POST" });
      if (!response.ok) {
        throw new Error("Simulation failed to start");
      }
    } catch {
      setCallOutcome({
        status: "error",
        message: "Could not start the simulation. Is the backend running?",
      });
    } finally {
      setIsStartingCall(false);
    }
  }

  async function handleEndCall() {
    setIsEndingCall(true);
    try {
      const response = await fetch(`${API_BASE_URL}/end-call`, { method: "POST" });
      if (!response.ok) {
        throw new Error("End call failed");
      }
      const result = await response.json();
      setCallOutcome(result);
    } catch {
      setCallOutcome({
        status: "error",
        message: "Could not finalize the call. Please try again.",
      });
    } finally {
      setIsEndingCall(false);
    }
  }

  useEffect(() => {
    const socket = new WebSocket(WEBSOCKET_URL);

    socket.addEventListener("open", () => {
      setConnectionStatus("connected");
    });

    socket.addEventListener("message", (event) => {
      let alert;
      try {
        alert = JSON.parse(event.data);
      } catch {
        return;
      }

      if (alert.type === "known_scammer") {
        setKnownScammerMessage(alert.message);
        return;
      }

      if (alert.type === "coaching_tip") {
        setCoachingTip(alert.tip);
        return;
      }

      if (alert.message_id) {
        applyAlert(alert);
      }
    });

    socket.addEventListener("close", () => {
      setConnectionStatus("disconnected");
    });

    socket.addEventListener("error", () => {
      setConnectionStatus("error");
    });

    return () => {
      socket.close();
    };
  }, []);

  const riskColor = getRiskColor(riskScore);
  const riskPercent = useMemo(() => `${Math.min(riskScore, 1) * 100}%`, [riskScore]);

  return (
    <main className="app">
      {knownScammerMessage && (
        <section className="known-scammer-banner">{knownScammerMessage}</section>
      )}

      {callOutcome?.status === "scam" && (
        <section className="scam-confirmed-banner">
          <p>{callOutcome.message || "Scam confirmed. Download your incident report."}</p>
          <a
            className="download-button"
            href={`${API_BASE_URL}/download-report/${callOutcome.timestamp}`}
            target="_blank"
            rel="noreferrer"
          >
            Download report
          </a>
        </section>
      )}

      {callOutcome?.status === "clean" && (
        <section className="clean-call-banner">
          {callOutcome.message ||
            "No scam detected. Your conversation was private and has been deleted."}
        </section>
      )}

      {callOutcome?.status === "error" && (
        <section className="error-banner">{callOutcome.message}</section>
      )}

      <section className="panel hero">
        <div>
          <p className="eyebrow">Guardian</p>
          <h1>Real-time scam call defense</h1>
        </div>
        <span className={`status ${connectionStatus}`}>{connectionStatus}</span>
      </section>

      <section className="panel call-actions">
        <button
          className="start-call-button"
          disabled={isStartingCall || connectionStatus !== "connected"}
          onClick={handleStartSimulation}
          type="button"
        >
          {isStartingCall ? "Starting call..." : "Start simulation"}
        </button>
        <button
          className="end-call-button"
          disabled={isEndingCall || Boolean(callOutcome)}
          onClick={handleEndCall}
          type="button"
        >
          {isEndingCall ? "Ending call..." : "End call"}
        </button>
      </section>

      <section className="panel">
        <div className="risk-header">
          <h2>Live Risk</h2>
          <strong>{riskScore.toFixed(2)}</strong>
        </div>
        <div className="gauge">
          <div
            className="gauge-fill"
            style={{ width: riskPercent, backgroundColor: riskColor }}
          />
        </div>
      </section>

      {riskScore > 0.7 && (
        <section className="warning-card">
          Warning: possible scam in progress
        </section>
      )}

      <section className="panel">
        <h2>Transcript</h2>
        <div className="transcript">
          {utterances.length === 0 ? (
            <p className="empty">Click Start simulation to begin a demo call...</p>
          ) : (
            utterances.map((utterance) => (
              <article className="utterance" key={utterance.id}>
                <p>{utterance.text}</p>
                <div className="utterance-meta">
                  <span>
                    {utterance.tactic} · {utterance.score.toFixed(2)}
                  </span>
                  {utterance.playbookMatch && (
                    <span className="playbook-tag">
                      Matches: {utterance.playbookMatch}
                    </span>
                  )}
                </div>
              </article>
            ))
          )}
        </div>
      </section>

      {coachingTip && (
        <section className="coaching-card">You could say: {coachingTip}</section>
      )}
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
