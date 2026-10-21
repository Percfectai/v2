/**
 * Shared speech-to-text (Web Speech API).
 * Chrome/Edge best; Safari partial; Firefox often unsupported.
 *
 * Usage:
 *   const stt = PercfectSTT.create({ onText, onError, onStart, onEnd });
 *   stt.toggle();  // start/stop
 *   stt.supported  // boolean
 */
(function (global) {
  "use strict";

  function getRecognitionCtor() {
    return (
      global.SpeechRecognition ||
      global.webkitSpeechRecognition ||
      global.mozSpeechRecognition ||
      null
    );
  }

  function create(opts) {
    opts = opts || {};
    const Ctor = getRecognitionCtor();
    const api = {
      supported: !!Ctor,
      listening: false,
      _rec: null,
      _want: false,
    };

    if (!Ctor) {
      api.toggle = function () {
        if (opts.onError) {
          opts.onError(
            "Speech-to-text not supported in this browser. Use Chrome or Edge, or type."
          );
        }
      };
      api.start = api.toggle;
      api.stop = function () {};
      return api;
    }

    const rec = new Ctor();
    // continuous:false is more reliable across browsers (esp. Safari)
    rec.continuous = opts.continuous === true;
    rec.interimResults = opts.interimResults !== false;
    rec.lang = opts.lang || "en-US";
    rec.maxAlternatives = 1;
    api._rec = rec;

    rec.onstart = function () {
      api.listening = true;
      if (opts.onStart) opts.onStart();
    };
    rec.onend = function () {
      api.listening = false;
      // auto-restart if user still wants continuous listen
      if (api._want && opts.continuous === true) {
        try {
          rec.start();
          return;
        } catch (e) {}
      }
      if (opts.onEnd) opts.onEnd();
    };
    rec.onerror = function (ev) {
      const err = (ev && ev.error) || "speech_error";
      if (err === "aborted" || err === "no-speech") {
        // benign — user paused or silence
        return;
      }
      api._want = false;
      api.listening = false;
      let msg = "Mic error: " + err;
      if (err === "not-allowed") {
        msg = "Mic blocked — allow microphone for percfectai.com in the browser.";
      } else if (err === "network") {
        msg = "Speech service network error — try again or type.";
      }
      if (opts.onError) opts.onError(msg);
      if (opts.onEnd) opts.onEnd();
    };
    rec.onresult = function (ev) {
      let interim = "";
      let final = "";
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const r = ev.results[i];
        const t = (r[0] && r[0].transcript) || "";
        if (r.isFinal) final += t;
        else interim += t;
      }
      if (opts.onText) {
        opts.onText({
          final: final.trim(),
          interim: interim.trim(),
          raw: ev,
        });
      }
    };

    api.start = function () {
      api._want = true;
      try {
        rec.start();
      } catch (e) {
        // already started
        try {
          rec.stop();
          setTimeout(function () {
            try {
              rec.start();
            } catch (e2) {
              if (opts.onError) opts.onError("Could not start mic.");
            }
          }, 200);
        } catch (e3) {
          if (opts.onError) opts.onError("Could not start mic.");
        }
      }
    };
    api.stop = function () {
      api._want = false;
      try {
        rec.stop();
      } catch (e) {}
      api.listening = false;
      if (opts.onEnd) opts.onEnd();
    };
    api.toggle = function () {
      if (api.listening || api._want) api.stop();
      else api.start();
    };
    return api;
  }

  global.PercfectSTT = { create: create, supported: !!getRecognitionCtor() };
})(typeof window !== "undefined" ? window : this);
