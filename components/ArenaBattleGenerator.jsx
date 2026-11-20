import React, { useState } from 'react';

const STAGE_ENVIRONMENTS = [
  "Green Coordinate Stage",
  "Clean Studio",
  "Roman Colosseum",
  "Throne Room",
  "Neon City",
  "Enchanted Forest",
  "Beach Sunset",
  "Outer Space",
  "Boxing Ring",
  "Open Highway Race Track",
  "Snowy Mountain Ski Slope",
  "Desert Dunes",
  "Basketball Court",
  "Sports Stadium",
  "Sports Field",
  "Tennis Court",
  "Grand Ballroom",
  "Night Club",
  "City Rooftop"
];

const PRESETS = {
  free: [
    { label: "🥊 Fight", key: "fight", extra: 0 },
    { label: "💕 Romance", key: "romance", extra: 0 },
    { label: "💃 Dance", key: "dance", extra: 0 },
    { label: "🤗 Hug", key: "hug", extra: 0 },
    { label: "🙌 High Five", key: "highfive", extra: 0 },
    { label: "⚔ Face-Off", key: "faceoff", extra: 0 },
  ],
  adult: [
    { label: "🎲 Surprise me (+15cr)", key: "surprise_me", extra: 15 },
    { label: "🧘 Partner yoga (+15cr)", key: "partner_yoga", extra: 15 },
    { label: "🍿 Movie night (+15cr)", key: "movie_night", extra: 15 },
    { label: "🏖 Beach day (+15cr)", key: "beach_day", extra: 15 },
    { label: "💆 Shoulder rub (+15cr)", key: "shoulder_rub", extra: 15 },
    { label: "🌧 Caught in rain (+15cr)", key: "caught_in_rain", extra: 15 },
    { label: "👩‍🍳 Kitchen chemistry (+15cr)", key: "kitchen_chemistry", extra: 15 },
    { label: "📸 Photoshoot (+15cr)", key: "photoshoot", extra: 15 },
    { label: "🛏 Sleepover (+15cr)", key: "sleepover", extra: 15 },
    { label: "🍷 After the wine (+15cr)", key: "after_the_wine", extra: 15 },
    { label: "🤸 Invisible trampoline (+15cr)", key: "invisible_trampoline", extra: 15 },
  ],
  combat: [
    { label: "🤺 Fencing Duel", key: "fencing", extra: 0 },
    { label: "🥊 Boxing Match", key: "boxing", extra: 0 },
    { label: "⚔ Sword Fight", key: "sword_fight", extra: 0 },
    { label: "🥋 Kung-Fu", key: "kung_fu", extra: 0 },
    { label: "🥷 Karate", key: "karate", extra: 0 },
    { label: "🤼 Wrestling", key: "wrestling", extra: 0 },
    { label: "🥊 MMA Cage", key: "mma", extra: 0 },
    { label: "🔦 Lightsaber", key: "lightsaber", extra: 0 },
    { label: "🥢 Staff Fight", key: "staff_fight", extra: 0 },
    { label: "😤 Standoff", key: "standoff", extra: 0 },
  ],
  sports: [
    { label: "🏀 Basketball", key: "basketball", extra: 0 },
    { label: "🏈 Football", key: "football", extra: 0 },
    { label: "⚾ Baseball", key: "baseball", extra: 0 },
    { label: "⚽ Soccer", key: "soccer", extra: 0 },
    { label: "🎾 Tennis", key: "tennis", extra: 0 },
    { label: "⛷ Skiing", key: "skiing", extra: 0 },
    { label: "🏂 Snowboarding", key: "snowboarding", extra: 0 },
    { label: "🏍 Dirt Bikes", key: "dirt_bikes", extra: 0 },
    { label: "🛞 Quad / ATV", key: "quad_atv", extra: 0 },
    { label: "🛷 Snowmobile", key: "snowmobile", extra: 0 },
    { label: "🏄 Surfing", key: "surfing", extra: 0 },
    { label: "🛹 Skateboarding", key: "skateboarding", extra: 0 },
    { label: "⛳ Golf", key: "golf", extra: 0 },
  ],
  dance: [
    { label: "🕺 Dance-Off", key: "dance_off", extra: 0 },
    { label: "💃 Tango", key: "tango", extra: 0 },
    { label: "🎩 Ballroom Waltz", key: "ballroom_waltz", extra: 0 },
    { label: "🌶 Salsa", key: "salsa", extra: 0 },
    { label: "🩰 Ballet", key: "ballet", extra: 0 },
    { label: "🤸 Breakdance", key: "breakdance", extra: 0 },
    { label: "🧢 Hip-Hop", key: "hip_hop", extra: 0 },
    { label: "🌀 Contemporary", key: "contemporary", extra: 0 },
    { label: "🎷 Swing", key: "swing", extra: 0 },
  ],
  racing: [
    { label: "🏍 Motorcycle Race", key: "motorcycle_race", extra: 0 },
    { label: "🏎 Convertible Race", key: "convertible_race", extra: 0 },
  ],
};

