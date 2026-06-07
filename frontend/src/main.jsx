import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { getInitialTheme, getNextTheme, THEME_STORAGE_KEY } from "./theme";
import "./styles.css";

const WEBSOCKET_URL = "ws://localhost:8000/ws";
const API_BASE_URL = "http://localhost:8000";

const PROMISE_CARDS = [
  {
    title: "Detects pressure tactics",
    description:
      "Sentinel watches for urgency, impersonation, secrecy, and payment pressure while the call is happening.",
  },
  {
    title: "Checks suspicious claims",
    description:
      "Verifier flags claims that cannot be trusted at face value, giving families a safer pause before acting.",
  },
  {
    title: "Coaches calm responses",
    description:
      "Coach suggests plain-language replies that de-escalate the call without embarrassing the person on the line.",
  },
  {
    title: "Alerts trusted contacts",
    description:
      "Ally prepares a clear message when someone close should step in or follow up after a risky call.",
  },
];

const AGENTS = [
  {
    name: "Sentinel",
    role: "Risk watcher",
    description: "Listens for scam tactics and risk escalation in real time.",
    className: "sentinel",
  },
  {
    name: "Verifier",
    role: "Claim checker",
    description: "Marks suspicious or unverifiable statements before anyone acts on them.",
    className: "verifier",
  },
  {
    name: "Coach",
    role: "Calm response guide",
    description: "Suggests safer things to say when the conversation gets tense.",
    className: "coach",
  },
  {
    name: "Ally",
    role: "Trusted-contact bridge",
    description: "Prepares a concise alert when help from family or a friend is needed.",
    className: "ally",
  },
  {
    name: "Scribe",
    role: "Incident recorder",
    description: "Captures the useful details needed for review and reports.",
    className: "scribe",
  },
];

const PROTECTION_STEPS = [
  {
    label: "Listen",
    title: "The call stays in motion",
    description:
      "The Nightwatchman listens for signals of manipulation without forcing the caller into a complicated workflow.",
  },
  {
    label: "Verify",
    title: "Claims get a second look",
    description:
      "Suspicious statements are checked and labeled so the person on the call can slow down safely.",
  },
  {
    label: "Support",
    title: "Help arrives clearly",
    description:
      "Coaching, ally alerts, and reports turn a stressful moment into a guided response.",
  },
];

function getRiskColor(score) {
  if (score > 0.7) {
    return "#dc2626";
  }

  if (score >= 0.4) {
    return "#d97706";
  }

  return "#0f766e";
}

