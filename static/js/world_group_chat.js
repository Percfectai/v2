/**
 * Percfect multi-body 3D world group chat.
 * Shared feed for everyone on Colosseum / Field / /3d — room=3d (type=3d_world).
 * Bodies: optional "speak as" seat so messages map to multi-body roster labels.
 *
 * Usage:
 *   PercfectWorldChat.mount({ room: '3d', seats: ['Pilot','Iron',...], loggedIn: true });
 * Or auto-mount when #wgc-root exists / data-world-chat attribute.
 */
(function (global) {
  'use strict';

  var DEFAULT_SEATS = [
    'Pilot', 'Iron', 'Meshy-6', 'Shot', 'Meshy-B', 'Meshy-C',
    'Voltage', 'Ashley', 'Vanessa', 'Sal', 'Mira', 'Rook', 'Vex', 'Moss', 'Knox',
  ];

  function esc(s) {
    return String(s || '').replace(/[&<>"']/g, function (m) {
      return ({ '&': '&', '<': '<', '>': '>', '"': '"', "'": '&#39;' })[m];
    });
  }

  function injectStyles() {
    if (document.getElementById('wgc-styles')) return;
    var css = [
      '#wgc-root, .wgc-root {',
      '  position: fixed; z-index: 40; right: 0.75rem; bottom: 0.75rem;',
      '  width: min(360px, calc(100vw - 1.5rem));',
      '  max-height: min(42vh, 380px);',
      '  display: flex; flex-direction: column;',
      '  background: rgba(8, 12, 18, 0.92);',
      '  border: 1px solid rgba(0, 255, 136, 0.28);',
      '  border-radius: 14px;',
      '  box-shadow: 0 12px 40px rgba(0,0,0,0.55);',
      '  font-family: system-ui, -apple-system, sans-serif;',
      '  color: #e8eef5; pointer-events: auto;',
      '}',
      '#wgc-root.wgc-collapsed { max-height: none; }',
      '#wgc-root.wgc-collapsed .wgc-body { display: none; }',
      '.wgc-head {',
      '  display: flex; align-items: center; justify-content: space-between;',
      '  gap: 0.5rem; padding: 0.45rem 0.65rem;',
      '  border-bottom: 1px solid rgba(255,255,255,0.08);',
      '  cursor: pointer; user-select: none;',
      '}',
      '.wgc-title { font-size: 0.72rem; letter-spacing: 0.06em; text-transform: uppercase; color: #86efac; font-weight: 700; }',
      '.wgc-sub { font-size: 0.62rem; color: #94a3b8; margin-left: 0.35rem; font-weight: 500; text-transform: none; letter-spacing: 0; }',
      '.wgc-toggle { background: transparent; border: none; color: #cbd5e1; font-size: 0.85rem; cursor: pointer; }',
      '.wgc-body { display: flex; flex-direction: column; min-height: 0; flex: 1; }',
      '.wgc-feed {',
      '  flex: 1; overflow-y: auto; padding: 0.5rem 0.65rem;',
      '  display: flex; flex-direction: column; gap: 0.45rem;',
      '  min-height: 120px; max-height: 220px;',
      '}',
      '.wgc-empty { color: #64748b; font-size: 0.75rem; text-align: center; margin: auto; padding: 0.75rem; }',
      '.wgc-msg { display: flex; flex-direction: column; gap: 0.12rem; max-width: 95%; }',
      '.wgc-meta { font-size: 0.62rem; color: #94a3b8; }',
      '.wgc-bubble {',
      '  background: rgba(30, 41, 59, 0.95); border: 1px solid rgba(148,163,184,0.2);',
      '  border-radius: 10px; padding: 0.35rem 0.55rem; font-size: 0.8rem;',
      '  word-break: break-word; line-height: 1.35;',
      '}',
      '.wgc-msg.mine .wgc-bubble { background: rgba(0, 120, 80, 0.45); border-color: rgba(0,255,136,0.35); }',
      '.wgc-msg.agent .wgc-bubble { background: rgba(30, 58, 90, 0.9); border-color: rgba(96,165,250,0.4); }',
      '.wgc-msg.agent .wgc-meta { color: #93c5fd; }',
      '.wgc-compose {',
      '  display: flex; flex-direction: column; gap: 0.35rem;',
      '  padding: 0.45rem 0.55rem 0.55rem;',
      '  border-top: 1px solid rgba(255,255,255,0.08);',
      '}',
      '.wgc-as {',
      '  display: flex; align-items: center; gap: 0.35rem;',
      '  font-size: 0.65rem; color: #94a3b8;',
      '}',
      '.wgc-as select {',
      '  flex: 1; background: #0f172a; color: #e2e8f0; border: 1px solid rgba(148,163,184,0.3);',
      '  border-radius: 8px; padding: 0.25rem 0.35rem; font-size: 0.7rem;',
      '}',
      '.wgc-row { display: flex; gap: 0.35rem; }',
      '.wgc-row input {',
      '  flex: 1; background: #0f172a; color: #f1f5f9; border: 1px solid rgba(148,163,184,0.35);',
      '  border-radius: 10px; padding: 0.45rem 0.6rem; font-size: 0.8rem;',
      '}',
      '.wgc-row input:focus { outline: none; border-color: #00ff88; }',
      '.wgc-send {',
      '  border: none; border-radius: 10px; padding: 0.45rem 0.75rem;',
      '  background: #00c86a; color: #04140c; font-weight: 700; font-size: 0.78rem; cursor: pointer;',
      '}',
      '.wgc-send:disabled { opacity: 0.5; cursor: not-allowed; }',
      '.wgc-err { color: #f87171; font-size: 0.68rem; min-height: 0.9rem; }',
      '.wgc-login { font-size: 0.72rem; color: #fbbf24; text-align: center; padding: 0.35rem; line-height: 1.4; }',
      '.wgc-login a { color: #00ff88; font-weight: 700; text-decoration: underline; }',
      '#wgc-root input, #wgc-root select, #wgc-root button, .wgc-root input, .wgc-root select, .wgc-root button {',
      '  pointer-events: auto !important;',
      '}',
      '@media (max-width: 640px) {',
      '  #wgc-root, .wgc-root { left: 0.5rem; right: 0.5rem; width: auto; bottom: 0.5rem; }',
      '}',
    ].join('\n');
    var st = document.createElement('style');
    st.id = 'wgc-styles';
    st.textContent = css;
    document.head.appendChild(st);
  }

  function mount(opts) {
    opts = opts || {};
    injectStyles();

    var room = opts.room || '3d';
    var seats = opts.seats || DEFAULT_SEATS;
    var loggedIn = opts.loggedIn;
    if (typeof loggedIn !== 'boolean') {
      loggedIn = !!(opts.username || (global.current_user && global.current_user.is_authenticated));
    }
    var me = opts.username || '';
    var pollMs = opts.pollMs || 2500;
    var title = opts.title || 'World chat';
    var subtitle = opts.subtitle || 'everyone on this board';

    var root = opts.el || document.getElementById('wgc-root');
    if (!root) {
      root = document.createElement('div');
      root.id = 'wgc-root';
      root.className = 'wgc-root';
      document.body.appendChild(root);
    }
    root.setAttribute('data-room', room);

    var seatOpts = seats.map(function (s) {
      return '<option value="' + esc(s) + '">' + esc(s) + '</option>';
    }).join('');

    root.innerHTML =
      '<div class="wgc-head" id="wgc-head" role="button" tabindex="0" aria-expanded="true">' +
      '<span class="wgc-title">' + esc(title) +
      '<span class="wgc-sub">' + esc(subtitle) + '</span></span>' +
      '<button type="button" class="wgc-toggle" id="wgc-toggle" aria-label="Collapse">▾</button>' +
      '</div>' +
      '<div class="wgc-body" id="wgc-body">' +
      '<div class="wgc-feed" id="wgc-feed"><div class="wgc-empty" id="wgc-empty">No messages yet — say hi to the sand</div></div>' +
      '<div class="wgc-compose">' +
      (loggedIn
        ? '<label class="wgc-as">Speak as ' +
          '<select id="wgc-as" aria-label="Body seat">' +
          '<option value="">You (' + esc(me || 'logged in') + ')</option>' +
          seatOpts +
          '</select></label>' +
          '<div class="wgc-row">' +
          '<input id="wgc-input" maxlength="480" placeholder="Talk to the crew… @Ashley @Voltage" autocomplete="off" />' +
          '<button type="button" class="wgc-send" id="wgc-send">Send</button>' +
          '</div>'
        : '<div class="wgc-login">Log in to type in world chat<br/><a href="/login?next=' +
          encodeURIComponent(global.location && global.location.pathname || '/motion-lab/agent-field.html') +
          '">Sign in →</a></div>') +
      '<div class="wgc-err" id="wgc-err"></div>' +
      '</div></div>';

    var lastId = 0;
    var feed = root.querySelector('#wgc-feed');
    var empty = root.querySelector('#wgc-empty');
    var errEl = root.querySelector('#wgc-err');
    var collapsed = false;

    function setErr(msg) {
      if (errEl) errEl.textContent = msg || '';
    }

    function renderMsgs(msgs) {
      if (!msgs || !msgs.length) return;
      var atBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 48;
      msgs.forEach(function (m) {
        if (!m || !m.body) return;
        if (m.id != null) {
          if (m.id <= lastId) return;
          lastId = m.id;
        }
        if (empty) {
          empty.remove();
          empty = null;
        }
        var div = document.createElement('div');
        var uname = String(m.username || 'anon');
        var isMine = me && uname.indexOf(me) !== -1;
        var crewNames = {
          Voltage:1, Ashley:1, Vanessa:1, Sal:1, Mira:1, Rook:1, Vex:1, Moss:1, Knox:1,
          FrontStreet:1, Photos:1, Arena:1, BuildCrew:1, Ops:1, CodeMaster:1
        };
        var isAgent = !isMine && !!(crewNames[uname] || crewNames[uname.split('·')[0].trim()]);
        div.className = 'wgc-msg' + (isMine ? ' mine' : '') + (isAgent ? ' agent' : '');
        div.innerHTML =
          '<div class="wgc-meta">' + esc(uname) + (isAgent ? ' · agent' : '') + '</div>' +
          '<div class="wgc-bubble">' + esc(m.body || '') + '</div>';
        feed.appendChild(div);
      });
      if (atBottom) feed.scrollTop = feed.scrollHeight;
    }

    var pollUrl = '/api/3d/world-chat/messages';
    var sendUrl = '/api/3d/world-chat/send';

    async function poll() {
      try {
        var res = await fetch(
          pollUrl + '?after=' + lastId,
          { credentials: 'same-origin', headers: { Accept: 'application/json' } }
        );
        if (res.status === 404) {
          pollUrl = '/studios/chatroom/messages';
          res = await fetch(
            pollUrl + '?room=' + encodeURIComponent(room) + '&after=' + lastId,
            { credentials: 'same-origin', headers: { Accept: 'application/json' } }
          );
        }
        var msgs = await res.json();
        if (Array.isArray(msgs)) renderMsgs(msgs);
      } catch (_e) { /* ignore */ }
    }

    async function send() {
      if (!loggedIn) {
        var next = (global.location && (global.location.pathname + global.location.search)) || '/motion-lab/agent-field.html';
        if (global.openAuthModal) global.openAuthModal('login');
        else setErr('Log in to send');
        try {
          global.location.href = '/login?next=' + encodeURIComponent(next);
        } catch (_e) { /* ignore */ }
        return;
      }
      var input = root.querySelector('#wgc-input');
      var btn = root.querySelector('#wgc-send');
      var asSel = root.querySelector('#wgc-as');
      var body = (input && input.value || '').trim();
      if (!body) return;
      if (input) input.value = '';
      if (btn) btn.disabled = true;
      setErr('');
      try {
        var fd = new FormData();
        fd.append('body', body);
        fd.append('room', room);
        if (asSel && asSel.value) fd.append('as_body', asSel.value);
        var res = await fetch(sendUrl, {
          method: 'POST',
          body: fd,
          credentials: 'same-origin',
        });
        if (res.status === 404) {
          sendUrl = '/studios/chatroom/send';
          res = await fetch(sendUrl, {
            method: 'POST',
            body: fd,
            credentials: 'same-origin',
          });
        }
        var m = await res.json().catch(function () { return {}; });
        if (!res.ok) {
          if (res.status === 401 || m.login_required) {
            loggedIn = false;
            setErr('Session expired — log in again');
            var next2 = (global.location && global.location.pathname) || '/motion-lab/agent-field.html';
            global.location.href = '/login?next=' + encodeURIComponent(next2);
            return;
          }
          setErr(m.error || ('Send failed (' + res.status + ')'));
          return;
        }
        if (m.body || m.username) {
          renderMsgs([m]);
        }
        if (m.agent_replies && m.agent_replies.length) {
          renderMsgs(m.agent_replies);
          m.agent_replies.forEach(function (ar) {
            try {
              var detail = {
                seat: ar.seat || '',
                label: ar.label || ar.username || '',
                body: ar.body || '',
                actions: ar.actions || [],
              };
              global.dispatchEvent(new CustomEvent('percfect-agent-body', { detail: detail }));
              if (global.__AGENT_FIELD__ && typeof global.__AGENT_FIELD__.drive === 'function') {
                global.__AGENT_FIELD__.drive(detail.seat || detail.label, detail.actions, detail);
              }
            } catch (_e) { /* ignore */ }
          });
        } else if (m.agents_replied && !m.agents_replied.length) {
          setErr('Crew silent — check chat keys (Vanessa/Sal/Ashley…)');
          setTimeout(function () { setErr(''); }, 4000);
        }
        setTimeout(poll, 600);
        setTimeout(poll, 2000);
      } catch (e) {
        setErr('Network error');
      } finally {
        if (btn) btn.disabled = false;
        if (input) input.focus();
      }
    }

    function toggle() {
      collapsed = !collapsed;
      root.classList.toggle('wgc-collapsed', collapsed);
      var t = root.querySelector('#wgc-toggle');
      if (t) t.textContent = collapsed ? '▸' : '▾';
      var head = root.querySelector('#wgc-head');
      if (head) head.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    }

    var head = root.querySelector('#wgc-head');
    if (head) {
      head.addEventListener('click', function (ev) {
        if (ev.target && ev.target.closest && ev.target.closest('.wgc-compose, input, select, button.wgc-send')) return;
        if (ev.target && (ev.target.id === 'wgc-input' || ev.target.id === 'wgc-send' || ev.target.id === 'wgc-as')) return;
        toggle();
      });
    }
    var sendBtn = root.querySelector('#wgc-send');
    if (sendBtn) sendBtn.addEventListener('click', function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      send();
    });
    var input = root.querySelector('#wgc-input');
    if (input) {
      input.addEventListener('click', function (ev) { ev.stopPropagation(); });
      input.addEventListener('pointerdown', function (ev) { ev.stopPropagation(); });
      input.addEventListener('keydown', function (ev) {
        ev.stopPropagation();
        if (ev.key === 'Enter') {
          ev.preventDefault();
          send();
        }
      });
      input.addEventListener('keyup', function (ev) { ev.stopPropagation(); });
    }
    var asSel = root.querySelector('#wgc-as');
    if (asSel) {
      asSel.addEventListener('click', function (ev) { ev.stopPropagation(); });
      asSel.addEventListener('pointerdown', function (ev) { ev.stopPropagation(); });
    }
    var compose = root.querySelector('.wgc-compose');
    if (compose) {
      compose.addEventListener('pointerdown', function (ev) { ev.stopPropagation(); });
      compose.addEventListener('click', function (ev) { ev.stopPropagation(); });
    }

    poll();
    var timer = setInterval(poll, pollMs);

    return {
      destroy: function () {
        clearInterval(timer);
      },
      poll: poll,
      setSeats: function (list) {
        seats = list || seats;
      },
    };
  }

  function autoMount() {
    var el = document.querySelector('[data-world-chat], #wgc-root');
    if (!el && !document.body) return;
    var seatsAttr = el && el.getAttribute('data-seats');
    var seats = seatsAttr ? seatsAttr.split(',').map(function (s) { return s.trim(); }).filter(Boolean) : null;
    var room = (el && el.getAttribute('data-room')) || '3d';
    var logged = el && el.getAttribute('data-logged-in');
    var user = el && el.getAttribute('data-username');
    mount({
      el: el || undefined,
      room: room,
      seats: seats || undefined,
      loggedIn: logged === '1' || logged === 'true',
      username: user || '',
      title: (el && el.getAttribute('data-title')) || undefined,
      subtitle: (el && el.getAttribute('data-subtitle')) || undefined,
    });
  }

  global.PercfectWorldChat = { mount: mount, autoMount: autoMount, DEFAULT_SEATS: DEFAULT_SEATS };

  // Load OS .glb Finder-drop helper (upload → dock on /3d · Colosseum · Field)
  if (!global.__PERCFECT_STAGE_GLB_DROP__ && !document.querySelector('script[src*="stage_glb_file_drop"]')) {
    try {
      var glbDrop = document.createElement('script');
      glbDrop.src = '/static/js/stage_glb_file_drop.js?v=1';
      glbDrop.async = true;
      (document.head || document.documentElement).appendChild(glbDrop);
    } catch (_e) { /* ignore */ }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      if (document.querySelector('[data-world-chat-auto]')) autoMount();
    });
  } else if (document.querySelector('[data-world-chat-auto]')) {
    autoMount();
  }
})(typeof window !== 'undefined' ? window : this);
