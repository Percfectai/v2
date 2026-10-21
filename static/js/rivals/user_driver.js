/**
 * ETERNAL RIVALS — Driver A (default): keyboard + on-screen touch buttons.
 * Feeds the shared CharacterController.command() interface.
 */
export class UserDriver {
  /**
   * @param {object} opts
   * @param {import('./character_controller.js').CharacterController} opts.controller
   * @param {THREE.Camera} [opts.camera]
   * @param {object} [opts.keyMap]
   * @param {HTMLElement} [opts.rootEl] scope for touch buttons (data-rivals-action)
   */
  constructor({ controller, camera = null, keyMap = null, rootEl = document } = {}) {
    this.controller = controller;
    this.camera = camera;
    this.enabled = true;
    this.keysDown = Object.create(null);
    this.joy = { x: 0, z: 0 }; // x right, z forward
    this._blockHeld = false;

    this.keyMap = keyMap || {
      move: ['w', 'a', 's', 'd', 'arrowup', 'arrowdown', 'arrowleft', 'arrowright'],
      attack_light: ['j'],
      attack_heavy: ['k'],
      block: ['l'],
      dodge: [' ', 'space', 'i'],
      jump: ['shift', 'shiftleft', 'shiftright'],
    };

    this._onKeyDown = (e) => this._key(e, true);
    this._onKeyUp = (e) => this._key(e, false);
    this._onBlur = () => {
      for (const k of Object.keys(this.keysDown)) this.keysDown[k] = false;
      this.joy.x = 0;
      this.joy.z = 0;
      if (this._blockHeld) {
        this._blockHeld = false;
        this.controller?.command('block', { on: false });
      }
    };

    window.addEventListener('keydown', this._onKeyDown);
    window.addEventListener('keyup', this._onKeyUp);
    window.addEventListener('blur', this._onBlur);

    this._bindTouch(rootEl);
  }

  setController(controller) {
    this.controller = controller;
  }

  setCamera(camera) {
    this.camera = camera;
  }

  setEnabled(on) {
    this.enabled = !!on;
    if (!this.enabled) {
      this.controller?.command('idle');
      this.joy.x = 0;
      this.joy.z = 0;
      for (const k of Object.keys(this.keysDown)) this.keysDown[k] = false;
    }
  }

  _key(e, down) {
    if (!this.enabled || !this.controller) return;
    const tag = (e.target && e.target.tagName) || '';
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

    const k = e.key.length === 1 ? e.key.toLowerCase() : e.key.toLowerCase();
    const code = (e.code || '').toLowerCase();

    if (this.keyMap.move.includes(k) || this.keyMap.move.includes(code)) {
      this.keysDown[k] = down;
      if (k.startsWith('arrow') || code.startsWith('arrow')) e.preventDefault();
      return;
    }

    if (!down) {
      if (this.keyMap.block.includes(k) || this.keyMap.block.includes(code)) {
        this._blockHeld = false;
        this.controller.command('block', { on: false });
      }
      return;
    }

    if (this.keyMap.attack_light.includes(k) || this.keyMap.attack_light.includes(code)) {
      e.preventDefault();
      this.controller.command('attack_light');
      return;
    }
    if (this.keyMap.attack_heavy.includes(k) || this.keyMap.attack_heavy.includes(code)) {
      e.preventDefault();
      this.controller.command('attack_heavy');
      return;
    }
    if (this.keyMap.block.includes(k) || this.keyMap.block.includes(code)) {
      e.preventDefault();
      this._blockHeld = true;
      this.controller.command('block', { on: true });
      return;
    }
    if (this.keyMap.dodge.includes(k) || this.keyMap.dodge.includes(code) || k === ' ') {
      e.preventDefault();
      this.controller.command('dodge');
      return;
    }
    if (this.keyMap.jump.includes(k) || this.keyMap.jump.includes(code)) {
      e.preventDefault();
      this.controller.command('jump');
    }
  }

