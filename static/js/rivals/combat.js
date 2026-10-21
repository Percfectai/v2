/**
 * ETERNAL RIVALS — basic combat state.
 * Hits land when an attack window overlaps an opponent within range.
 * Triggers hit_react / ko through the same CharacterController command API.
 */

export class CombatSystem {
  /**
   * @param {object} opts
   * @param {object} opts.config combat section of rivals_config
   * @param {function} [opts.onEvent] ({type, ...}) UI / log hook
   */
  constructor({ config = {}, onEvent = null } = {}) {
    this.config = config;
    this.onEvent = typeof onEvent === 'function' ? onEvent : () => {};
    /** @type {Map<string, import('./character_controller.js').CharacterController>} */
    this.fighters = new Map();
  }

  register(controller) {
    if (!controller?.id) return;
    this.fighters.set(controller.id, controller);
  }

  unregister(id) {
    this.fighters.delete(id);
  }

  resetHealth() {
    for (const c of this.fighters.values()) {
      c.alive = true;
      c.health = c.maxHealth;
      c.busyUntil = 0;
      c.command('idle');
    }
  }

  /**
   * Call every frame after controllers.update().
   */
  update() {
    const list = [...this.fighters.values()];
    for (const attacker of list) {
      const window = attacker.consumeAttackWindow();
      if (!window) continue;

      for (const defender of list) {
        if (defender.id === attacker.id) continue;
        if (!defender.alive) continue;
        if (defender.isInvulnerable) {
          this.onEvent({
            type: 'whiff',
            attacker: attacker.id,
            defender: defender.id,
            reason: 'invulnerable',
          });
          continue;
        }

        const ap = attacker.getPosition();
        const dp = defender.getPosition();
        const dist = Math.hypot(ap.x - dp.x, ap.z - dp.z);
        if (dist > window.range) {
          this.onEvent({
            type: 'whiff',
            attacker: attacker.id,
            defender: defender.id,
            reason: 'range',
            dist,
            range: window.range,
          });
          continue;
        }

        // Prefer hits in front of attacker
        const toDx = dp.x - ap.x;
        const toDz = dp.z - ap.z;
        const facing = attacker.getFacing();
        const fwdX = Math.sin(facing);
        const fwdZ = Math.cos(facing);
        const len = Math.hypot(toDx, toDz) || 1;
        const dot = (toDx / len) * fwdX + (toDz / len) * fwdZ;
        if (dot < 0.15 && dist > 0.55) {
          this.onEvent({
            type: 'whiff',
            attacker: attacker.id,
            defender: defender.id,
            reason: 'behind',
            dot,
          });
          continue;
        }

        let dmg = window.damage;
        let blocked = false;
        if (defender.blocking) {
          const mult = Number(this.config.block_damage_mult ?? 0.25);
          dmg = Math.max(1, Math.round(dmg * mult));
          blocked = true;
        }

        const newHp = Math.max(0, defender.health - dmg);
        defender.health = newHp;

        const knockDir = {
          dx: toDx / len,
          dz: toDz / len,
        };

        if (newHp <= Number(this.config.ko_threshold ?? 0)) {
          defender.command('ko');
          this.onEvent({
            type: 'ko',
            attacker: attacker.id,
            defender: defender.id,
            damage: dmg,
            kind: window.kind,
            health: 0,
          });
        } else {
          defender.command('hit_react', {
            dx: knockDir.dx,
            dz: knockDir.dz,
            knockback: blocked ? 0.2 : 0.5,
          });
          this.onEvent({
            type: blocked ? 'block' : 'hit',
            attacker: attacker.id,
            defender: defender.id,
            damage: dmg,
            kind: window.kind,
            health: newHp,
            blocked,
          });
        }
      }
    }
  }

  snapshot() {
    const out = {};
    for (const [id, c] of this.fighters) {
      out[id] = {
        health: c.health,
        maxHealth: c.maxHealth,
        alive: c.alive,
        state: c.state,
      };
    }
    return out;
  }
}

export default CombatSystem;
