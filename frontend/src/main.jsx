import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { getInitialTheme, getNextTheme, THEME_STORAGE_KEY } from "./theme";
import "./styles.css";

const WEBSOCKET_URL = "ws://localhost:8000/ws";
const API_BASE_URL = "http://localhost:8000";
const ARCHITECTURE_URL = "https://app.eraser.io/workspace/dygGZhvvUSu03e7ZHjXt?origin=share";

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
    contribution: "Detects pressure, secrecy, urgency, and impersonation patterns.",
    className: "sentinel",
  },
  {
    name: "Verifier",
    role: "Claim checker",
    description: "Marks suspicious or unverifiable statements before anyone acts on them.",
    contribution: "Gives the family a safer pause before trusting a caller's claim.",
    className: "verifier",
  },
  {
    name: "Coach",
    role: "Calm response guide",
    description: "Suggests safer things to say when the conversation gets tense.",
    contribution: "Turns risk into a composed next sentence.",
    className: "coach",
  },
  {
    name: "Ally",
    role: "Trusted-contact bridge",
    description: "Prepares a concise alert when help from family or a friend is needed.",
    contribution: "Brings in the right person without creating panic.",
    className: "ally",
  },
  {
    name: "Scribe",
    role: "Incident recorder",
    description: "Captures the useful details needed for review and reports.",
    contribution: "Documents only what matters for follow-up and recovery.",
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
    speaker: alert.speaker ?? "caller",
    timestamp: alert.timestamp ?? Date.now() / 1000,
    tactic: alert.tactic ?? "ANALYZING",
    score: Number(alert.score ?? 0),
    playbookMatch: alert.playbook_match ?? "",
    verificationVerdict: "",
    coachingTip: "",
  };
}