function getRiskLevel(score) {
  if (score > 0.7) {
    return "high";
  }

  if (score >= 0.4) {
    return "elevated";
  }

  return "calm";
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
    return { label: "Unverifiable claim", className: "verification-tag verification-tag-warning" };
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
  const [theme, setTheme] = useState(() =>
    getInitialTheme({
      savedTheme: window.localStorage.getItem(THEME_STORAGE_KEY),
      systemPrefersDark: window.matchMedia("(prefers-color-scheme: dark)").matches,
    }),
  );

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

  function handleToggleTheme() {
    setTheme((current) => getNextTheme(current));
  }

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  }, [theme]);

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
  const riskLevel = getRiskLevel(riskScore);
  const riskPercent = useMemo(() => `${Math.min(riskScore, 1) * 100}%`, [riskScore]);
  const verifiedCount = utterances.filter((utterance) => utterance.verificationVerdict).length;
  const agentActivity = {
    Sentinel: connectionStatus === "connected" || utterances.length > 0,
    Verifier: verifiedCount > 0,
    Coach: Boolean(coachingTip),
    Ally: Boolean(allyAlert),
    Scribe: utterances.length > 0 || Boolean(callOutcome),
  };
  const systemReadiness =
    connectionStatus === "connected" ? "Ready to protect" : "Waiting for backend";

  return (
    <main className={`app risk-${riskLevel}`}>
      <div className="living-signal" aria-hidden="true">
        <span className="signal-ring signal-ring-one" />
        <span className="signal-ring signal-ring-two" />
        <span className="signal-ring signal-ring-three" />
        <span className="signal-node signal-node-one" />
        <span className="signal-node signal-node-two" />
        <span className="signal-node signal-node-three" />
      </div>

      <nav className="site-nav" aria-label="Primary navigation">
        <a className="brand" href="#top" aria-label="The Nightwatchman home">
          <span className="brand-mark">N</span>
          <span>The Nightwatchman</span>
        </a>
        <div className="nav-links">
          <a href="#product">Product</a>
          <a href="#agents">Agents</a>
          <a href="#console">Live Console</a>
          <a href="#trust">Trust</a>
        </div>
        <button className="theme-toggle" onClick={handleToggleTheme} type="button">
          <span>{theme === "dark" ? "Dark" : "Light"}</span>
          <span className="theme-toggle-track" aria-hidden="true">
            <span className="theme-toggle-thumb" />
          </span>
        </button>
      </nav>

      <section className="hero-section" id="top">
        <div className="hero-copy">
          <p className="eyebrow">Family-first call protection</p>
          <h1>A trusted voice beside every call.</h1>
          <p className="hero-subtitle">
            The Nightwatchman listens for scam tactics, checks suspicious claims,
            coaches safer responses, and prepares trusted-contact alerts when a
            call starts to feel wrong.
          </p>
          <div className="hero-actions">
            <button
              className="primary-button"
              disabled={isStartingCall || connectionStatus !== "connected"}
              onClick={handleStartLiveCall}
              type="button"
            >
              {isStartingCall ? "Getting ready..." : "Start live monitoring"}
            </button>
            <a className="secondary-button" href="#agents">
              Meet the agents
            </a>
          </div>
        </div>

        <aside className="hero-orbit-card" aria-label="Live system preview">
          <div className="orbit-core">
            <span className="orbit-pulse" />
            <strong>{Math.round(Math.min(riskScore, 1) * 100)}%</strong>
            <span>Live risk</span>
          </div>
          <div className="orbit-card-row">
            <span>Status</span>
            <strong className={`status-text ${connectionStatus}`}>{connectionStatus}</strong>
          </div>
          <div className="orbit-card-row">
            <span>System</span>
            <strong>{systemReadiness}</strong>
          </div>
          <div className="orbit-card-row">
            <span>Agents active</span>
            <strong>{Object.values(agentActivity).filter(Boolean).length}/5</strong>
          </div>
        </aside>
      </section>

      <section className="promise-grid section-panel" id="product" aria-label="Product capabilities">
        {PROMISE_CARDS.map((card) => (
          <article className="promise-card" key={card.title}>
            <span className="promise-icon" />
            <h2>{card.title}</h2>
            <p>{card.description}</p>
          </article>
        ))}
      </section>

      <section className="agents-section section-panel" id="agents">
        <div className="section-heading">
          <p className="eyebrow">Multi-agent protection</p>
          <h2>A coordinated safety team, not a single chatbot.</h2>
          <p>
            Each agent has a focused job, and the interface shows them as a calm
            constellation around the call instead of a noisy technical diagram.
          </p>
        </div>

        <div className="agent-constellation">
          <div className="agent-call-core">
            <span className="call-core-ring" />
            <strong>Live call</strong>
            <span>{utterances.length || "No"} moments tracked</span>
          </div>
          {AGENTS.map((agent) => (
            <article
              className={`agent-node ${agent.className} ${
                agentActivity[agent.name] ? "active" : ""
              }`}
              key={agent.name}
              tabIndex="0"
            >
              <span className="agent-status-dot" />
              <p>{agent.role}</p>
              <h3>{agent.name}</h3>
              <span>{agent.description}</span>
            </article>
          ))}
        </div>
      </section>

      <section className="steps-section" aria-label="How protection works">
        {PROTECTION_STEPS.map((step, index) => (
          <article className="step-card" key={step.label}>
            <span className="step-number">{String(index + 1).padStart(2, "0")}</span>
            <p>{step.label}</p>
            <h2>{step.title}</h2>
            <span>{step.description}</span>
          </article>
        ))}
      </section>

      <section className="console-section" id="console">
        <div className="section-heading">
          <p className="eyebrow">Live console</p>
          <h2>Real-time protection, redesigned for calm decisions.</h2>
        </div>

        <div className="console-grid">
          <div className="console-main">
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

            <section className="glass-panel call-control-panel">
              <div>
                <p className="eyebrow">Monitoring controls</p>
                <h2>Start when the call begins. End when it is safe.</h2>
              </div>
              <div className="call-actions">
                <button
                  className="primary-button compact"
                  disabled={isStartingCall || connectionStatus !== "connected"}
                  onClick={handleStartLiveCall}
                  type="button"
                >
                  {isStartingCall ? "Getting ready..." : "Start live monitoring"}
                </button>
                <button
                  className="danger-button compact"
                  disabled={isEndingCall || Boolean(callOutcome)}
                  onClick={handleEndCall}
                  type="button"
                >
                  {isEndingCall ? "Ending call..." : "End call"}
                </button>
              </div>
            </section>

            <section className="glass-panel transcript-panel">
              <div className="panel-header">
                <div>
                  <p className="eyebrow">Transcript</p>
                  <h2>What the agents are hearing</h2>
                </div>
                <span className="count-pill">{utterances.length} entries</span>
              </div>
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
          </div>

          <aside className="console-sidebar">
            <section className="glass-panel risk-panel">
              <div className="panel-header">
                <div>
                  <p className="eyebrow">Live risk</p>
                  <h2>{riskScore.toFixed(2)}</h2>
                </div>
                <span className={`status ${connectionStatus}`}>{connectionStatus}</span>
              </div>
              <div className="gauge">
                <div
                  className="gauge-fill"
                  style={{ width: riskPercent, backgroundColor: riskColor }}
                />
              </div>
              <p className="risk-caption">
                Signal intensity stays calm until the call shows sustained pressure or
                suspicious claims.
              </p>
            </section>

            {riskScore > 0.7 && (
              <section className="warning-card">Possible scam in progress</section>
            )}

            {coachingTip && (
              <section className="coaching-card">
                <p className="eyebrow">Coach suggests</p>
                <strong>{coachingTip}</strong>
              </section>
            )}

            {allyAlert && (
              <section className="ally-card">
                <div className="ally-card-header">
                  <div>
                    <p className="eyebrow">Ally alert ready</p>
                    <strong>{allyAlert}</strong>
                  </div>
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
          </aside>
        </div>
      </section>

      <section className="trust-section section-panel" id="trust">
        <div>
          <p className="eyebrow">Trust and privacy</p>
          <h2>Built to support families without turning every call into an incident.</h2>
        </div>
        <p>
          Clean conversations can be cleared, reports are created only when needed,
          and the interface keeps the person on the call focused on the next safe
          action.
        </p>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