export default function ArenaBattleGenerator() {
  const [player1, setPlayer1] = useState(null);
  const [player2, setPlayer2] = useState(null);
  const [duration, setDuration] = useState({ sec: 6, cost: 18 });
  const [stage, setStage] = useState("Roman Colosseum");
  const [activeAction, setActiveAction] = useState({ key: "fight", extra: 0 });
  const [customPrompt, setCustomPrompt] = useState("");
  const [showCookie, setShowCookie] = useState(true);

  const totalCost = duration.cost + activeAction.extra;

  const handlePickPlayer = (slot) => {
    const name = window.prompt(`Enter Character Name/ID for Player ${slot}:`);
    if (name) {
      if (slot === 1) setPlayer1(name);
      else setPlayer2(name);
    }
  };

  const handleGenerate = (e) => {
    e.preventDefault();
    if (!player1 || !player2) {
      alert("Please select Player 1 and Player 2 before generating.");
      return;
    }
    alert(`Generating ${duration.sec}s scene with ${player1} VS ${player2} on ${stage} doing ${activeAction.key} (${totalCost} credits).`);
  };

  return (
    <div style={{ backgroundColor: "#0c0907", color: "#fff6ea", minHeight: "100vh", fontFamily: "Inter, sans-serif", paddingBottom: "80px" }}>
      {/* Header */}
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "16px 32px", borderBottom: "1px solid #3d2e22" }}>
        <div style={{ fontWeight: 800, fontSize: "1.3rem", background: "linear-gradient(135deg, #e8a54b, #c45c2a)", WebkitBackgroundClip: "text", color: "transparent" }}>
          Percfect Arena
        </div>
        <nav style={{ display: "flex", gap: "20px", alignItems: "center" }}>
          <a href="/studios" style={{ color: "#b8a08a", textDecoration: "none" }}>Studios</a>
          <a href="/support" style={{ color: "#b8a08a", textDecoration: "none" }}>Support</a>
          <a href="/login" style={{ color: "#b8a08a", textDecoration: "none" }}>Log in</a>
          <button style={{ background: "linear-gradient(135deg, #e8a54b, #c45c2a)", color: "#1a1008", border: "none", padding: "8px 16px", borderRadius: "8px", fontWeight: 700, cursor: "pointer" }}>
            Get started
          </button>
        </nav>
      </header>

      {/* Main Container */}
      <div style={{ maxWidth: "1100px", margin: "32px auto", padding: "0 16px" }}>
        <div style={{ textAlign: "center", marginBottom: "28px" }}>
          <h1 style={{ fontSize: "2.4rem", fontWeight: 900, marginBottom: "8px", letterSpacing: "-0.03em" }}>The Arena</h1>
          <p style={{ color: "#b8a08a" }}>Pick two players — library opens from the corner</p>
        </div>

        {/* Matchup Grid */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr auto 1fr", gap: "16px", alignItems: "center", marginBottom: "32px" }}>
          <div onClick={() => handlePickPlayer(1)} style={{ background: "#16110d", border: `2px dashed ${player1 ? "#e8a54b" : "#5c4330"}`, borderRadius: "14px", padding: "40px 20px", textAlign: "center", cursor: "pointer" }}>
            <div style={{ fontSize: "2.5rem", marginBottom: "8px" }}>👤</div>
            <div style={{ fontWeight: 700, fontSize: "1.1rem", color: "#f5e0b8" }}>{player1 || "P1 Choose player"}</div>
          </div>
          <div style={{ fontWeight: 900, fontSize: "1.8rem", color: "#e8a54b", textShadow: "0 0 16px rgba(232, 165, 75, 0.4)", padding: "12px" }}>VS</div>
          <div onClick={() => handlePickPlayer(2)} style={{ background: "#16110d", border: `2px dashed ${player2 ? "#e8a54b" : "#5c4330"}`, borderRadius: "14px", padding: "40px 20px", textAlign: "center", cursor: "pointer" }}>
            <div style={{ fontSize: "2.5rem", marginBottom: "8px" }}>👤</div>
            <div style={{ fontWeight: 700, fontSize: "1.1rem", color: "#f5e0b8" }}>{player2 || "P2 Choose player"}</div>
          </div>
        </div>

        {/* Controls Panel */}
        <div style={{ background: "#16110d", border: "1px solid #3d2e22", borderRadius: "14px", padding: "24px", marginBottom: "32px" }}>
          {/* Duration */}
          <div style={{ marginBottom: "20px" }}>
            <label style={{ display: "block", fontSize: "0.8rem", color: "#f0c674", marginBottom: "8px", textTransform: "uppercase", fontWeight: 700 }}>Duration</label>
            <div style={{ display: "flex", gap: "12px" }}>
              {[{ sec: 6, cost: 18 }, { sec: 10, cost: 28 }, { sec: 15, cost: 38 }].map((d) => (
                <button
                  key={d.sec}
                  type="button"
                  onClick={() => setDuration(d)}
                  style={{
                    background: "#221a14",
                    border: `1px solid ${duration.sec === d.sec ? "#e8a54b" : "#5c4330"}`,
                    color: duration.sec === d.sec ? "#fff6ea" : "#b8a08a",
                    padding: "10px 20px",
                    borderRadius: "8px",
                    cursor: "pointer",
                    fontWeight: 600,
                  }}
                >
                  {d.sec}s (+{d.cost}cr)
                </button>
              ))}
            </div>
          </div>

          {/* Stage Environment */}
          <div style={{ marginBottom: "20px" }}>
            <label style={{ display: "block", fontSize: "0.8rem", color: "#f0c674", marginBottom: "8px", textTransform: "uppercase", fontWeight: 700 }}>Stage Environment (19 Locations)</label>
            <select
              value={stage}
              onChange={(e) => setStage(e.target.value)}
              style={{ width: "100%", padding: "12px", background: "#221a14", border: "1px solid "#5c4330", color: "#fff6ea", borderRadius: "8px", fontSize: "1rem" }}
            >
              {STAGE_ENVIRONMENTS.map((stg) => (
                <option key={stg} value={stg}>{stg}</option>
              ))}
            </select>
          </div>

          {/* Custom Prompt */}
          <div style={{ marginBottom: "20px" }}>
            <label style={{ display: "block", fontSize: "0.8rem", color: "#f0c674", marginBottom: "8px", textTransform: "uppercase", fontWeight: 700 }}>Custom Interaction Prompt</label>
            <textarea
              rows={2}
              value={customPrompt}
              onChange={(e) => setCustomPrompt(e.target.value)}
              placeholder='e.g., "They spar with blades in the Colosseum dust until one bows"'
              style={{ width: "100%", padding: "12px", background: "#221a14", border: "1px solid #5c4330", color: "#fff6ea", borderRadius: "8px" }}
            />
          </div>

          {/* Generate Button */}
          <button
            onClick={handleGenerate}
            style={{ width: "100%", padding: "16px", fontSize: "1.15rem", fontWeight: 800, border: "none", borderRadius: "10px", background: "linear-gradient(135deg, #e8a54b, #c45c2a 50%, #8b2942)", color: "#1a1008", cursor: "pointer", boxShadow: "0 6px 24px rgba(232, 165, 75, 0.35)" }}
          >
            ▶ Generate ({duration.sec}s · ~{totalCost} credits)
          </button>
        </div>

        {/* Presets */}
        <div style={{ background: "#16110d", border: "1px solid #3d2e22", borderRadius: "14px", padding: "24px" }}>
          <h3 style={{ fontSize: "1.2rem", fontWeight: 800, marginBottom: "16px", color: "#f5e0b8" }}>Interaction Presets</h3>
          {Object.entries(PRESETS).map(([cat, items]) => (
            <div key={cat} style={{ marginBottom: "16px" }}>
              <div style={{ fontSize: "0.75rem", fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", color: cat === "adult" ? "#fb7185" : "#f0c674", marginBottom: "8px" }}>
                {cat === "adult" ? "18+ (+15 credits)" : cat.toUpperCase()}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
                {items.map((it) => (
                  <button
                    key={it.key}
                    type="button"
                    onClick={() => setActiveAction(it)}
                    style={{
                      background: activeAction.key === it.key ? "linear-gradient(135deg, #e8a54b, #c45c2a)" : "#221a14",
                      color: activeAction.key === it.key ? "#1a1008" : "#fff6ea",
                      border: `1px solid ${activeAction.key === it.key ? "transparent" : "#5c4330"}`,
                      padding: "8px 14px",
                      borderRadius: "999px",
                      cursor: "pointer",
                      fontSize: "0.85rem",
                      fontWeight: 600,
                    }}
                  >
                    {it.label}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Footer */}
      <footer style={{ borderTop: "1px solid #3d2e22", padding: "32px", textAlign: "center", color: "#b8a08a", fontSize: "0.9rem", marginTop: "60px" }}>
        <p>© 2026 PercfectAI · AI images & video generated via xAI</p>
        <nav style={{ marginTop: "12px", display: "flex", gap: "16px", justifyContent: "center" }}>
          <a href="/about" style={{ color: "#b8a08a", textDecoration: "none" }}>About</a>
          <a href="/terms" style={{ color: "#b8a08a", textDecoration: "none" }}>Terms</a>
          <a href="/privacy" style={{ color: "#b8a08a", textDecoration: "none" }}>Privacy</a>
          <a href="/disclaimer" style={{ color: "#b8a08a", textDecoration: "none" }}>Disclaimer</a>
          <a href="/support" style={{ color: "#b8a08a", textDecoration: "none" }}>Support</a>
          <a href="mailto:support@percfectai.com" style={{ color: "#b8a08a", textDecoration: "none" }}>support@percfectai.com</a>
        </nav>
      </footer>

      {/* Cookie Banner */}
      {showCookie && (
        <div style={{ position: "fixed", bottom: 0, left: 0, right: 0, background: "#16110d", borderTop: "1px solid #3d2e22", padding: "16px 32px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <p style={{ fontSize: "0.85rem", color: "#b8a08a", margin: 0 }}>
            We serve cookies to enable essential services and functionality on our site.
          </p>
          <div style={{ display: "flex", gap: "12px" }}>
            <button onClick={() => setShowCookie(false)} style={{ background: "transparent", border: "1px solid #3d2e22", color: "#fff6ea", padding: "6px 16px", borderRadius: "6px", cursor: "pointer" }}>Decline</button>
            <button onClick={() => setShowCookie(false)} style={{ background: "linear-gradient(135deg, #e8a54b, #c45c2a)", color: "#1a1008", border: "none", padding: "6px 16px", borderRadius: "6px", cursor: "pointer", fontWeight: 700 }}>Accept</button>
          </div>
        </div>
      )}
    </div>
  );
}