function formatTacticLabel(tactic) {
  if (!tactic || tactic === "ANALYZING") {
    return "Analyzing…";
  }

  if (tactic === "NONE") {
    return "No risk detected";
  }

  return tactic
    .toLowerCase()
    .split("_")
    .join(" ")
    .replace(/^\w/, (character) => character.toUpperCase());
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

function formatLabel(value) {
  return String(value ?? "")
    .toLowerCase()
    .split("_")
    .join(" ")
    .replace(/^\w/, (character) => character.toUpperCase());
}

function formatTimestamp(timestamp) {
  if (!timestamp) {
    return "";
  }

  const date = new Date(Number(timestamp) * 1000);
  if (Number.isNaN(date.getTime())) {
    return "";
  }

  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatPercent(value) {
  return `${Math.round(Number(value ?? 0) * 100)}%`;
}

function RedisKey({ children }) {
  return <code className="redis-key">{children}</code>;
}

function RedisCard({ title, subtitle, redisKey, variant = "", children }) {
  return (
    <article className={`redis-card ${variant}`}>
      <div className="redis-card-heading">
        <div>
          <h2>{title}</h2>
          <p>{subtitle}</p>
        </div>
        {redisKey && <RedisKey>{redisKey}</RedisKey>}
      </div>
      {children}
    </article>
  );
}

function MetricRow({ label, value }) {
  return (
    <div className="redis-metric-row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function RedisBadge({ tone = "neutral", children }) {
  return <span className={`redis-badge ${tone}`}>{children}</span>;
}

function MiniBar({ value, max, danger = false }) {
  const width = max > 0 ? Math.max((Number(value) / max) * 100, 4) : 0;
  return (
    <span className="redis-mini-bar">
      <span
        className={danger ? "danger" : ""}
        style={{ width: `${Math.min(width, 100)}%` }}
      />
    </span>
  );
}

function RiskTimelineChart({ points }) {
  const chartPoints = points ?? [];
  const polyline = chartPoints
    .map((point, index) => {
      const x = chartPoints.length === 1 ? 50 : (index / (chartPoints.length - 1)) * 100;
      const y = 100 - Math.min(Math.max(Number(point.score ?? 0), 0), 1) * 100;
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <div className="redis-chart-frame">
      {chartPoints.length > 0 ? (
        <svg className="risk-timeline-chart" viewBox="0 0 100 100" preserveAspectRatio="none">
          <line className="danger-threshold" x1="0" x2="100" y1="30" y2="30" />
          <polyline points={polyline} />
        </svg>
      ) : (
        <p className="redis-empty">Waiting for risk timeline points.</p>
      )}
      <div className="chart-axis-labels">
        <span>0</span>
        <span>1.0</span>
      </div>
    </div>
  );
}

function RedisIntelligenceDashboard({ data, error, loading }) {
  if (loading && !data) {
    return (
      <section className="redis-intelligence-section">
        <div className="redis-dashboard-header">
          <p className="eyebrow">Redis Intelligence</p>
          <h1>Loading live Redis services...</h1>
        </div>
      </section>
    );
  }

  if (!data) {
    return (
      <section className="redis-intelligence-section">
        <div className="redis-dashboard-header">
          <p className="eyebrow">Redis Intelligence</p>
          <h1>Redis service telemetry is unavailable.</h1>
          {error && <p className="redis-error">{error}</p>}
        </div>
      </section>
    );
  }

  const topKMax = Math.max(...data.top_k.tactics.map((item) => item.count), 1);
  const phraseMax = Math.max(...data.count_min.phrases.map((item) => item.count), 1);
  const hitRate = Number(data.langcache.hit_rate_pct ?? 0);
  const latestEntry =
    data.streams.last_entry_ms_ago === null
      ? "No stream entries"
      : `${data.streams.last_entry_ms_ago} ms ago`;

  return (
    <section className="redis-intelligence-section">
      <div className="redis-dashboard-header">
        <div>
          <p className="eyebrow">Redis Intelligence</p>
          <h1>What Redis is storing for this call.</h1>
          <p>
            Live Redis keys, probabilistic structures, streams, semantic indexes,
            and cache state behind the current Guardian call.
          </p>
        </div>
        <RedisBadge tone={error ? "danger" : "success"}>
          {error ? "Refresh error" : "Auto-refreshing every 2s"}
        </RedisBadge>
      </div>

      <div className="redis-summary-strip" aria-label="Redis live summary">
        <div>
          <span>Stream length</span>
          <strong>{data.streams.total_messages}</strong>
          <RedisKey>guardian:transcript</RedisKey>
        </div>
        <div>
          <span>Latest entry</span>
          <strong>{latestEntry}</strong>
          <RedisKey>{data.hashes.last_message_id || "pending"}</RedisKey>
        </div>
        <div>
          <span>Last tactic hash</span>
          <strong>{formatLabel(data.hashes.tactic)}</strong>
          <RedisKey>guardian:tactic:{"{last_id}"}</RedisKey>
        </div>
        <div>
          <span>Risk percentile</span>
          <strong>{data.tdigest.percentile}th</strong>
          <RedisKey>tdigest:risk_distribution</RedisKey>
        </div>
      </div>

      <div className="redis-section-heading">
        <p className="eyebrow">Live wired data</p>
        <h2>Current call backbone</h2>
      </div>
      <div className="redis-card-grid">
        <RedisCard
          title="TimeSeries — Live Risk Timeline"
          subtitle="Stores one risk score per utterance and reads the last 10 points."
          redisKey="guardian:risk_timeline"
          variant="primary"
        >
          <RiskTimelineChart points={data.timeseries.points} />
        </RedisCard>

        <RedisCard title="Streams" subtitle="Stores the transcript as the append-only call event log." redisKey="guardian:transcript" variant="primary">
          <MetricRow label="Total messages" value={data.streams.total_messages} />
          <MetricRow label="Last entry" value={latestEntry} />
          <MetricRow label="Pending messages" value={data.streams.pending_messages} />
          <div className="redis-pill-row">
            {data.streams.consumer_groups.map((group) => (
              <RedisBadge tone="success" key={group}>
                {group}
              </RedisBadge>
            ))}
          </div>
        </RedisCard>

        <RedisCard title="Hashes — Agent Results" subtitle="Stores Sentinel output for the latest utterance." redisKey="guardian:tactic:{last_id}" variant="primary">
          <MetricRow label="Message ID" value={data.hashes.last_message_id || "No stream entry yet"} />
          <div className="redis-metric-row">
            <span>Tactic</span>
            <RedisBadge tone={data.hashes.tactic === "NONE" ? "neutral" : "danger"}>
              {formatLabel(data.hashes.tactic)}
            </RedisBadge>
          </div>
          <div className="redis-progress-field">
            <MetricRow label="Confidence" value={formatPercent(data.hashes.confidence)} />
            <MiniBar value={data.hashes.confidence} max={1} danger={data.hashes.confidence > 0.7} />
          </div>
          <MetricRow label="Verified" value={data.hashes.verified ? "true" : "false"} />
          <MetricRow label="Playbook match" value={data.hashes.playbook_match} />
        </RedisCard>
      </div>

      <div className="redis-section-heading">
        <p className="eyebrow">Redis capability layer</p>
        <h2>Specialized structures powering the call analysis</h2>
      </div>
      <div className="redis-card-grid">
        <RedisCard title="Bloom Filter" subtitle="Checks whether the caller appears in the known scammer set." redisKey="guardian:known_scammers">
          <div className="redis-hero-metric">
            <span>{data.bloom_filter.caller_number}</span>
            <RedisBadge tone={data.bloom_filter.result === "HIT" ? "success" : "danger"}>
              {data.bloom_filter.result}
            </RedisBadge>
          </div>
          <MetricRow label="Lookup latency" value={`${data.bloom_filter.latency_us} us`} />
          <MetricRow
            label="Configuration"
            value={`${data.bloom_filter.filter_size.toLocaleString()} capacity / ${data.bloom_filter.error_rate} error rate`}
          />
        </RedisCard>

        <RedisCard
          title="Top-K — Tactic Leaderboard"
          subtitle="Maintains the highest-frequency manipulation tactics for this caller."
          redisKey="topk:tactics"
        >
          <div className="redis-bar-list">
            {data.top_k.tactics.map((item, index) => (
              <div className="redis-bar-row" key={item.tactic}>
                <span>{formatLabel(item.tactic)}</span>
                <MiniBar value={item.count} max={topKMax} danger={index === 0} />
                <strong>{item.count}</strong>
              </div>
            ))}
          </div>
        </RedisCard>

        <RedisCard
          title="Count-Min Sketch — Phrase Frequency"
          subtitle="Estimates trigger phrase counts without storing every phrase occurrence."
          redisKey="cms:trigger_phrases"
        >
          <div className="redis-table">
            {data.count_min.phrases.map((item) => (
              <div className="redis-table-row" key={item.phrase}>
                <span>{item.phrase}</span>
                <strong>{item.count}</strong>
                <MiniBar value={item.count} max={phraseMax} />
              </div>
            ))}
          </div>
        </RedisCard>

        <RedisCard
          title="t-digest — Risk Distribution"
          subtitle="Compares this call's risk against historical call scores."
          redisKey="tdigest:risk_distribution"
        >
          <div className="redis-percentile">{data.tdigest.percentile}th percentile</div>
          <p className="redis-muted">{data.tdigest.label}</p>
          <div className="redis-stat-grid">
            <MetricRow label="p50" value={data.tdigest.p50} />
            <MetricRow label="p90" value={data.tdigest.p90} />
            <MetricRow label="p99" value={data.tdigest.p99} />
          </div>
        </RedisCard>

        <RedisCard
          title="Vector Sets — Playbook Match"
          subtitle="Matches utterances to scam playbooks with vector search and keyword ranking."
          redisKey="guardian:playbooks"
        >
          <blockquote>&ldquo;{data.vector_search.utterance}&rdquo;</blockquote>
          <MetricRow label="Matched playbook" value={data.vector_search.matched_playbook} />
          <MetricRow label="Similarity" value={formatPercent(data.vector_search.similarity_score)} />
          <MetricRow label="Rank method" value={data.vector_search.rank_method} />
          <MetricRow label="Latency" value={`${data.vector_search.latency_ms} ms`} />
        </RedisCard>

        <RedisCard title="LangCache — Semantic Cache" subtitle="Reuses semantically similar LLM responses instead of recomputing them." redisKey="langcache:coach">
          <div className="redis-cache-layout">
            <div className="redis-donut" style={{ "--hit-rate": `${hitRate}%` }}>
              <span>{hitRate}%</span>
            </div>
            <div>
              <p className="redis-muted">{data.langcache.last_hit}</p>
              <MetricRow label="Requests" value={data.langcache.total_requests} />
              <MetricRow label="Cache hits" value={data.langcache.cache_hits} />
            </div>
          </div>
          <MetricRow
            label="Hit vs miss latency"
            value={`${data.langcache.avg_hit_latency_ms} ms / ${data.langcache.avg_miss_latency_ms} ms`}
          />
        </RedisCard>

        <RedisCard title="Agent Memory" subtitle="Persists caller-specific context across separate calls." redisKey="memory:caller:{number}">
          <MetricRow label="Caller" value={data.agent_memory.caller_number} />
          <MetricRow label="Times seen" value={data.agent_memory.times_seen} />
          <MetricRow label="Last scam type" value={data.agent_memory.last_scam_type} />
          <div className="redis-pill-row">
            {data.agent_memory.known_contacts.map((contact) => (
              <RedisBadge key={contact}>{contact}</RedisBadge>
            ))}
          </div>
          <p className="redis-muted">{data.agent_memory.notes}</p>
        </RedisCard>

        <RedisCard title="Pub/Sub — Alert Channel" subtitle="Broadcasts real-time tactic alerts to connected dashboard clients." redisKey="guardian:alerts">
          <MetricRow label="Channel" value={data.pubsub.channel} />
          <MetricRow label="Messages published" value={data.pubsub.messages_published} />
          <pre className="redis-json">{JSON.stringify(data.pubsub.last_message, null, 2)}</pre>
        </RedisCard>

        <RedisCard
          title="RDI — Redis Data Integration"
          subtitle="Syncs external scammer blocklist records into Redis."
          redisKey="rdi:scammer_blocklist"
        >
          <MetricRow label="Source" value={data.rdi.source} />
          <div className="redis-metric-row">
            <span>Status</span>
            <RedisBadge tone="success">{data.rdi.status.toUpperCase()}</RedisBadge>
          </div>
          <MetricRow label="Last sync" value={data.rdi.last_sync} />
          <MetricRow label="Records synced" value={data.rdi.records_synced} />
          <MetricRow label="Mode" value={data.rdi.mode} />
        </RedisCard>
      </div>
    </section>
  );
}

function App() {
  const [connectionStatus, setConnectionStatus] = useState("connecting");
  const [knownScammerMessage, setKnownScammerMessage] = useState("");
  const [coachingTip, setCoachingTip] = useState("");
  const [utterances, setUtterances] = useState([]);
  const [riskScore, setRiskScore] = useState(0);
  const [callOutcome, setCallOutcome] = useState(null);
  const [isStartingCall, setIsStartingCall] = useState(false);
  const [isSimulating, setIsSimulating] = useState(false);
  const [isMicCallActive, setIsMicCallActive] = useState(false);
  const [micDenied, setMicDenied] = useState(false);
  const [twilioConfigured, setTwilioConfigured] = useState(false);
  const [twilioCallActive, setTwilioCallActive] = useState(false);
  const [isCallSessionActive, setIsCallSessionActive] = useState(false);
  const [isEndingCall, setIsEndingCall] = useState(false);
  const [allyAlert, setAllyAlert] = useState("");
  const [allyCopied, setAllyCopied] = useState(false);
  const [activeTab, setActiveTab] = useState("home");
  const [redisIntelligence, setRedisIntelligence] = useState(null);
  const [redisIntelligenceError, setRedisIntelligenceError] = useState("");
  const [isRedisIntelligenceLoading, setIsRedisIntelligenceLoading] = useState(false);
  const callerTranscriptEndRef = useRef(null);
  const victimTranscriptEndRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const mediaStreamRef = useRef(null);
  const micRecordingActiveRef = useRef(false);
  const micChunkTimerRef = useRef(null);
  const micChunksRef = useRef([]);
  const micMimeTypeRef = useRef("");
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
      // Preserve fields that arrive on other events (verification, coaching)
      // so a later risk update does not wipe them out.
      const merged = existing
        ? {
            ...existing,
            ...utterance,
            speaker: existing.speaker ?? utterance.speaker,
            verificationVerdict: existing.verificationVerdict,
            coachingTip: existing.coachingTip,
          }
        : utterance;
      const withoutDuplicate = current.filter((item) => item.id !== merged.id);
      return [...withoutDuplicate, merged].slice(-40);
    });
  }

  function applyTranscriptRetract(retract) {
    if (!retract.message_id) {
      return;
    }

    setUtterances((current) =>
      current.filter((item) => item.id !== retract.message_id),
    );
  }

  function applyTranscript(transcript) {
    setUtterances((current) => {
      const existing = current.find((item) => item.id === transcript.message_id);
      const speaker = transcript.speaker ?? "caller";
      const utterance = {
        id: transcript.message_id,
        text: transcript.text,
        speaker,
        timestamp: transcript.timestamp ?? existing?.timestamp ?? Date.now() / 1000,
        tactic: existing?.tactic ?? (speaker === "caller" ? "ANALYZING" : ""),
        score: existing?.score ?? 0,
        playbookMatch: existing?.playbookMatch ?? "",
        verificationVerdict: existing?.verificationVerdict ?? "",
        coachingTip: existing?.coachingTip ?? "",
      };
      const withoutDuplicate = current.filter((item) => item.id !== utterance.id);
      return [...withoutDuplicate, utterance].slice(-40);
    });
  }

  async function uploadMicChunk(blob, filename) {
    if (blob.size < 500) {
      return;
    }

    const formData = new FormData();
    formData.append("audio", blob, filename);

    try {
      await fetch(`${API_BASE_URL}/transcribe-user`, {
        method: "POST",
        body: formData,
      });
    } catch {
      // Keep recording even if a chunk upload fails.
    }
  }

  function scheduleMicChunkStop() {
    if (micChunkTimerRef.current) {
      window.clearTimeout(micChunkTimerRef.current);
    }

    micChunkTimerRef.current = window.setTimeout(() => {
      const recorder = mediaRecorderRef.current;
      if (recorder && recorder.state === "recording") {
        recorder.stop();
      }
    }, 3000);
  }

  function startMicRecordingCycle() {
    const recorder = mediaRecorderRef.current;
    if (!recorder || !micRecordingActiveRef.current || recorder.state !== "inactive") {
      return;
    }

    micChunksRef.current = [];
    recorder.start();
    scheduleMicChunkStop();
  }

  function stopMicrophoneCapture() {
    micRecordingActiveRef.current = false;

    if (micChunkTimerRef.current) {
      window.clearTimeout(micChunkTimerRef.current);
      micChunkTimerRef.current = null;
    }

    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      mediaRecorderRef.current.stop();
    }
    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    mediaRecorderRef.current = null;
    mediaStreamRef.current = null;
    micChunksRef.current = [];
    micMimeTypeRef.current = "";
    setIsMicCallActive(false);
  }

  async function handleSimulate() {
    stopMicrophoneCapture();
    setMicDenied(false);
    setTwilioCallActive(false);
    setIsCallSessionActive(true);
    setIsSimulating(true);
    setCallOutcome(null);
    setCoachingTip("");
    setAllyAlert("");
    setAllyCopied(false);
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
        message: "Could not start simulation. Is the backend running?",
      });
    } finally {
      setIsSimulating(false);
    }
  }

  async function handleStartCall() {
    setIsStartingCall(true);
    setCallOutcome(null);
    setCoachingTip("");
    setAllyAlert("");
    setAllyCopied(false);
    setUtterances([]);
    setRiskScore(0);
    setMicDenied(false);
    setTwilioCallActive(false);
    stopMicrophoneCapture();

    try {
      const response = await fetch(`${API_BASE_URL}/reset-call`, { method: "POST" });
      if (!response.ok) {
        throw new Error("Call failed to start");
      }

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaStreamRef.current = stream;

      const preferredTypes = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
      const mimeType = preferredTypes.find((type) => MediaRecorder.isTypeSupported(type));
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      mediaRecorderRef.current = recorder;
      micMimeTypeRef.current = recorder.mimeType || mimeType || "audio/webm";
      micRecordingActiveRef.current = true;

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          micChunksRef.current.push(event.data);
        }
      };

      recorder.onstop = async () => {
        const chunks = micChunksRef.current;
        micChunksRef.current = [];

        if (chunks.length > 0) {
          const blob = new Blob(chunks, { type: micMimeTypeRef.current });
          const filename = micMimeTypeRef.current.includes("mp4") ? "chunk.mp4" : "chunk.webm";
          await uploadMicChunk(blob, filename);
        }

        if (micRecordingActiveRef.current) {
          startMicRecordingCycle();
        }
      };

      startMicRecordingCycle();
      setIsMicCallActive(true);
      setIsCallSessionActive(true);

      if (twilioConfigured) {
        try {
          const twilioResponse = await fetch(`${API_BASE_URL}/start-twilio-call`, {
            method: "POST",
          });
          if (twilioResponse.ok) {
            setTwilioCallActive(true);
          } else {
            const errorBody = await twilioResponse.json().catch(() => ({}));
            setCallOutcome({
              status: "error",
              message:
                errorBody.detail ||
                "Twilio call failed to start. Microphone-only mode is active.",
            });
          }
        } catch {
          setCallOutcome({
            status: "error",
            message: "Twilio call failed to start. Microphone-only mode is active.",
          });
        }
      }
    } catch (error) {
      stopMicrophoneCapture();
      setIsCallSessionActive(false);
      setTwilioCallActive(false);
      if (error?.name === "NotAllowedError" || error?.name === "PermissionDeniedError") {
        setMicDenied(true);
      } else {
        setCallOutcome({
          status: "error",
          message:
            error?.message || "Could not start call with microphone. Is the backend running?",
        });
      }
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
    stopMicrophoneCapture();
    setTwilioCallActive(false);
    setIsMicCallActive(false);
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
      setIsCallSessionActive(false);
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

  const callerUtterances = useMemo(
    () => utterances.filter((utterance) => utterance.speaker !== "victim"),
    [utterances],
  );
  const victimUtterances = useMemo(
    () => utterances.filter((utterance) => utterance.speaker === "victim"),
    [utterances],
  );

  useEffect(() => {
    callerTranscriptEndRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [callerUtterances.length]);

  useEffect(() => {
    victimTranscriptEndRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [victimUtterances.length]);

  useEffect(() => {
    return () => {
      stopMicrophoneCapture();
    };
  }, []);

  useEffect(() => {
    let isCancelled = false;

    async function fetchTwilioStatus() {
      try {
        const response = await fetch(`${API_BASE_URL}/twilio-status`);
        if (!response.ok) {
          return;
        }
        const result = await response.json();
        if (!isCancelled) {
          setTwilioConfigured(Boolean(result.configured));
        }
      } catch {
        if (!isCancelled) {
          setTwilioConfigured(false);
        }
      }
    }

    fetchTwilioStatus();

    return () => {
      isCancelled = true;
    };
  }, []);

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
        const tip = alert.tip ?? "";
        if (!tip) {
          return;
        }
        setCoachingTip(tip);
        if (alert.message_id) {
          setUtterances((current) =>
            current.map((item) =>
              item.id === alert.message_id ? { ...item, coachingTip: tip } : item,
            ),
          );
        }
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

      if (alert.type === "transcript_retract") {
        applyTranscriptRetract(alert);
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

  useEffect(() => {
    if (activeTab !== "redis") {
      return undefined;
    }

    let isCancelled = false;

    async function fetchRedisIntelligence() {
      setIsRedisIntelligenceLoading(true);
      try {
        const response = await fetch(`${API_BASE_URL}/redis-intelligence`);
        if (!response.ok) {
          throw new Error("Redis intelligence endpoint returned an error");
        }
        const result = await response.json();
        if (!isCancelled) {
          setRedisIntelligence(result);
          setRedisIntelligenceError("");
        }
      } catch (error) {
        if (!isCancelled) {
          setRedisIntelligenceError(error.message || "Could not load Redis intelligence");
        }
      } finally {
        if (!isCancelled) {
          setIsRedisIntelligenceLoading(false);
        }
      }
    }

    fetchRedisIntelligence();
    const intervalId = window.setInterval(fetchRedisIntelligence, 2000);

    return () => {
      isCancelled = true;
      window.clearInterval(intervalId);
    };
  }, [activeTab]);

  const riskColor = getRiskColor(riskScore);
  const riskLevel = getRiskLevel(riskScore);
  const riskPercent = useMemo(() => `${Math.min(riskScore, 1) * 100}%`, [riskScore]);
  const verifiedCount = callerUtterances.filter((utterance) => utterance.verificationVerdict).length;
  const agentActivity = {
    Sentinel: connectionStatus === "connected" || callerUtterances.length > 0,
    Verifier: verifiedCount > 0,
    Coach: Boolean(coachingTip),
    Ally: Boolean(allyAlert),
    Scribe: callerUtterances.length > 0 || Boolean(callOutcome),
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
          <a href="#agents" onClick={() => setActiveTab("home")}>
            Agents
          </a>
          <a href="#product" onClick={() => setActiveTab("home")}>
            Product
          </a>
          <a href="#console" onClick={() => setActiveTab("home")}>
            Live Console
          </a>
          <a href="#trust" onClick={() => setActiveTab("home")}>
            Trust
          </a>
          <button
            type="button"
            className={`nav-tab ${activeTab === "architecture" ? "active" : ""}`}
            onClick={() => setActiveTab("architecture")}
          >
            Architecture
          </button>
          <button
            type="button"
            className={`nav-tab ${activeTab === "redis" ? "active" : ""}`}
            onClick={() => setActiveTab("redis")}
          >
            Redis Intelligence
          </button>
        </div>
        <button className="theme-toggle" onClick={handleToggleTheme} type="button">
          <span>{theme === "dark" ? "Dark" : "Light"}</span>
          <span className="theme-toggle-track" aria-hidden="true">
            <span className="theme-toggle-thumb" />
          </span>
        </button>
      </nav>

      {activeTab === "architecture" ? (
        <section className="architecture-section">
          <div className="architecture-card section-panel">
            <p className="eyebrow">System architecture</p>
            <h1>Guardian system architecture</h1>
            <p>
              Eraser blocks this shared workspace from loading inside third-party
              iframes, so open the architecture diagram directly in Eraser.
            </p>
            <a
              className="primary-button"
              href={ARCHITECTURE_URL}
              target="_blank"
              rel="noreferrer"
            >
              Open architecture diagram
            </a>
          </div>
        </section>
      ) : activeTab === "redis" ? (
        <RedisIntelligenceDashboard
          data={redisIntelligence}
          error={redisIntelligenceError}
          loading={isRedisIntelligenceLoading}
        />
      ) : (
        <>
      <section className="hero-section" id="top">
        <div className="hero-copy">
          <p className="eyebrow">Family-first call protection</p>
          <h1>A trusted voice beside every call.</h1>
          <p className="hero-subtitle">
            Five specialized agents work together in real time: listening for scam
            tactics, verifying suspicious claims, coaching calm responses, alerting
            trusted contacts, and documenting only what matters.
          </p>
          <div className="hero-actions">
            <button
              className="primary-button"
              disabled={isStartingCall || connectionStatus !== "connected"}
              onClick={handleStartCall}
              type="button"
            >
              {isStartingCall ? "Starting call..." : "Start Call"}
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

      <section className="agents-section section-panel" id="agents">
        <div className="section-heading">
          <p className="eyebrow">Flagship protection engine</p>
          <h2>Five specialized agents working beside every call.</h2>
          <p>
            The Nightwatchman is not a single chatbot. It is a coordinated safety
            system where each agent owns one critical part of protection.
          </p>
        </div>

        <div className="agent-constellation">
          <div className="agent-call-core">
            <span className="call-core-ring" />
            <p>Protection Engine</p>
            <strong>5 agents</strong>
            <span>{utterances.length || "No"} call moments tracked</span>
          </div>
          {AGENTS.map((agent) => (
            <article
              className={`agent-node ${agent.className} ${
                agentActivity[agent.name] ? "active" : ""
              }`}
              key={agent.name}
              tabIndex="0"
            >
              <div className="agent-node-header">
                <span className="agent-mark">{agent.name.slice(0, 1)}</span>
                <span className="agent-status-dot" />
              </div>
              <p>{agent.role}</p>
              <h3>{agent.name}</h3>
              <span>{agent.description}</span>
              <strong>{agent.contribution}</strong>
            </article>
          ))}
        </div>
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

            {micDenied && (
              <section className="mic-warning-banner">
                Microphone access denied — victim audio unavailable.
              </section>
            )}

            <section className="glass-panel call-control-panel">
              <div>
                <p className="eyebrow">Monitoring controls</p>
                <h2>Start when the call begins. End when it is safe.</h2>
              </div>
              <div className="call-actions">
                <button
                  className="secondary-button compact"
                  disabled={isSimulating || connectionStatus !== "connected"}
                  onClick={handleSimulate}
                  type="button"
                >
                  {isSimulating ? "Simulating..." : "Simulate"}
                </button>
                <button
                  className="primary-button compact"
                  disabled={isStartingCall || connectionStatus !== "connected"}
                  onClick={handleStartCall}
                  type="button"
                >
                  {isStartingCall ? "Starting call..." : "Start Call"}
                </button>
                <button
                  className="danger-button compact"
                  disabled={isEndingCall || !isCallSessionActive}
                  onClick={handleEndCall}
                  type="button"
                >
                  {isEndingCall ? "Ending call..." : "End Call"}
                </button>
                {isMicCallActive && <span className="mic-active-pill">Mic live</span>}
                {isMicCallActive && !twilioConfigured && (
                  <span className="twilio-simulated-pill">
                    Twilio not connected — simulated mode
                  </span>
                )}
                {isMicCallActive && twilioConfigured && twilioCallActive && (
                  <span className="twilio-active-pill">Twilio calling</span>
                )}
              </div>
            </section>

            <section className="glass-panel transcript-panel">
              <div className="panel-header">
                <div>
                  <p className="eyebrow">Transcript</p>
                  <h2>What each side is saying</h2>
                </div>
                <span className="count-pill">
                  {callerUtterances.length + victimUtterances.length} entries
                </span>
              </div>
              <div className="transcript-columns">
                <div className="transcript-column">
                  <div className="transcript-column-header caller">Caller</div>
                  <div className="transcript-column-scroll">
                    {callerUtterances.length === 0 ? (
                      <p className="empty">
                        Caller speech appears here from Twilio or simulation.
                      </p>
                    ) : (
                      callerUtterances.map((utterance) => {
                        const verificationTag = getVerificationTag(utterance.verificationVerdict);

                        return (
                          <article className="transcript-card caller-card" key={utterance.id}>
                            <p>{utterance.text}</p>
                            <div className="transcript-card-meta">
                              <span className="transcript-card-time">
                                {formatTimestamp(utterance.timestamp)}
                              </span>
                              <span>
                                {formatTacticLabel(utterance.tactic)}
                                {utterance.tactic &&
                                  utterance.tactic !== "NONE" &&
                                  utterance.tactic !== "ANALYZING" &&
                                  ` · ${utterance.score.toFixed(2)}`}
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
                            {utterance.coachingTip && (
                              <p className="utterance-coaching">
                                <span>Coach</span>
                                {utterance.coachingTip}
                              </p>
                            )}
                          </article>
                        );
                      })
                    )}
                    <div ref={callerTranscriptEndRef} />
                  </div>
                </div>

                <div className="transcript-column">
                  <div className="transcript-column-header victim">You</div>
                  <div className="transcript-column-scroll">
                    {victimUtterances.length === 0 ? (
                      <p className="empty">
                        Click Start Call and speak — your side appears here.
                      </p>
                    ) : (
                      victimUtterances.map((utterance) => (
                        <article className="transcript-card victim-card" key={utterance.id}>
                          <p>{utterance.text}</p>
                          <span className="transcript-card-time">
                            {formatTimestamp(utterance.timestamp)}
                          </span>
                        </article>
                      ))
                    )}
                    <div ref={victimTranscriptEndRef} />
                  </div>
                </div>
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
        </>
      )}
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
