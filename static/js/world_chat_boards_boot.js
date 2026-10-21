/**
 * Mount world group chat on Field / Colosseum if not already mounted.
 */
(function () {
  'use strict';
  if (window.__PERCFECT_WGC_BOARDS_BOOT__) return;
  window.__PERCFECT_WGC_BOARDS_BOOT__ = true;

  var FULL_SEATS = [
    'Voltage', 'Ashley', 'Vanessa', 'Sal', 'Mira', 'Rook', 'Vex', 'Moss', 'Knox',
    'FrontStreet', 'Photos', 'Arena', 'BuildCrew', 'Ops', 'CodeMaster',
  ];

  function ensureRoot() {
    var el = document.getElementById('wgc-root');
    if (el) return el;
    el = document.createElement('div');
    el.id = 'wgc-root';
    el.className = 'wgc-root';
    el.setAttribute('data-world-chat', '1');
    el.setAttribute('data-room', '3d');
    document.body.appendChild(el);
    return el;
  }

  function mount(logged, name) {
    if (!window.PercfectWorldChat || typeof window.PercfectWorldChat.mount !== 'function') return;
    var el = ensureRoot();
    if (el.getAttribute('data-wgc-mounted') === '1') return;
    el.setAttribute('data-wgc-mounted', '1');
    var path = (window.location && window.location.pathname) || '';
    var title = /colosseum/i.test(path) ? 'Colosseum chat' : 'Field chat';
    window.PercfectWorldChat.mount({
      el: el,
      room: '3d',
      seats: FULL_SEATS,
      loggedIn: !!logged,
      username: name || '',
      title: title,
      subtitle: 'real agents · they move when they talk',
    });
  }

  function go() {
    fetch('/percfectstudios/session-info', {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var logged = !!(d && (d.logged_in || d.username || d.user_id || d.is_admin));
        var name = (d && (d.username || d.name || d.email)) || '';
        mount(logged, name);
      })
      .catch(function () { mount(false, ''); });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', go);
  } else {
    go();
  }
})();
