import { useEffect, useId, useRef, useState } from "react";
import { PartyPlayerName } from "./PlayerCard";
import { errorMessage } from "./partyApi";
import "./partyChat.css";
import { SkinAvatar } from "./SkinAvatar";

export type ChatMessage = {
  id: string;
  text: string;
  at: number;
  sender?: { uuid: string; name: string };
  source?: "web" | "game";
};

export function PartyChat({
  messages,
  connected,
  onSend,
  onReport,
}: Readonly<{
  messages: ChatMessage[];
  connected: boolean;
  onSend: (text: string, requestId: string) => Promise<void>;
  onReport?: (messageId: string, reason: string) => Promise<void>;
}>) {
  const id = useId();
  const [draft, setDraft] = useState("");
  const [collapsed, setCollapsed] = useState(false);
  const [unread, setUnread] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const attempt = useRef<{ text: string; id: string } | null>(null);
  const sendingNow = useRef(false);
  const log = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);
  const previous = useRef(messages.at(-1)?.id);
  const bottom = () => {
    if (log.current) log.current.scrollTop = log.current.scrollHeight;
    pinned.current = true;
    setUnread(false);
  };
  useEffect(() => {
    const latest = messages.at(-1)?.id;
    if (!collapsed && pinned.current) bottom();
    else if (latest && latest !== previous.current) setUnread(true);
    previous.current = latest;
  }, [messages, collapsed]);
  const send = async () => {
    const text = draft.trim();
    if (!connected || sendingNow.current || !text || text.length > 256) return;
    if (attempt.current?.text !== text)
      attempt.current = { text, id: crypto.randomUUID() };
    sendingNow.current = true;
    setSending(true);
    setError("");
    try {
      await onSend(text, attempt.current.id);
      setDraft("");
      attempt.current = null;
      pinned.current = true;
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      sendingNow.current = false;
      setSending(false);
    }
  };

  return (
    <section className="party-chat" aria-labelledby={`${id}-title`}>
      <header className="chat-heading">
        <h2 id={`${id}-title`}>Party chat</h2>
        <output className="chat-status">
          {!connected ? "Reconnecting…" : "Connected"}
        </output>
        <button
          type="button"
          className="text-button"
          aria-expanded={!collapsed}
          aria-controls={`${id}-body`}
          onClick={() => setCollapsed(!collapsed)}
        >
          {unread && (
            <span className="chat-unread-dot" aria-label="New messages" />
          )}
          {collapsed ? "Show" : "Hide"}
        </button>
      </header>
      <div id={`${id}-body`} hidden={collapsed}>
        <div className="chat-history-wrap">
          <div
            ref={log}
            className="chat-history"
            role="log"
            aria-label="Party messages"
            aria-live="polite"
            aria-relevant="additions"
            tabIndex={0}
            onScroll={() => {
              const element = log.current!;
              pinned.current =
                element.scrollHeight -
                  element.clientHeight -
                  element.scrollTop <
                40;
              if (pinned.current) setUnread(false);
            }}
          >
            {messages.length === 0 ? (
              <div className="chat-empty">
                <p>No messages yet</p>
                <span>Say hello to your party.</span>
              </div>
            ) : (
              messages.map((message) =>
                message.sender ? (
                  <div className="chat-message" key={message.id}>
                    <SkinAvatar className="chat-avatar" {...message.sender} />
                    <div className="chat-message-content">
                      <div className="chat-message-meta">
                        <PartyPlayerName user={message.sender} />
                        <span className="chat-source">
                          {message.source === "game" ? "In game" : "Web"}
                        </span>
                        <time dateTime={new Date(message.at).toISOString()}>
                          {new Date(message.at).toLocaleTimeString([], {
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </time>
                      </div>
                      <p>{message.text}</p>
                      {onReport && (
                        <ReportMessage
                          messageId={message.id}
                          onReport={onReport}
                        />
                      )}
                    </div>
                  </div>
                ) : (
                  <p className="chat-event" key={message.id}>
                    {message.text}
                  </p>
                ),
              )
            )}
          </div>
          {unread && (
            <button
              type="button"
              className="chat-jump small-button"
              onClick={bottom}
            >
              New messages ↓
            </button>
          )}
        </div>
        <form
          className="chat-composer"
          onSubmit={(event) => {
            event.preventDefault();
            void send();
          }}
        >
          <input
            aria-label="Message your party"
            placeholder="Message your party…"
            autoComplete="off"
            maxLength={256}
            readOnly={sending}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && event.nativeEvent.isComposing)
                event.preventDefault();
            }}
          />
          {draft.length >= 220 && (
            <span className="chat-limit">{draft.length}/256</span>
          )}
          <button
            type="submit"
            className="chat-send"
            aria-label="Send message"
            disabled={!connected || sending || !draft.trim()}
          >
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path
                d="m5 12 7-7 7 7M12 5v14"
                stroke="currentColor"
                strokeWidth="1.7"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        </form>
        {error && (
          <p className="chat-connection-note" role="alert">
            {error} Your draft is kept.
          </p>
        )}
        {!connected && (
          <output className="chat-connection-note">
            Your draft is kept. Send it when you’re connected again.
          </output>
        )}
      </div>
    </section>
  );
}

function ReportMessage({
  messageId,
  onReport,
}: Readonly<{
  messageId: string;
  onReport: (id: string, reason: string) => Promise<void>;
}>) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const working = useRef(false);
  const [status, setStatus] = useState("");
  async function sendReport() {
    if (working.current || !reason.trim()) return;
    working.current = true;
    setBusy(true);
    setStatus("");
    try {
      await onReport(messageId, reason.trim());
      setOpen(false);
      setStatus("Reported.");
    } catch (error) {
      setStatus(errorMessage(error));
    } finally {
      working.current = false;
      setBusy(false);
    }
  }
  return (
    <div className="chat-report">
      {!open && status !== "Reported." && (
        <button
          type="button"
          className="text-button"
          onClick={() => setOpen(true)}
        >
          Report
        </button>
      )}
      {open && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void sendReport();
          }}
        >
          <label>
            Report reason{" "}
            <input
              required
              maxLength={500}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          <button
            type="submit"
            disabled={busy || !reason.trim()}
            className="small-button"
          >
            Submit report
          </button>
          <button
            type="button"
            className="text-button"
            disabled={busy}
            onClick={() => setOpen(false)}
          >
            Cancel
          </button>
        </form>
      )}
      {status && <output>{status}</output>}
    </div>
  );
}
