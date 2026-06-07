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
    tactic: alert.tactic ?? "ANALYZING",
    score: Number(alert.score ?? 0),
    playbookMatch: alert.playbook_match ?? "",
    verificationVerdict: "",
  };
}

function getVerificationTag(verdict) {
  if (verdict === "CREDIBLE") {
    return { label: "Claim unchallenged", className: "verification-tag verification-tag-neutral" };
  }

  if (verdict === "SUSPICIOUS" || verdict === "UNVERIFIABLE") {
    return { label: "⚠ Unverifiable claim", className: "verification-tag verification-tag-warning" };
  }

  return null;
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
  const [allyAlert, setAllyAlert] = useState("");
  const [allyCopied, setAllyCopied] = useState(false);

  function applyAlert(alert) {
    const nextScore = Number(alert.score ?? 0);
    setRiskScore((current) => Math.max(current, nextScore));
    setUtterances((current) => {
      const utterance = buildUtterance(alert);
      const existing = current.find((item) => item.id === utterance.id);
      const merged = existing ? { ...existing, ...utterance } : utterance;
      const withoutDuplicate = current.filter((item) => item.id !== merged.id);
      return [...withoutDuplicate, merged].slice(-10);
    });
  }

  function applyTranscript(transcript) {
    setUtterances((current) => {
      const existing = current.find((item) => item.id === transcript.message_id);
      const utterance = {
        id: transcript.message_id,
        text: transcript.text,
        tactic: existing?.tactic ?? "ANALYZING",
        score: existing?.score ?? 0,
        playbookMatch: existing?.playbookMatch ?? "",
        verificationVerdict: existing?.verificationVerdict ?? "",
      };
      const withoutDuplicate = current.filter((item) => item.id !== utterance.id);
      return [...withoutDuplicate, utterance].slice(-10);
    });
  }

  async function handleStartLiveCall() {
    setIsStartingCall(true);
    setCallOutcome(null);
    setCoachingTip("");
    setAllyAlert("");
    setAllyCopied(false);
    setUtterances([]);
    setRiskScore(0);

    try {
      const response = await fetch(`${API_BASE_URL}/reset-call`, { method: "POST" });
      if (!response.ok) {
        throw new Error("Call monitoring failed to start");
      }
    } catch {
      setCallOutcome({
        status: "error",
        message: "Could not start live call monitoring. Is the backend running?",
      });
    } finally {
      setIsStartingCall(false);
    }
  }

  async function handleCopyAllyAlert() {
    if (!allyAlert) {
      return;
    }

    try {
      await navigator.clipboard.writeText(allyAlert);
      setAllyCopied(true);
      window.setTimeout(() => setAllyCopied(false), 2000);
    } catch {
      setAllyCopied(false);
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

      if (alert.type === "verification_result") {
        setUtterances((current) =>
          current.map((item) =>
            item.id === alert.message_id
              ? { ...item, verificationVerdict: alert.verdict ?? "" }
              : item,
          ),
        );
        return;
      }

      if (alert.type === "ally_alert") {
        setAllyAlert(alert.message ?? "");
        return;
      }

      if (alert.type === "transcript") {
        applyTranscript(alert);
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
          onClick={handleStartLiveCall}
          type="button"
        >
          {isStartingCall ? "Getting ready..." : "Start live monitoring"}
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
            <p className="empty">
              Click Start live monitoring, then call your Twilio number and speak.
            </p>
          ) : (
            utterances.map((utterance) => {
              const verificationTag = getVerificationTag(utterance.verificationVerdict);

              return (
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
                  {verificationTag && (
                    <span className={verificationTag.className}>
                      {verificationTag.label}
                    </span>
                  )}
                </div>
              </article>
              );
            })
          )}
        </div>
      </section>

      {coachingTip && (
        <section className="coaching-card">You could say: {coachingTip}</section>
      )}

      {allyAlert && (
        <section className="ally-card">
          <div className="ally-card-header">
            <p className="ally-card-title">Ally Alert Ready: {allyAlert}</p>
            <button
              className="copy-button"
              onClick={handleCopyAllyAlert}
              type="button"
            >
              {allyCopied ? "Copied" : "Copy"}
            </button>
          </div>
          <p className="ally-card-subtext">
            In production this would be sent to your trusted contact.
          </p>
        </section>
      )}
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
