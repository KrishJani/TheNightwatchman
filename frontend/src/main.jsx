import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const WEBSOCKET_URL = "ws://localhost:8000/ws";

function getRiskColor(score) {
  if (score > 0.7) {
    return "#ef4444";
  }

  if (score >= 0.4) {
    return "#f59e0b";
  }

  return "#22c55e";
}

function App() {
  const [connectionStatus, setConnectionStatus] = useState("connecting");
  const [knownScammerMessage, setKnownScammerMessage] = useState("");
  const [coachingTip, setCoachingTip] = useState("");
  const [utterances, setUtterances] = useState([]);
  const [riskScore, setRiskScore] = useState(0);

  useEffect(() => {
    const socket = new WebSocket(WEBSOCKET_URL);

    socket.addEventListener("open", () => {
      setConnectionStatus("connected");
    });

    socket.addEventListener("message", (event) => {
      const alert = JSON.parse(event.data);
      if (alert.type === "known_scammer") {
        setKnownScammerMessage(alert.message);
        return;
      }

      if (alert.type === "coaching_tip") {
        setCoachingTip(alert.tip);
        return;
      }

      const nextScore = Number(alert.score ?? 0);

      setRiskScore(nextScore);
      setUtterances((current) =>
        [
          ...current,
          {
            id: alert.message_id,
            text: alert.text,
            tactic: alert.tactic,
            score: nextScore,
            playbookMatch: alert.playbook_match ?? "",
          },
        ].slice(-10),
      );
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

      <section className="panel hero">
        <div>
          <p className="eyebrow">Guardian</p>
          <h1>Real-time scam call defense</h1>
        </div>
        <span className={`status ${connectionStatus}`}>{connectionStatus}</span>
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
            <p className="empty">Waiting for call activity...</p>
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
