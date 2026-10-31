import { useEffect, useRef, useState } from "react";
import { helpText, parseChatVerb, type ChatVerb } from "./chat-verbs";

export type ChatMsg = { id: string; role: "user" | "coach"; text: string };

export type ChatRailHandlers = {
  runVerb: (verb: ChatVerb) => Promise<string>;
  context: {
    tab: number;
    title: string;
    castCount: number;
    hasCoverPrompt: boolean;
    hasCoverArt: boolean;
    coverApproved: boolean;
    unlocked: boolean;
    priceLabel: string;
  };
  busy: boolean;
};

const SUGGESTIONS = [
  "What's next?",
  "Go to cover",
  "Rewrite cover",
  "Ink cover",
  "Unlock",
];

export function ChatRail({ runVerb, context, busy }: ChatRailHandlers) {
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);
  const booted = useRef(false);

  useEffect(() => {
    if (booted.current) return;
    booted.current = true;
    setMsgs([
      {
        id: crypto.randomUUID(),
        role: "coach",
        text: helpText(context),
      },
    ]);
  }, [context]);

  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [msgs, sending]);

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || sending || busy) return;
    setDraft("");
    setMsgs((m) => [...m, { id: crypto.randomUUID(), role: "user", text: trimmed }]);
    setSending(true);
    try {
      const verb = parseChatVerb(trimmed);
      const reply =
        verb.type === "help"
          ? helpText(context)
          : await runVerb(verb);
      setMsgs((m) => [...m, { id: crypto.randomUUID(), role: "coach", text: reply }]);
    } catch (e) {
      setMsgs((m) => [
        ...m,
        {
          id: crypto.randomUUID(),
          role: "coach",
          text: e instanceof Error ? e.message : "That didn't go through. Try again.",
        },
      ]);
    } finally {
      setSending(false);
    }
  }

  return (
    <aside className="chatrail" aria-label="Comic coach chat">
      <div className="chatrail__head">
        <div className="kicker">Coach</div>
        <h2 className="chatrail__title">Talk the comic</h2>
        <p className="help">Characters + Cover. I run the studio — you say what happens.</p>
      </div>
      <div className="chatrail__msgs" ref={scroller} role="log" aria-live="polite">
        {msgs.map((m) => (
          <div key={m.id} className={`chatbubble chatbubble--${m.role}`}>
            {m.text.split("\n").map((line, i) => (
              <span key={i}>
                {i > 0 && <br />}
                {line}
              </span>
            ))}
          </div>
        ))}
        {(sending || busy) && <div className="chatbubble chatbubble--coach chatbubble--busy">Working…</div>}
      </div>
      <div className="chatrail__suggest">
        {SUGGESTIONS.map((s) => (
          <button key={s} type="button" className="chip" disabled={sending || busy} onClick={() => void send(s)}>
            {s}
          </button>
        ))}
      </div>
      <form
        className="chatrail__form"
        onSubmit={(e) => {
          e.preventDefault();
          void send(draft);
        }}
      >
        <label className="sr-only" htmlFor="comic-coach-input">
          Message the comic coach
        </label>
        <input
          id="comic-coach-input"
          className="inp"
          value={draft}
          disabled={sending || busy}
          placeholder='Try "use saved Maya" or "ink cover"'
          onChange={(e) => setDraft(e.target.value)}
          autoComplete="off"
        />
        <button className="btn-sm primary" type="submit" disabled={sending || busy || !draft.trim()}>
          Send
        </button>
      </form>
    </aside>
  );
}
