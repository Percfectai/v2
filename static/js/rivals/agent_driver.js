/**
 * ETERNAL RIVALS — Driver B: agent takeover.
 * Polls admin-only Flask endpoints and drives characters through the SAME
 * CharacterController.command() interface as the user driver.
 * No WebSocket (app has none for Studio); lightweight HTTP poll only.
 */

const DEFAULT_POLL_MS = 250;

export class AgentDriver {
  /**
   * @param {object} opts
   * @param {Map<string, import('./character_controller.js').CharacterController>|object} opts.controllers
   * @param {number} [opts.pollMs]
   * @param {string} [opts.commandsUrl]
   * @param {function} [opts.onCommand]
   * @param {function} [opts.onError]
   */
  constructor({
    controllers,
    pollMs = DEFAULT_POLL_MS,
    commandsUrl = '/studios/3d/agent/commands',
    onCommand = null,
    onError = null,
  } = {}) {
    this.controllers =
      controllers instanceof Map ? controllers : new Map(Object.entries(controllers || {}));
    this.pollMs = pollMs;
    this.commandsUrl = commandsUrl;
    this.onCommand = onCommand;
    this.onError = onError;
    this.enabled = false;
    this._timer = null;
    this._since = 0;
    this._inflight = false;
  }

  setControllers(map) {
    this.controllers = map instanceof Map ? map : new Map(Object.entries(map || {}));
  }

  setEnabled(on) {
    this.enabled = !!on;
    if (this.enabled) this.start();
    else this.stop();
  }

  start() {
    if (this._timer) return;
    this._timer = setInterval(() => this.poll(), this.pollMs);
    this.poll();
  }

  stop() {
    if (this._timer) {
      clearInterval(this._timer);
      this._timer = null;
    }
    this._inflight = false;
  }

  async poll() {
    if (!this.enabled || this._inflight) return;
    this._inflight = true;
    try {
      const url = `${this.commandsUrl}?since=${this._since}&consume=1`;
      const res = await fetch(url, {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
      });
      if (res.status === 401 || res.status === 403) {
        this.onError?.({ status: res.status, error: 'auth' });
        return;
      }
      if (!res.ok) {
        this.onError?.({ status: res.status, error: 'poll_failed' });
        return;
      }
      const data = await res.json();
      const cmds = data.commands || data.queue || [];
      if (data.since != null) this._since = data.since;
      for (const cmd of cmds) {
        this._apply(cmd);
        if (cmd.id != null && cmd.id > this._since) this._since = cmd.id;
      }
    } catch (e) {
      this.onError?.({ error: String(e.message || e) });
    } finally {
      this._inflight = false;
    }
  }

  _apply(cmd) {
    if (!cmd) return;
    // Never fall back to cmd.id (that is the queue sequence number from Flask).
    const characterId = cmd.character_id || cmd.characterId || 'player';
    const action = cmd.action || cmd.op || cmd.command;
    const params = cmd.params || cmd.args || {};
    const controller = this.controllers.get(characterId);
    if (!controller) {
      this.onError?.({ error: 'unknown_character', character_id: characterId });
      return;
    }
    const result = controller.command(action, params);
    this.onCommand?.({ character_id: characterId, action, params, result, raw: cmd });
  }

  /**
   * Optional helper: POST a command (for debug panel / agent tools).
   */
  async enqueue(characterId, action, params = {}) {
    const res = await fetch('/studios/3d/agent/command', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({
        character_id: characterId,
        action,
        params,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || res.statusText);
    return data;
  }

  dispose() {
    this.stop();
  }
}

export default AgentDriver;