  _bindTouch(rootEl) {
    const root = rootEl || document;
    const press = (action, params, isDown) => {
      if (!this.enabled || !this.controller) return;
      if (action === 'block') {
        this.controller.command('block', { on: isDown });
        return;
      }
      if (!isDown) return;
      if (action === 'attack_light' || action === 'attack_heavy' || action === 'dodge') {
        this.controller.command(action, params || {});
      }
    };

    root.querySelectorAll('[data-rivals-action]').forEach((btn) => {
      const action = btn.getAttribute('data-rivals-action');
      const hold = btn.getAttribute('data-rivals-hold') === '1';
      const start = (e) => {
        e.preventDefault();
        press(action, {}, true);
      };
      const end = (e) => {
        if (!hold) return;
        e.preventDefault();
        press(action, {}, false);
      };
      btn.addEventListener('pointerdown', start);
      btn.addEventListener('pointerup', end);
      btn.addEventListener('pointerleave', end);
      btn.addEventListener('pointercancel', end);
    });

    // Joystick base (optional)
    const base = root.querySelector('#rivals-joystick-base');
    const stick = root.querySelector('#rivals-joystick-stick');
    if (!base || !stick) return;
    const maxR = 36;
    let pid = null;

    const setStick = (dx, dy) => {
      const len = Math.hypot(dx, dy);
      let nx = dx;
      let ny = dy;
      if (len > maxR) {
        nx = (dx / len) * maxR;
        ny = (dy / len) * maxR;
      }
      stick.style.transform = `translate(calc(-50% + ${nx}px), calc(-50% + ${ny}px))`;
      this.joy.x = nx / maxR;
      this.joy.z = -ny / maxR; // screen up → forward
    };
    const endJoy = () => {
      pid = null;
      this.joy.x = 0;
      this.joy.z = 0;
      stick.style.transform = 'translate(-50%, -50%)';
    };

    base.addEventListener('pointerdown', (e) => {
      if (!this.enabled) return;
      e.preventDefault();
      e.stopPropagation();
      pid = e.pointerId;
      base.setPointerCapture?.(e.pointerId);
      const rect = base.getBoundingClientRect();
      setStick(e.clientX - (rect.left + rect.width / 2), e.clientY - (rect.top + rect.height / 2));
    });
    base.addEventListener('pointermove', (e) => {
      if (pid !== e.pointerId) return;
      e.preventDefault();
      const rect = base.getBoundingClientRect();
      setStick(e.clientX - (rect.left + rect.width / 2), e.clientY - (rect.top + rect.height / 2));
    });
    const end = (e) => {
      if (pid != null && e.pointerId !== pid) return;
      endJoy();
    };
    base.addEventListener('pointerup', end);
    base.addEventListener('pointercancel', end);
    base.addEventListener('lostpointercapture', end);
  }

  /**
   * Push continuous move intent into the controller each frame.
   */
  update() {
    if (!this.enabled || !this.controller) return;

    let ix = 0;
    let iz = 0;
    if (this.keysDown.w || this.keysDown.arrowup) iz += 1;
    if (this.keysDown.s || this.keysDown.arrowdown) iz -= 1;
    if (this.keysDown.a || this.keysDown.arrowleft) ix -= 1;
    if (this.keysDown.d || this.keysDown.arrowright) ix += 1;
    ix += this.joy.x;
    iz += this.joy.z;

    const len = Math.hypot(ix, iz);
    if (len < 0.08) {
      // Only stop if we were the ones moving (don't clobber agent when disabled)
      if (this._wasMoving) {
        this.controller.command('move', { direction: { x: 0, z: 0 } });
        this._wasMoving = false;
      }
      return;
    }
    if (len > 1) {
      ix /= len;
      iz /= len;
    }
    this._wasMoving = true;
    this.controller.command('move', {
      direction: { x: ix, z: iz },
      camera_relative: true,
    });
  }

  dispose() {
    window.removeEventListener('keydown', this._onKeyDown);
    window.removeEventListener('keyup', this._onKeyUp);
    window.removeEventListener('blur', this._onBlur);
  }
}

export default UserDriver;
