// v14 — xAI cloud STT (MediaRecorder → /support/stt) + single Ara TTS
/**
 * Admin floating companions.
 * - Vanessa: personal assistant you can talk to (STT + TTS + hands-free loop)
 * - Mira: product/ops co-pilot (same voice controls)
 * Ashley & Sal remain on /studios/support only.
 */
(function () {
  "use strict";

  const root = document.getElementById("vanessa-root");
  if (!root) return;

  const fab = document.getElementById("vanessa-fab");
  const fabImg = document.getElementById("vanessa-fab-img");
  const fabLetter = document.getElementById("vanessa-fab-letter");
  const avatarBtn = document.getElementById("vanessa-avatar-btn");
  const avatarImg = document.getElementById("vanessa-avatar");
  const avatarLetter = document.getElementById("vanessa-avatar-letter");
  const avatarFile = document.getElementById("vanessa-avatar-file");
  const closeBtn = document.getElementById("vanessa-close");
  const log = document.getElementById("vanessa-log");
  const form = document.getElementById("vanessa-form");
  const input = document.getElementById("vanessa-input");
  const sendBtn = document.getElementById("vanessa-send");
  const micBtn = document.getElementById("vanessa-mic");
  const talkBtn = document.getElementById("vanessa-talk");
  const speakToggle = document.getElementById("vanessa-speak-toggle");
  const voiceStatus = document.getElementById("vanessa-voice-status");
  const shotBtn = document.getElementById("vanessa-shot");
  const shotPreview = document.getElementById("vanessa-shot-preview");
  const shotImg = document.getElementById("vanessa-shot-img");
  const shotClear = document.getElementById("vanessa-shot-clear");
  const errEl = document.getElementById("vanessa-err");
  const titleEl = document.getElementById("vanessa-title");
  const subEl = document.getElementById("vanessa-sub");
  const tierRow = document.getElementById("vanessa-tier-row");
  const miraNote = document.getElementById("mira-tier-note");

  // Optional site defaults (drop files into static/assets/companions/)
  const DEFAULT_AVATARS = {
    vanessa: "/static/assets/companions/vanessa.jpg?v=face-1",
    mira: "/static/assets/companions/mira.jpg?v=face-1",
  };

  const CHAT_URLS = [
    "/studios/support/chat",
    "/percfectstudios/support/chat",
    "/api/support/chat",
  ];
  const PAGE_CTX =
    "URL: " +
    (window.location.pathname + window.location.search) +
    " · " +
    (document.title || "");

  let agent = "vanessa"; // vanessa | mira
  let modelTier = "fast"; // Vanessa only
  const histories = { vanessa: [], mira: [] };
  let pendingShot = null;
  let busy = false;
  let speakReplies = true;
  let voice = null;
  let autoSendArmed = false; // prevent double-send from STT final

  try {
    const savedAgent = localStorage.getItem("admin_companion_agent");
    if (savedAgent === "mira" || savedAgent === "vanessa") agent = savedAgent;
    const savedTier = localStorage.getItem("vanessa_model_tier");
    if (savedTier === "fast" || savedTier === "smart") modelTier = savedTier;
    const savedSpeak = localStorage.getItem("vanessa_speak_replies");
    if (savedSpeak === "0") speakReplies = false;
    if (savedSpeak === "1") speakReplies = true;
  } catch (e) {}

  function appendMsg(role, text, forAgent) {
    if (!log) return;
    if (forAgent && forAgent !== agent) return;
    const div = document.createElement("div");
    div.className = "v-msg " + (role === "user" ? "user" : role === "sys" ? "sys" : "bot");
    div.textContent = text;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
  }

  function setErr(msg) {
    if (!errEl) return;
    if (!msg) {
      errEl.style.display = "none";
      errEl.textContent = "";
      return;
    }
    errEl.textContent = msg;
    errEl.style.display = "block";
  }

  function setVoiceStatus(state, label) {
    root.classList.toggle("listening", state === "listening");
    root.classList.toggle("speaking", state === "speaking");
    root.classList.toggle("thinking", state === "thinking");
    if (!voiceStatus) return;
    voiceStatus.className = "vanessa-voice-status" + (state && state !== "idle" ? " " + state : "");
    voiceStatus.textContent = label || (state === "listening"
      ? "Listening"
      : state === "speaking"
        ? "Speaking"
        : state === "thinking"
          ? "Thinking"
          : "Idle");
  }

  function setMicUi(listening) {
    if (!micBtn) return;
    micBtn.classList.toggle("listening", !!listening);
    micBtn.setAttribute("aria-pressed", listening ? "true" : "false");
    micBtn.title = listening ? "Stop listening" : "Speech to text";
  }

  function setTalkUi(on) {
    if (!talkBtn) return;
    talkBtn.classList.toggle("active", !!on);
    talkBtn.setAttribute("aria-pressed", on ? "true" : "false");
    talkBtn.textContent = on ? "🎙 Talking…" : "🎙 Talk";
  }

  function setSpeakUi() {
    if (!speakToggle) return;
    speakToggle.classList.toggle("active", speakReplies);
    speakToggle.setAttribute("aria-pressed", speakReplies ? "true" : "false");
  }

  function avatarStorageKey(who) {
    return "companion_avatar_" + (who || agent);
  }

  function getSavedAvatar(who) {
    try {
      return localStorage.getItem(avatarStorageKey(who)) || "";
    } catch (e) {
      return "";
    }
  }

  function applyAvatarSrc(src) {
    const has = !!(src && String(src).trim());
    if (avatarImg) {
      if (has) {
        avatarImg.src = src;
        avatarImg.hidden = false;
      } else {
        avatarImg.removeAttribute("src");
        avatarImg.hidden = true;
      }
    }
    if (avatarBtn) avatarBtn.classList.toggle("has-pic", has);
    if (avatarLetter) {
      avatarLetter.textContent = agent === "mira" ? "M" : "V";
      avatarLetter.style.display = has ? "none" : "";
    }
    if (fabImg) {
      if (has) {
        fabImg.src = src;
        fabImg.hidden = false;
      } else {
        fabImg.removeAttribute("src");
        fabImg.hidden = true;
      }
    }
    if (fab) fab.classList.toggle("has-pic", has);
    if (fabLetter) {
      fabLetter.textContent = agent === "mira" ? "M" : "V";
      fabLetter.style.display = has ? "none" : "";
    }
  }

  function loadAvatarForAgent() {
    const saved = getSavedAvatar(agent);
    if (saved) {
      applyAvatarSrc(saved);
      return;
    }
    // Try optional site default; fall back to letter if missing
    const def = DEFAULT_AVATARS[agent];
    if (!def) {
      applyAvatarSrc("");
      return;
    }
    const who = agent;
    const probe = new Image();
    probe.onload = function () {
      if (agent === who) applyAvatarSrc(def);
    };
    probe.onerror = function () {
      if (agent === who) applyAvatarSrc("");
    };
    probe.src = def + (def.indexOf("?") >= 0 ? "&" : "?") + "v=1";
  }

  function resizeImageFile(file, maxSide, quality) {
    maxSide = maxSide || 320;
    quality = quality == null ? 0.82 : quality;
    return new Promise(function (resolve, reject) {
      const reader = new FileReader();
      reader.onerror = function () {
        reject(new Error("Could not read image"));
      };
      reader.onload = function () {
        const img = new Image();
        img.onerror = function () {
          reject(new Error("Invalid image"));
        };
        img.onload = function () {
          let w = img.naturalWidth || img.width;
          let h = img.naturalHeight || img.height;
          if (!w || !h) {
            reject(new Error("Invalid image size"));
            return;
          }
          const scale = Math.min(1, maxSide / Math.max(w, h));
          w = Math.max(1, Math.round(w * scale));
          h = Math.max(1, Math.round(h * scale));
          const c = document.createElement("canvas");
          c.width = w;
          c.height = h;
          c.getContext("2d").drawImage(img, 0, 0, w, h);
          let q = quality;
          let dataUrl = c.toDataURL("image/jpeg", q);
          // Keep localStorage small (~300KB cap)
          while (dataUrl.length > 280000 && q > 0.45) {
            q -= 0.08;
            dataUrl = c.toDataURL("image/jpeg", q);
          }
          if (dataUrl.length > 350000) {
            reject(new Error("Image still too large — try a smaller photo"));
            return;
          }
          resolve(dataUrl);
        };
        img.src = reader.result;
      };
      reader.readAsDataURL(file);
    });
  }

  function setupAvatarPicker() {
    if (avatarBtn && avatarFile) {
      avatarBtn.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        avatarFile.value = "";
        avatarFile.click();
      });
      // Right-click header face → clear custom pic
      avatarBtn.addEventListener("contextmenu", function (e) {
        e.preventDefault();
        try {
          localStorage.removeItem(avatarStorageKey(agent));
        } catch (err) {}
        loadAvatarForAgent();
        appendMsg("sys", "Picture reset for " + (agent === "mira" ? "Mira" : "Vanessa") + ".");
      });
    }
    if (avatarFile) {
      avatarFile.addEventListener("change", function () {
        const file = avatarFile.files && avatarFile.files[0];
        if (!file) return;
        if (!/^image\//.test(file.type || "")) {
          setErr("Pick an image file (jpg, png, webp…).");
          return;
        }
        resizeImageFile(file)
          .then(function (dataUrl) {
            try {
              localStorage.setItem(avatarStorageKey(agent), dataUrl);
            } catch (err) {
              setErr("Could not save picture in this browser (storage full?).");
              return;
            }
            applyAvatarSrc(dataUrl);
            appendMsg(
              "sys",
              "Picture set for " +
                (agent === "mira" ? "Mira" : "Vanessa") +
                " on this device. Right-click face to reset."
            );
            setErr("");
          })
          .catch(function (ex) {
            setErr(ex.message || "Could not use that image");
          });
      });
    }
  }

  function updateChrome() {
    document.querySelectorAll(".v-tab").forEach(function (btn) {
      const on = btn.getAttribute("data-agent") === agent;
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    });
    document.querySelectorAll(".v-tier").forEach(function (btn) {
      btn.classList.toggle("active", btn.getAttribute("data-tier") === modelTier);
    });
    if (tierRow) tierRow.hidden = agent !== "vanessa";
    if (miraNote) miraNote.hidden = agent !== "mira";

    if (titleEl) {
      titleEl.innerHTML =
        agent === "mira"
          ? 'Mira <span>· you only</span>'
          : 'Vanessa <span>· you only</span>';
    }
    if (subEl) {
      subEl.textContent =
        agent === "mira"
          ? "Product/ops · Talk mode · Ashley & Sal on Support"
          : "Personal assistant · Talk with me · Ashley & Sal on Support";
    }
    if (input) {
      input.placeholder =
        agent === "mira"
          ? "Talk or type a product change for Sal…"
          : modelTier === "smart"
            ? "Talk or type — Smart mode…"
            : "Talk or type — Fast mode…";
    }
    if (fabLetter) fabLetter.textContent = agent === "mira" ? "M" : "V";
    if (avatarLetter) avatarLetter.textContent = agent === "mira" ? "M" : "V";
    loadAvatarForAgent();

    log.querySelectorAll("[data-seed]").forEach(function (el) {
      el.hidden = el.getAttribute("data-seed") !== agent;
    });
    setSpeakUi();
  }

  function setupVoice() {
    if (!window.VanessaVoice) {
      if (micBtn) {
        micBtn.disabled = true;
        micBtn.title = "Voice module failed to load";
      }
      if (talkBtn) {
        talkBtn.disabled = true;
        talkBtn.title = "Voice module failed to load";
      }
      return;
    }

    if (!VanessaVoice.sttSupported) {
      if (micBtn) {
        micBtn.disabled = true;
        micBtn.title = "Mic recording not supported in this browser — type instead";
      }
      if (talkBtn) {
        talkBtn.disabled = true;
        talkBtn.title = "Talk mode needs mic recording support";
      }
    }
    if (!VanessaVoice.ttsSupported && speakToggle) {
      speakToggle.disabled = true;
      speakToggle.title = "Text-to-speech not supported in this browser";
      speakReplies = false;
      setSpeakUi();
    }

    voice = VanessaVoice.create({
      lang: "en-US",
      isPaused: function () {
        return !!busy;
      },
      getAgent: function () {
        return agent;
      },
      getVoiceId: function () {
        // Vanessa = Ara (Grok), Mira = Eve
        return agent === "mira" ? "eve" : "ara";
      },
      getInputText: function () {
        return (input && input.value) || "";
      },
      onListenStart: function () {
        setMicUi(true);
        setVoiceStatus("listening", "Listening");
        setErr("");
      },
      onListenEnd: function () {
        setMicUi(false);
        if (voice && voice.speaking) return;
        if (busy) {
          setVoiceStatus("thinking", "Thinking");
          return;
        }
        if (voice && voice.conversation) {
          setVoiceStatus("listening", "Listening");
        } else {
          setVoiceStatus("idle", "Idle");
        }
      },
      onSpeakStart: function () {
        setVoiceStatus("speaking", "Speaking");
      },
      onSpeakEnd: function () {
        if (busy) {
          setVoiceStatus("thinking", "Thinking");
        } else if (voice && voice.conversation) {
          setVoiceStatus("listening", "Listening");
        } else {
          setVoiceStatus("idle", "Idle");
        }
      },
      onError: function (msg) {
        setMicUi(false);
        setErr(msg);
        if (!(voice && voice.conversation)) setVoiceStatus("idle", "Idle");
      },
      onPartial: function (parts) {
        if (!input) return;
        const base = parts.base || "";
        const fin = parts.final || "";
        const mid = parts.interim || "";
        if (fin) {
          input.value = (base + fin).replace(/\s+/g, " ").trimStart();
        } else if (mid) {
          input.value = (base + mid).trimStart();
        }
      },
      onFinal: function (said) {
        if (!said) return;
        if (input) {
          if (voice && voice.conversation) {
            input.value = said;
          } else if (!input.value || input.value.trim().length < said.length) {
            input.value = said;
          }
        }
        // Hands-free Talk mode: speech → chat API → speak reply
        if (voice && voice.conversation && !busy && !autoSendArmed) {
          autoSendArmed = true;
          setTimeout(function () {
            autoSendArmed = false;
            send(said);
          }, 120);
        }
      },
    });

    if (micBtn) {
      micBtn.addEventListener("click", function (e) {
        e.preventDefault();
        if (!voice) return;
        // One-shot dictation; if Talk mode is on, toggle still works
        voice.toggleListen();
      });
    }

    if (talkBtn) {
      talkBtn.addEventListener("click", function (e) {
        e.preventDefault();
        if (!voice) return;
        const on = !voice.conversation;
        voice.setConversation(on);
        setTalkUi(on);
        try {
          localStorage.setItem("vanessa_talk_mode", on ? "1" : "0");
        } catch (err) {}
        if (on) {
          // Conversation implies speaking replies
          if (!speakReplies) {
            speakReplies = true;
            try {
              localStorage.setItem("vanessa_speak_replies", "1");
            } catch (err2) {}
            setSpeakUi();
          }
          setOpen(true);
          appendMsg(
            "sys",
            "Talk mode on — speak, pause when done. I hear you via xAI (admin only), then reply out loud."
          );
          setVoiceStatus("listening", "Listening");
          voice.startListen();
        } else {
          voice.stopListen();
          setVoiceStatus("idle", "Idle");
          appendMsg("sys", "Talk mode off.");
        }
      });
    }

    if (speakToggle) {
      speakToggle.addEventListener("click", function (e) {
        e.preventDefault();
        speakReplies = !speakReplies;
        try {
          localStorage.setItem("vanessa_speak_replies", speakReplies ? "1" : "0");
        } catch (err) {}
        setSpeakUi();
        if (!speakReplies && voice) voice.stopSpeak();
        appendMsg("sys", speakReplies ? "I’ll speak my replies." : "Voice replies muted.");
      });
    }

    setSpeakUi();
  }

  function maybeSpeak(reply) {
    if (!speakReplies || !voice || !voice.ttsSupported) return;
    // Skip pure system-y / handoff blocks for short spoken summary already cleaned in voice layer
    voice.speak(reply);
  }

  function setOpen(open) {
    root.classList.toggle("open", !!open);
    try {
      localStorage.setItem("vanessa_open", open ? "1" : "0");
    } catch (e) {}
    if (open && input) setTimeout(function () { input.focus(); }, 50);
    if (!open && voice) {
      // Keep conversation preference but stop mics/speech when closed
      voice.stopListen();
      voice.stopSpeak();
      setMicUi(false);
      if (!(voice && voice.conversation)) setVoiceStatus("idle", "Idle");
    }
  }

  function clearShot() {
    pendingShot = null;
    if (shotPreview) shotPreview.hidden = true;
    if (shotImg) shotImg.removeAttribute("src");
  }

  function setShot(dataUrl) {
    pendingShot = dataUrl || null;
    if (!pendingShot) {
      clearShot();
      return;
    }
    if (shotImg) shotImg.src = pendingShot;
    if (shotPreview) shotPreview.hidden = false;
  }

  async function capturePageSnapshot() {
    if (typeof html2canvas !== "function") {
      throw new Error("Snapshot library failed to load — refresh and try again.");
    }
    setErr("");
    if (shotBtn) {
      shotBtn.disabled = true;
      shotBtn.classList.add("busy");
    }
    const wasOpen = root.classList.contains("open");
    root.style.visibility = "hidden";
    try {
      await new Promise(function (r) {
        requestAnimationFrame(function () {
          requestAnimationFrame(r);
        });
      });
      const canvas = await html2canvas(document.documentElement, {
        scale: Math.min(1, 1200 / Math.max(document.documentElement.scrollWidth || 1200, 1)),
        useCORS: true,
        allowTaint: true,
        logging: false,
        backgroundColor: "#0a0a12",
        windowWidth: document.documentElement.scrollWidth,
        windowHeight: Math.min(document.documentElement.scrollHeight, 4000),
      });
      let out = canvas;
      if (canvas.width > 1280) {
        const ratio = 1280 / canvas.width;
        const c2 = document.createElement("canvas");
        c2.width = 1280;
        c2.height = Math.max(1, Math.round(canvas.height * ratio));
        c2.getContext("2d").drawImage(canvas, 0, 0, c2.width, c2.height);
        out = c2;
      }
      let quality = 0.72;
      let dataUrl = out.toDataURL("image/jpeg", quality);
      while (dataUrl.length > 700000 && quality > 0.4) {
        quality -= 0.08;
        dataUrl = out.toDataURL("image/jpeg", quality);
      }
      if (dataUrl.length > 900000) {
        throw new Error("Snapshot still too large — try a simpler view.");
      }
      setShot(dataUrl);
      appendMsg("sys", "Page snapshot attached (" + Math.round(dataUrl.length / 1024) + " KB).");
    } finally {
      root.style.visibility = "";
      if (shotBtn) {
        shotBtn.disabled = false;
        shotBtn.classList.remove("busy");
      }
      if (wasOpen) setOpen(true);
    }
  }

  if (fab) {
    fab.addEventListener("click", function () {
      setOpen(!root.classList.contains("open"));
    });
  }
  if (closeBtn) {
    closeBtn.addEventListener("click", function () {
      setOpen(false);
    });
  }

  document.querySelectorAll(".v-tab").forEach(function (btn) {
    btn.addEventListener("click", function () {
      agent = btn.getAttribute("data-agent") || "vanessa";
      try {
        localStorage.setItem("admin_companion_agent", agent);
      } catch (e) {}
      updateChrome();
    });
  });

  document.querySelectorAll(".v-tier").forEach(function (btn) {
    btn.addEventListener("click", function () {
      modelTier = btn.getAttribute("data-tier") || "fast";
      try {
        localStorage.setItem("vanessa_model_tier", modelTier);
      } catch (e) {}
      updateChrome();
      appendMsg(
        "sys",
        modelTier === "smart"
          ? "Vanessa model → Smart (stronger, costs more)"
          : "Vanessa model → Fast (cheaper, talk & relay)"
      );
    });
  });

  try {
    if (localStorage.getItem("vanessa_open") === "1") setOpen(true);
  } catch (e) {}

  setupAvatarPicker();
  setupVoice();
  updateChrome();

  // Restore talk mode if user left it on (don't auto-start mic until they open / click — privacy)
  try {
    if (localStorage.getItem("vanessa_talk_mode") === "1" && voice) {
      setTalkUi(false); // visual off until they hit Talk again this session
    }
  } catch (e) {}

  if (shotBtn) {
    shotBtn.addEventListener("click", function (e) {
      e.preventDefault();
      capturePageSnapshot().catch(function (ex) {
        setErr(ex.message || "Snapshot failed");
      });
    });
  }
  if (shotClear) {
    shotClear.addEventListener("click", function (e) {
      e.preventDefault();
      clearShot();
    });
  }

  if (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      send();
    });
  }
  if (input) {
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        send();
      }
    });
  }

  async function postChat(payload) {
    let lastErr = null;
    for (let i = 0; i < CHAT_URLS.length; i++) {
      try {
        const res = await fetch(CHAT_URLS[i], {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/json",
            Accept: "application/json",
          },
          body: JSON.stringify(payload),
        });
        const data = await res.json().catch(function () {
          return {};
        });
        // 404 on wrong path → try next
        if (res.status === 404 && i < CHAT_URLS.length - 1) {
          lastErr = new Error(data.error || "Not found");
          continue;
        }
        return { res: res, data: data };
      } catch (net) {
        lastErr = net;
      }
    }
    throw lastErr || new Error("Network error");
  }

  /**
   * @param {string} [forcedText] — spoken text from Talk mode (don't rely on input race)
   */
  async function send(forcedText) {
    setErr("");
    if (busy) return;
    if (voice && voice.listening) voice.stopListen();
    if (voice) voice.stopSpeak();

    const text = String(
      forcedText != null && String(forcedText).trim()
        ? forcedText
        : (input && input.value) || ""
    ).trim();
    const shot = pendingShot;
    if (!text && !shot) return;

    busy = true;
    setVoiceStatus("thinking", "Thinking");

    const displayText = text || "(page snapshot — see attached image)";
    appendMsg("user", displayText + (shot ? "  [+snapshot]" : ""));
    histories[agent].push({ role: "user", content: displayText });
    if (input) input.value = "";
    if (sendBtn) {
      sendBtn.disabled = true;
      sendBtn.textContent = "…";
    }

    const who = agent === "mira" ? "Mira" : "Vanessa";
    const isVoiceTurn = !!(speakReplies || (voice && voice.conversation));
    // Keep under 4000 server limit; voice turns stay short
    let messageForApi = displayText;
    if (isVoiceTurn) {
      messageForApi =
        displayText +
        "\n\n[VOICE MODE] Speak briefly (2–5 short sentences). " +
        "Page: " +
        PAGE_CTX +
        ". " +
        "If Nick wants a code/UI change, put [PASS_TO_SAL] after the spoken reply.";
    } else {
      messageForApi =
        displayText +
        "\n\n---\n[Page context for " +
        who +
        " / Sal]\n" +
        PAGE_CTX +
        (shot ? "\n[SNAPSHOT attached]" : "") +
        "\nIf Nick wants a UI/code change, emit [PASS_TO_SAL] with a precise brief.";
    }
    if (messageForApi.length > 3900) {
      messageForApi = messageForApi.slice(0, 3900);
    }

    const payload = {
      agent: agent,
      message: messageForApi,
      history: histories[agent].slice(-10),
    };
    if (agent === "vanessa") {
      payload.model_tier = modelTier;
    }
    if (shot) payload.image = shot;

    try {
      const out = await postChat(payload);
      const res = out.res;
      const data = out.data;
      if (!res.ok) {
        var detail = data.error || data.message || "HTTP " + res.status;
        if (res.status === 403 || res.status === 404) {
          detail =
            res.status === 404
              ? "Admin only / not found — log in as admin, hard-refresh (Cmd+Shift+R)."
              : "Admin only — log in with your admin account, then hard-refresh.";
        } else if (res.status === 503 || /not configured/i.test(String(detail))) {
          detail = "Companion API key/model not configured on the server.";
        }
        throw new Error(detail);
      }
      const reply = data.reply || "…";
      appendMsg("bot", reply);
      histories[agent].push({ role: "assistant", content: reply });
      clearShot();

      if (data.model || data.model_tier_label) {
        appendMsg(
          "sys",
          "model: " +
            (data.model || "?") +
            (data.model_tier_label ? " · " + data.model_tier_label : "")
        );
      }

      if (data.passed_to_sal) {
        if (data.build_queued && data.build_task) {
          appendMsg(
            "sys",
            "Passed to Sal · fixer queued · id " + (data.build_task.id || "?")
          );
        } else if (data.sal_reply) {
          appendMsg("sys", "Passed to Sal — open Support page for Sal panel/inbox.");
        } else {
          appendMsg("sys", "Passed to Sal.");
        }
      }

      // Speak reply; Talk mode re-listens after TTS (or immediately if Speak off)
      if (speakReplies && voice && voice.ttsSupported) {
        maybeSpeak(reply);
      } else if (voice && voice.conversation) {
        voice.armConversationListen();
        setVoiceStatus("listening", "Listening");
      }
    } catch (ex) {
      var msg = ex.message || "Network error";
      setErr(msg);
      const fail =
        "Couldn't complete that: " +
        msg +
        "\n\nTip: Chrome/Edge + allow mic. Hard-refresh after login.";
      appendMsg("bot", fail);
      if (speakReplies && voice) {
        maybeSpeak("Sorry boss — that failed. " + msg);
      } else if (voice && voice.conversation) {
        voice.armConversationListen();
      }
    } finally {
      busy = false;
      if (sendBtn) {
        sendBtn.disabled = false;
        sendBtn.textContent = "Send";
      }
      if (input) input.focus();
      // TTS path arms listen on speak end; if no TTS, arm now
      if (voice && voice.conversation && !(speakReplies && voice.ttsSupported)) {
        voice.armConversationListen();
        setVoiceStatus("listening", "Listening");
      }
    }
  }
})();
