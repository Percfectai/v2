/**
 * Vanessa / Mira voice — mic STT (xAI server) + Grok Ara/Eve TTS + conversation loop.
 *
 * STT: MediaRecorder → admin-only POST /studios/support/stt (xAI speech-to-text).
 *      Key never in the browser. Browser SpeechRecognition is NOT used (was broken).
 * TTS: xAI Ara (Vanessa) / Eve (Mira) via /studios/support/tts.
 */
(function (global) {
  "use strict";

  function canRecord() {
    return !!(
      global.MediaRecorder &&
      global.navigator &&
      navigator.mediaDevices &&
      typeof navigator.mediaDevices.getUserMedia === "function"
    );
  }

  function cleanForSpeech(text) {
    if (!text) return "";
    let t = String(text);
    t = t.replace(/\[PASS_TO_SAL\][\s\S]*$/i, "");
    t = t.replace(/###\s*BUILD_TASK[\s\S]*$/i, "");
    t = t.replace(/```[\s\S]*?```/g, " ");
    t = t.replace(/\[Page context[\s\S]*$/i, "");
    t = t.replace(/\[VOICE MODE\][\s\S]*$/i, "");
    t = t.replace(/model:\s*[^\n]+/gi, "");
    t = t.replace(/\*\*?/g, "");
    t = t.replace(/\s+/g, " ").trim();
    if (t.length > 900) t = t.slice(0, 900) + "…";
    return t;
  }

  function pickMimeType() {
    if (!global.MediaRecorder || !MediaRecorder.isTypeSupported) {
      return "";
    }
    const candidates = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus",
      "audio/mp4",
    ];
    for (let i = 0; i < candidates.length; i++) {
      if (MediaRecorder.isTypeSupported(candidates[i])) return candidates[i];
    }
    return "";
  }

  function createVoice(opts) {
    opts = opts || {};
    const recordOk = canRecord();
    const api = {
      sttSupported: recordOk,
      ttsSupported: true,
      listening: false,
      speaking: false,
      conversation: false,
      _wantListen: false,
      _base: "",
      _restartTimer: null,
      _audio: null,
      _audioUrl: null,
      _speakGen: 0,
      _stream: null,
      _recorder: null,
      _chunks: [],
      _mime: "",
      _vadTimer: null,
      _hadSpeech: false,
      _silenceMs: 0,
      _recording: false,
      _transcribing: false,
      _analyser: null,
      _audioCtx: null,
      _raf: null,
      _maxRecordTimer: null,
    };

    function paused() {
      return !!(opts.isPaused && opts.isPaused());
    }

    function ttsUrls() {
      return [
        "/studios/support/tts",
        "/percfectstudios/support/tts",
        "/api/support/tts",
      ];
    }

    function sttUrls() {
      return [
        "/studios/support/stt",
        "/percfectstudios/support/stt",
        "/api/support/stt",
      ];
    }

    function voiceId() {
      if (opts.getVoiceId) return opts.getVoiceId() || "ara";
      return opts.voiceId || "ara";
    }

    function agentName() {
      if (opts.getAgent) return opts.getAgent() || "vanessa";
      return "vanessa";
    }

    function clearRestart() {
      if (api._restartTimer) {
        clearTimeout(api._restartTimer);
        api._restartTimer = null;
      }
    }

    function scheduleListen(ms) {
      clearRestart();
      api._restartTimer = setTimeout(function () {
        api._restartTimer = null;
        if (!api.conversation || !api._wantListen) return;
        if (api.speaking || paused() || api._transcribing) return;
        api.startListen();
      }, ms || 500);
    }

    function killAudio() {
      if (api._audio) {
        try {
          api._audio.pause();
          api._audio.src = "";
        } catch (e) {}
        api._audio = null;
      }
      if (api._audioUrl) {
        try {
          URL.revokeObjectURL(api._audioUrl);
        } catch (e2) {}
        api._audioUrl = null;
      }
      try {
        if (global.speechSynthesis) global.speechSynthesis.cancel();
      } catch (e3) {}
    }

    function stopVad() {
      if (api._raf) {
        try {
          cancelAnimationFrame(api._raf);
        } catch (e) {}
        api._raf = null;
      }
      if (api._vadTimer) {
        clearInterval(api._vadTimer);
        api._vadTimer = null;
      }
      if (api._maxRecordTimer) {
        clearTimeout(api._maxRecordTimer);
        api._maxRecordTimer = null;
      }
      api._analyser = null;
      if (api._audioCtx) {
        try {
          api._audioCtx.close();
        } catch (e2) {}
        api._audioCtx = null;
      }
    }

    function stopStreamTracks() {
      if (api._stream) {
        try {
          api._stream.getTracks().forEach(function (t) {
            try {
              t.stop();
            } catch (e) {}
          });
        } catch (e2) {}
        api._stream = null;
      }
    }

    function finishSpeak(onEnd, gen) {
      if (gen != null && gen !== api._speakGen) return;
      api.speaking = false;
      killAudio();
      if (opts.onSpeakEnd) opts.onSpeakEnd();
      if (onEnd) onEnd();
      if (api.conversation && api._wantListen && !paused()) scheduleListen(450);
    }

    async function speakCloud(clean, onEnd, gen) {
      const payload = {
        text: clean,
        agent: agentName(),
        voice_id: voiceId(),
      };
      let lastErr = null;
      const urls = ttsUrls();
      for (let i = 0; i < urls.length; i++) {
        if (gen !== api._speakGen) return;
        try {
          const res = await fetch(urls[i], {
            method: "POST",
            credentials: "same-origin",
            headers: {
              "Content-Type": "application/json",
              Accept: "audio/mpeg, application/json",
            },
            body: JSON.stringify(payload),
          });
          if (gen !== api._speakGen) return;
          if (res.status === 404 && i < urls.length - 1) continue;
          if (!res.ok) {
            const errJ = await res.json().catch(function () {
              return {};
            });
            lastErr = new Error(errJ.error || "TTS HTTP " + res.status);
            if (res.status === 404 || res.status === 503) continue;
            throw lastErr;
          }
          const ct = (res.headers.get("content-type") || "").toLowerCase();
          if (ct.indexOf("json") >= 0) {
            const errJ = await res.json().catch(function () {
              return {};
            });
            throw new Error(errJ.error || "TTS returned JSON error");
          }
          const blob = await res.blob();
          if (!blob || blob.size < 100) throw new Error("Empty audio");
          if (gen !== api._speakGen) return;

          try {
            if (global.speechSynthesis) global.speechSynthesis.cancel();
          } catch (eC) {}
          killAudio();

          const url = URL.createObjectURL(blob);
          api._audioUrl = url;
          const audio = new Audio(url);
          api._audio = audio;
          api.speaking = true;
          if (opts.onSpeakStart) opts.onSpeakStart();

          audio.onended = function () {
            finishSpeak(onEnd, gen);
          };
          audio.onerror = function () {
            if (gen !== api._speakGen) return;
            finishSpeak(function () {
              if (opts.onError) opts.onError("Ara voice playback failed.");
              if (onEnd) onEnd();
            }, gen);
          };
          try {
            await audio.play();
          } catch (playErr) {
            if (gen !== api._speakGen) return;
            finishSpeak(function () {
              if (opts.onError) {
                opts.onError(
                  "Could not play Ara voice — click the page once, then try again."
                );
              }
              if (onEnd) onEnd();
            }, gen);
          }
          return;
        } catch (e) {
          lastErr = e;
        }
      }
      if (gen !== api._speakGen) return;
      api.speaking = false;
      if (opts.onError) {
        opts.onError(
          (lastErr && lastErr.message) ||
            "Ara voice unavailable (server). Check admin login + TTS key."
        );
      }
      if (opts.onSpeakEnd) opts.onSpeakEnd();
      if (onEnd) onEnd();
      if (api.conversation && api._wantListen && !paused()) scheduleListen(600);
    }

    api.speak = function (text, onEnd) {
      const clean = cleanForSpeech(text);
      if (!clean) {
        if (onEnd) onEnd();
        if (api.conversation && api._wantListen && !paused()) scheduleListen(400);
        return;
      }
      api._speakGen += 1;
      const gen = api._speakGen;

      try {
        if (global.speechSynthesis) global.speechSynthesis.cancel();
      } catch (e0) {}
      // Stop mic while she talks
      hardStopRecorder(false);
      api.listening = false;
      killAudio();
      api.speaking = true;
      if (opts.onSpeakStart) opts.onSpeakStart();
      speakCloud(clean, onEnd, gen);
    };

    api.stopSpeak = function () {
      api._speakGen += 1;
      killAudio();
      try {
        if (global.speechSynthesis) global.speechSynthesis.cancel();
      } catch (e) {}
      api.speaking = false;
    };

    // --- Cloud STT ---
    async function transcribeBlob(blob) {
      const urls = sttUrls();
      let lastErr = null;
      const ext =
        (blob && blob.type && blob.type.indexOf("ogg") >= 0 && "ogg") ||
        (blob && blob.type && blob.type.indexOf("mp4") >= 0 && "m4a") ||
        "webm";
      const filename = "vanessa." + ext;

      for (let i = 0; i < urls.length; i++) {
        try {
          const form = new FormData();
          // Non-file fields first; file last (xAI rule)
          form.append("format", "true");
          form.append("language", "en");
          form.append("file", blob, filename);

          const res = await fetch(urls[i], {
            method: "POST",
            credentials: "same-origin",
            body: form,
          });
          if (res.status === 404 && i < urls.length - 1) continue;
          const body = await res.json().catch(function () {
            return {};
          });
          if (!res.ok) {
            lastErr = new Error(body.error || "STT HTTP " + res.status);
            if (res.status === 404 || res.status === 503) continue;
            throw lastErr;
          }
          const text = (body.text || "").trim();
          return text;
        } catch (e) {
          lastErr = e;
        }
      }
      throw lastErr || new Error("Speech-to-text unavailable");
    }

    function hardStopRecorder(finalize) {
      stopVad();
      const rec = api._recorder;
      api._recorder = null;
      api._recording = false;
      if (rec && rec.state !== "inactive") {
        try {
          if (finalize) rec.stop();
          else rec.stop();
        } catch (e) {
          try {
            rec.stop();
          } catch (e2) {}
        }
      } else if (!finalize) {
        stopStreamTracks();
        api._chunks = [];
      }
      // If not finalizing, drop stream immediately
      if (!finalize) {
        stopStreamTracks();
        api._chunks = [];
      }
    }

    function startVad(stream) {
      stopVad();
      api._hadSpeech = false;
      api._silenceMs = 0;
      try {
        const AC = global.AudioContext || global.webkitAudioContext;
        if (!AC) return;
        const ctx = new AC();
        api._audioCtx = ctx;
        const source = ctx.createMediaStreamSource(stream);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 2048;
        source.connect(analyser);
        api._analyser = analyser;
        const data = new Uint8Array(analyser.fftSize);

        // Poll RMS every 80ms — end utterance after speech then ~1.1s silence
        api._vadTimer = setInterval(function () {
          if (!api._recording || !api._analyser) return;
          api._analyser.getByteTimeDomainData(data);
          let sum = 0;
          for (let i = 0; i < data.length; i++) {
            const v = (data[i] - 128) / 128;
            sum += v * v;
          }
          const rms = Math.sqrt(sum / data.length);
          // Threshold tuned for laptop mics
          if (rms > 0.025) {
            api._hadSpeech = true;
            api._silenceMs = 0;
            if (opts.onPartial) {
              opts.onPartial({
                final: "",
                interim: "…",
                base: api._base,
              });
            }
          } else if (api._hadSpeech) {
            api._silenceMs += 80;
            if (api._silenceMs >= 1100) {
              // End of phrase — stop recorder (triggers onstop → STT)
              try {
                if (api._recorder && api._recorder.state === "recording") {
                  api._recorder.stop();
                }
              } catch (e) {}
            }
          }
        }, 80);
      } catch (e) {
        // No VAD — user must click mic/Talk again to stop (max timer still ends)
      }
    }

    async function onRecorderStopped() {
      api.listening = false;
      api._recording = false;
      stopVad();
      stopStreamTracks();
      if (opts.onListenEnd) opts.onListenEnd();

      const chunks = api._chunks || [];
      api._chunks = [];
      if (!chunks.length) {
        if (api.conversation && api._wantListen && !paused()) scheduleListen(600);
        return;
      }
      const mime = api._mime || chunks[0].type || "audio/webm";
      const blob = new Blob(chunks, { type: mime });
      if (blob.size < 800) {
        // Too short — re-listen in talk mode
        if (api.conversation && api._wantListen && !paused()) scheduleListen(500);
        return;
      }

      api._transcribing = true;
      if (opts.onPartial) {
        opts.onPartial({ final: "", interim: "Transcribing…", base: api._base });
      }
      try {
        const text = await transcribeBlob(blob);
        api._transcribing = false;
        if (!text) {
          if (opts.onError) {
            opts.onError("Didn't catch that — speak again a bit louder.");
          }
          if (api.conversation && api._wantListen && !paused()) scheduleListen(700);
          return;
        }
        if (opts.onPartial) {
          opts.onPartial({
            final: text,
            interim: "",
            base: api._base,
          });
        }
        if (api.conversation) {
          api._wantListen = false;
          clearRestart();
        }
        if (opts.onFinal) opts.onFinal(text);
      } catch (e) {
        api._transcribing = false;
        let msg = (e && e.message) || "Speech-to-text failed";
        if (/404|Not found/i.test(msg)) {
          msg = "Voice STT not available — admin login required, or deploy STT route.";
        } else if (/503|key missing|STT key/i.test(msg)) {
          msg =
            "STT key missing on server — set XAI_STT_API_KEY or XAI_TTS_API_KEY (voice silo).";
        }
        if (opts.onError) opts.onError(msg);
        if (api.conversation && api._wantListen && !paused()) scheduleListen(1200);
      }
    }

    api.startListen = function () {
      if (!recordOk) {
        if (opts.onError) {
          opts.onError(
            "Mic recording needs a modern browser (Chrome, Edge, or Firefox)."
          );
        }
        return;
      }
      if (paused() || api._transcribing) return;
      if (api.speaking) api.stopSpeak();
      clearRestart();
      api._wantListen = true;

      if (api.conversation) {
        api._base = "";
      } else {
        api._base = (opts.getInputText && opts.getInputText()) || "";
        if (api._base && !/\s$/.test(api._base)) api._base += " ";
      }

      // Tear down any prior recorder
      hardStopRecorder(false);

      navigator.mediaDevices
        .getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            channelCount: 1,
          },
        })
        .then(function (stream) {
          if (!api._wantListen || paused()) {
            stream.getTracks().forEach(function (t) {
              t.stop();
            });
            return;
          }
          api._stream = stream;
          api._chunks = [];
          api._mime = pickMimeType();
          let rec;
          try {
            rec = api._mime
              ? new MediaRecorder(stream, { mimeType: api._mime })
              : new MediaRecorder(stream);
          } catch (eRec) {
            rec = new MediaRecorder(stream);
          }
          api._recorder = rec;
          api._mime = rec.mimeType || api._mime || "audio/webm";

          rec.ondataavailable = function (ev) {
            if (ev.data && ev.data.size > 0) api._chunks.push(ev.data);
          };
          rec.onerror = function () {
            if (opts.onError) opts.onError("Mic recorder error — try Talk again.");
            hardStopRecorder(false);
            api.listening = false;
            if (opts.onListenEnd) opts.onListenEnd();
          };
          rec.onstop = function () {
            onRecorderStopped();
          };

          try {
            rec.start(250); // timeslice for chunks
          } catch (eStart) {
            if (opts.onError) {
              opts.onError("Could not start mic — allow Microphone for this site.");
            }
            hardStopRecorder(false);
            return;
          }

          api._recording = true;
          api.listening = true;
          if (opts.onListenStart) opts.onListenStart();
          startVad(stream);

          // Safety cap 45s per utterance
          api._maxRecordTimer = setTimeout(function () {
            try {
              if (api._recorder && api._recorder.state === "recording") {
                api._recorder.stop();
              }
            } catch (eMax) {}
          }, 45000);
        })
        .catch(function (err) {
          api.listening = false;
          let msg = "Mic blocked or unavailable.";
          const name = (err && err.name) || "";
          if (name === "NotAllowedError" || name === "PermissionDeniedError") {
            msg =
              "Mic blocked — click the lock icon → allow Microphone for this site, then hit Talk again.";
          } else if (name === "NotFoundError") {
            msg = "No mic found — plug in a mic or check system sound settings.";
          }
          if (opts.onError) opts.onError(msg);
          if (opts.onListenEnd) opts.onListenEnd();
        });
    };

    api.stopListen = function () {
      api._wantListen = false;
      clearRestart();
      if (api._recorder && api._recorder.state === "recording") {
        try {
          api._recorder.stop();
        } catch (e) {
          hardStopRecorder(false);
          api.listening = false;
        }
      } else {
        hardStopRecorder(false);
        api.listening = false;
        if (opts.onListenEnd) opts.onListenEnd();
      }
    };

    api.toggleListen = function () {
      if (api.listening || api._recording) api.stopListen();
      else api.startListen();
    };

    api.armConversationListen = function () {
      if (!api.conversation) return;
      api._wantListen = true;
      if (!api.speaking && !paused() && !api._transcribing) scheduleListen(350);
    };

    api.setConversation = function (on) {
      api.conversation = !!on;
      if (!api.conversation) {
        api.stopListen();
      } else {
        api._wantListen = true;
      }
    };

    api.stopAll = function () {
      api.conversation = false;
      api._wantListen = false;
      clearRestart();
      hardStopRecorder(false);
      api.listening = false;
      api.stopSpeak();
    };

    return api;
  }

  global.VanessaVoice = {
    create: createVoice,
    cleanForSpeech: cleanForSpeech,
    sttSupported: canRecord(),
    ttsSupported: true,
  };
})(typeof window !== "undefined" ? window : this);
