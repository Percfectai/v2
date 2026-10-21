/**
 * ETERNAL RIVALS — CharacterController
 * Load any rigged character GLB onto the existing flat-ground 3D stage and
 * expose a single command interface used by BOTH user and agent drivers.
 *
 * Commands: move, turn, idle, attack_light, attack_heavy, block, dodge,
 *           hit_react, ko
 * Clips when present; procedural bone/root motion when missing.
 * Feet stay on the ground plane (floorY).
 */
import * as THREE from 'three';
import {
  clone as skeletonClone,
  retargetClip as skeletonRetargetClip,
} from 'three/addons/utils/SkeletonUtils.js';

/**
 * Fuzzy bone-name map for Mixamo / Meshy / common humanoids.
 * Keys = motion-pack bone (lower), values = needles to match on character.
 */
const BONE_ALIASES = [
  { from: ['hips', 'hip', 'pelvis', 'mixamorighips', 'root'], to: ['hips', 'hip', 'pelvis', 'root'] },
  { from: ['spine', 'mixamorigspine'], to: ['spine'] },
  { from: ['spine1', 'spine_01', 'mixamorigspine1'], to: ['spine1', 'spine_01', 'chest'] },
  { from: ['spine2', 'spine_02', 'mixamorigspine2'], to: ['spine2', 'spine_02'] },
  { from: ['neck', 'mixamorigneck'], to: ['neck'] },
  { from: ['head', 'mixamorighead'], to: ['head'] },
  { from: ['leftupleg', 'left_up_leg', 'upperleg_l', 'thigh_l', 'mixamorigleftupleg'], to: ['leftupleg', 'upperleg_l', 'thigh_l', 'upleg_l'] },
  { from: ['rightupleg', 'right_up_leg', 'upperleg_r', 'thigh_r', 'mixamorigrightupleg'], to: ['rightupleg', 'upperleg_r', 'thigh_r', 'upleg_r'] },
  { from: ['leftleg', 'left_leg', 'lowerleg_l', 'calf_l', 'mixamorigleftleg'], to: ['leftleg', 'lowerleg_l', 'calf_l'] },
  { from: ['rightleg', 'right_leg', 'lowerleg_r', 'calf_r', 'mixamorigrightleg'], to: ['rightleg', 'lowerleg_r', 'calf_r'] },
  { from: ['leftfoot', 'left_foot', 'foot_l', 'mixamorigleftfoot'], to: ['leftfoot', 'foot_l'] },
  { from: ['rightfoot', 'right_foot', 'foot_r', 'mixamorigrightfoot'], to: ['rightfoot', 'foot_r'] },
  { from: ['leftarm', 'left_arm', 'upperarm_l', 'mixamorigleftarm'], to: ['leftarm', 'upperarm_l', 'arm_l'] },
  { from: ['rightarm', 'right_arm', 'upperarm_r', 'mixamorigrightarm'], to: ['rightarm', 'upperarm_r', 'arm_r'] },
  { from: ['leftforearm', 'left_fore_arm', 'lowerarm_l', 'mixamorigleftforearm'], to: ['leftforearm', 'lowerarm_l', 'forearm_l'] },
  { from: ['rightforearm', 'right_fore_arm', 'lowerarm_r', 'mixamorigrightforearm'], to: ['rightforearm', 'lowerarm_r', 'forearm_r'] },
  { from: ['lefthand', 'left_hand', 'hand_l', 'mixamoriglefthand'], to: ['lefthand', 'hand_l'] },
  { from: ['righthand', 'right_hand', 'hand_r', 'mixamorigrighthand'], to: ['righthand', 'hand_r'] },
];

function normBone(n) {
  return String(n || '')
    .toLowerCase()
    .replace(/mixamorig:?/g, '')
    .replace(/[^a-z0-9]/g, '');
}

function buildBoneNameMap(sourceBones, targetBones) {
  const names = {};
  const targetByNorm = new Map();
  for (const b of targetBones) {
    targetByNorm.set(normBone(b.name), b.name);
  }
  for (const sb of sourceBones) {
    const sn = normBone(sb.name);
    // exact normalized match
    if (targetByNorm.has(sn)) {
      names[sb.name] = targetByNorm.get(sn);
      continue;
    }
    // alias table
    let mapped = null;
    for (const row of BONE_ALIASES) {
      if (row.from.some((f) => sn.includes(normBone(f)) || normBone(f).includes(sn))) {
        for (const t of row.to) {
          const tn = normBone(t);
          for (const [k, real] of targetByNorm) {
            if (k.includes(tn) || tn.includes(k)) {
              mapped = real;
              break;
            }
          }
          if (mapped) break;
        }
      }
      if (mapped) break;
    }
    if (mapped) names[sb.name] = mapped;
  }
  return names;
}

function findSkinnedMesh(root) {
  let found = null;
  root.traverse((o) => {
    if (!found && o.isSkinnedMesh && o.skeleton?.bones?.length) found = o;
  });
  return found;
}

const CLIP_NEEDLES = {
  idle: ['idle', 'stand', 'wait', 'rest', 'tpose', 't-pose', 't_pose', 'breath', 'neutral'],
  // Meshy / Mixamo / PoYo often use bare names: "Walking", "Walk_Cycle", "Animation", "Take 001"
  walk: [
    'walk', 'run', 'jog', 'move', 'locomotion', 'cycle', 'stride', 'gait',
    'walking', 'running', 'forward', 'inplace', 'in_place', 'in-place',
  ],
  attack_light: ['attack', 'punch', 'jab', 'hit', 'strike', 'light'],
  attack_heavy: ['heavy', 'smash', 'kick', 'power', 'strong'],
  block: ['block', 'guard', 'defend', 'shield'],
  dodge: ['dodge', 'roll', 'evade', 'sidestep'],
  hit_react: ['hit', 'react', 'hurt', 'damage', 'flinch', 'impact'],
  ko: ['ko', 'death', 'die', 'fall', 'down', 'defeat'],
};

function findClip(clips, needles) {
  if (!clips?.length) return null;
  return (
    clips.find((c) => {
      const n = (c.name || '').toLowerCase();
      return needles.some((k) => n.includes(k));
    }) || null
  );
}

/** Collect bones from SkinnedMesh skeletons first (Meshy), then scene isBone. */
function collectBones(root) {
  const out = [];
  const seen = new Set();
  root.traverse((o) => {
    if (o.isSkinnedMesh && o.skeleton?.bones?.length) {
      for (const b of o.skeleton.bones) {
        if (b && !seen.has(b)) {
          seen.add(b);
          out.push(b);
        }
      }
    }
  });
  root.traverse((o) => {
    if (o.isBone && !seen.has(o)) {
      seen.add(o);
      out.push(o);
    }
  });
  return out;
}

function fitMeshToStage(root, targetH = 1.85) {
  const box = new THREE.Box3().setFromObject(root);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const scale = targetH / Math.max(0.001, size.y);
  root.scale.setScalar(scale);
  // Plant feet on floor — do NOT overwrite y with 0 after this.
  root.position.set(-center.x * scale, -box.min.y * scale, -center.z * scale);
  return root.position.y;
}

function findBone(root, needles) {
  const bones = collectBones(root);
  const needlesN = needles.map((k) => String(k).toLowerCase().replace(/[^a-z0-9]/g, ''));
  for (const b of bones) {
    const n = String(b.name || '')
      .toLowerCase()
      .replace(/mixamorig:?/g, '')
      .replace(/[^a-z0-9]/g, '');
    if (needlesN.some((k) => n.includes(k) || k.includes(n))) return b;
  }
  // Fallback: any Object3D with bone-like name (some exporters skip isBone)
  let found = null;
  root.traverse((o) => {
    if (found || !o.name) return;
    const n = String(o.name)
      .toLowerCase()
      .replace(/mixamorig:?/g, '')
      .replace(/[^a-z0-9]/g, '');
    if (needlesN.some((k) => n.includes(k))) found = o;
  });
  return found;
}

export class CharacterController {
  /**
   * @param {object} opts
   * @param {string} opts.id
   * @param {THREE.Object3D} opts.parent  scene or group to attach into
   * @param {object} [opts.config] movement + combat tuning (from rivals_config)
   * @param {number} [opts.floorY]
   * @param {string} [opts.tint] hex color for outline-ish material boost
   */
  constructor({ id, parent, config = {}, floorY = 0, tint = null } = {}) {
    this.id = id || 'fighter';
    this.parent = parent;
    this.config = config;
    this.floorY = floorY;
    this.tint = tint;

    this.root = null;
    this.mixer = null;
    this.actions = Object.create(null); // name -> AnimationAction
    this.clipsPresent = Object.create(null);
    this.activeAction = null;

    this.state = 'idle'; // idle | walk | attack_light | attack_heavy | block | dodge | hit_react | ko
    this.facing = 0; // yaw radians
    this.moveIntent = { x: 0, z: 0, active: false };
    this.moveTarget = null; // {x,z} world or null
    this.busyUntil = 0; // performance.now() ms
    this.invulnUntil = 0;
    this.blocking = false;
    this.alive = true;

    this.maxHealth = Number(config.combat?.max_health ?? 100);
    this.health = this.maxHealth;

    this.moveSpeed = Number(config.movement?.move_speed ?? 2.8);
    this.turnSpeed = Number(config.movement?.turn_speed ?? 10);
    this.bounds = Number(config.movement?.bounds_radius ?? 6.5);
    this.targetH = Number(config.movement?.target_height_m ?? 1.85);

    this._charFloorY = 0;
    this._spawnOffset = { x: 0, z: 0 };
    this._proceduralT = 0;
    this._rightArm = null;
    this._spine = null;
    this._attackHitWindow = null; // { until, kind, range, damage } while swinging

    this._tmp = {
      camFwd: new THREE.Vector3(),
      camRight: new THREE.Vector3(),
      moveDir: new THREE.Vector3(),
      v: new THREE.Vector3(),
    };
  }

  get isBusy() {
    return !this.alive || performance.now() < this.busyUntil;
  }

  get isInvulnerable() {
    return performance.now() < this.invulnUntil;
  }

  getPosition() {
    if (!this.root) return { x: 0, y: this.floorY, z: 0 };
    return {
      x: this.root.position.x,
      y: this.root.position.y,
      z: this.root.position.z,
    };
  }

  getFacing() {
    return this.facing;
  }

  getState() {
    return {
      id: this.id,
      state: this.state,
      health: this.health,
      maxHealth: this.maxHealth,
      alive: this.alive,
      blocking: this.blocking,
      invulnerable: this.isInvulnerable,
      busy: this.isBusy,
      position: this.getPosition(),
      facing: this.facing,
      clips: { ...this.clipsPresent },
    };
  }

  setHealth(hp) {
    this.health = Math.max(0, Math.min(this.maxHealth, Number(hp) || 0));
    if (this.health <= 0 && this.alive) {
      this.command('ko');
    }
  }

  /**
   * Unified command interface — used by user driver AND agent driver.
   * @param {string} action
   * @param {object} [params]
   */
  command(action, params = {}) {
    const a = String(action || '').toLowerCase().trim();
    if (!a) return { ok: false, error: 'empty action' };

    // 17-set aliases (controller.html / Meshy action names)
    const ALIAS = {
      walk_fwd: 'walk',
      walk: 'walk',
      run: 'run',
      punch: 'attack_light',
      heavy_punch: 'attack_heavy',
      hurt: 'hit_react',
    };
    const mapped = ALIAS[a] || a;

    if (mapped === 'move') return this._cmdMove(params);
    if (mapped === 'turn') return this._cmdTurn(params);
    if (mapped === 'idle') return this._cmdIdle(params);
    if (mapped === 'attack_light' || mapped === 'attack_heavy') return this._cmdAttack(mapped, params);
    if (mapped === 'block') return this._cmdBlock(params);
    if (mapped === 'dodge') return this._cmdDodge(params);
    if (mapped === 'jump') return this._cmdJump(params);
    if (mapped === 'hit_react') return this._cmdHitReact(params);
    if (mapped === 'ko') return this._cmdKo(params);
    if (mapped === 'set_health') {
      this.setHealth(params.health ?? params.hp);
      return { ok: true, action: a, health: this.health };
    }
    // Play any registered set clip (kick, roundhouse, cast, taunt, walk_back, strafe_*, run, …)
    if (this.actions[a] || this.actions[mapped]) {
      return this.playSetAction(a);
    }
    return { ok: false, error: `unknown action: ${a}` };
  }

  /**
   * Play a named animation-set clip (keypress). Prefer exact name, then aliases.
   */
  playSetAction(name, opts = {}) {
    const n = String(name || '').toLowerCase();
    const tryNames = [
      n,
      n === 'walk' ? 'walk_fwd' : null,
      n === 'walk_fwd' ? 'walk' : null,
      n === 'punch' ? 'attack_light' : null,
      n === 'attack_light' ? 'punch' : null,
      n === 'heavy_punch' ? 'attack_heavy' : null,
      n === 'hurt' ? 'hit_react' : null,
      n === 'hit_react' ? 'hurt' : null,
    ].filter(Boolean);
    let key = null;
    for (const t of tryNames) {
      if (this.actions[t]) {
        key = t;
        break;
      }
    }
    if (!key) return { ok: false, error: `no clip: ${name}` };

    const oneshot = /jump|punch|heavy|kick|roundhouse|dodge|cast|taunt|hurt|ko|attack/.test(key);
    this.moveIntent = { x: 0, z: 0, active: false };
    this.moveTarget = null;
    this.blocking = key === 'block';
    this.state = key === 'walk' || key === 'walk_fwd' || key === 'run' ? 'walk' : key;
    if (oneshot) {
      this.busyUntil = performance.now() + Number(opts.duration_ms || 600);
    }
    const played = this._playClip(key, 0.12, { loop: !oneshot, restart: true });
    // Prefer walk_fwd clip when state walk
    if ((key === 'walk' || key === 'walk_fwd') && this.actions.walk_fwd) {
      this._playClip('walk_fwd', 0.12, { loop: true, restart: false });
    }
    if (key === 'run' && this.actions.run) {
      this._playClip('run', 0.12, { loop: true, restart: false });
    }
    return { ok: true, action: key, clip: played };
  }

  /**
   * Fetch a GLB once (or reuse a preloaded gltf) and attach a skinned clone.
   * Shared templates: call loadAsync once, then attachGltf(gltf, spawn) per agent
   * so the Field can show 15 bodies without re-downloading a 10MB mesh 15 times.
   */
  async load(url, GLTFLoader, spawn = { x: 0, z: 0 }) {
    if (!url || !GLTFLoader) throw new Error('load requires url + GLTFLoader');
    const loader = new GLTFLoader();
    const gltf = await loader.loadAsync(url);
    return this.attachGltf(gltf, spawn);
  }

  /**
   * Attach a clone of a preloaded glTF (SkeletonUtils-safe for skinned Meshy rigs).
   * @param {object} gltf result of GLTFLoader.loadAsync
   * @param {{x?:number,z?:number}} [spawn]
   */
  attachGltf(gltf, spawn = { x: 0, z: 0 }) {
    if (!gltf?.scene) throw new Error('attachGltf requires gltf.scene');
    this.disposeMeshOnly();

    // Always clone — original stays in cache for other seats
    let root;
    try {
      root = skeletonClone(gltf.scene);
    } catch (_) {
      root = gltf.scene.clone(true);
    }

    root.traverse((o) => {
      if (o.isMesh) {
        o.castShadow = true;
        o.receiveShadow = true;
        // Clone materials so per-agent tint does not leak across seats
        if (o.material) {
          try {
            if (Array.isArray(o.material)) {
              o.material = o.material.map((m) => (m && m.clone ? m.clone() : m));
            } else if (o.material.clone) {
              o.material = o.material.clone();
            }
          } catch (_) { /* ignore */ }
        }
        if (this.tint && o.material) {
          try {
            const mats = Array.isArray(o.material) ? o.material : [o.material];
            const tintCol = new THREE.Color(this.tint);
            for (const m of mats) {
              if (!m) continue;
              if (m.color) m.color.lerp(tintCol, 0.35);
              if (m.emissive) {
                m.emissive.copy(tintCol);
                m.emissiveIntensity = 0.45;
              }
            }
          } catch (_) { /* ignore */ }
        }
      }
    });

    this._charFloorY = fitMeshToStage(root, this.targetH);
    this._spawnOffset = { x: spawn.x || 0, z: spawn.z || 0 };
    root.position.x = this._spawnOffset.x;
    root.position.z = this._spawnOffset.z;
    root.position.y = this._charFloorY;
    this.floorY = this._charFloorY;

    this.root = root;
    this.parent.add(root);

    this._rightArm = findBone(root, ['rightarm', 'right_arm', 'arm_r', 'r_arm', 'hand_r', 'righthand', 'upperarm_r', 'upperarmr']);
    this._leftArm = findBone(root, ['upperarm_l', 'leftarm', 'left_arm', 'arm_l', 'l_arm', 'upperarml']);
    this._spine = findBone(root, ['spine', 'chest', 'torso', 'hips', 'pelvis']);
    // Leg bones — Meshy / Mixamo / generic humanoid aliases
    this._legs = {
      upperL: findBone(root, ['upperleg_l', 'leftupleg', 'upleg_l', 'thigh_l', 'l_thigh', 'leg_l', 'leftleg', 'hip_l']),
      upperR: findBone(root, ['upperleg_r', 'rightupleg', 'upleg_r', 'thigh_r', 'r_thigh', 'leg_r', 'rightleg', 'hip_r']),
      lowerL: findBone(root, ['lowerleg_l', 'leftleg', 'calf_l', 'shin_l', 'l_calf', 'leftlowerleg']),
      lowerR: findBone(root, ['lowerleg_r', 'rightleg', 'calf_r', 'shin_r', 'r_calf', 'rightlowerleg']),
      footL: findBone(root, ['foot_l', 'leftfoot', 'l_foot', 'ankle_l']),
      footR: findBone(root, ['foot_r', 'rightfoot', 'r_foot', 'ankle_r']),
    };
    this._hasLegRig = !!(this._legs.upperL || this._legs.upperR);

    this._setupClips(gltf, root);
    // Debug: why slide? clip names + leg bind
    try {
      const names = (gltf.animations || []).map((c) => c.name || '(unnamed)');
      console.info(
        `[CharacterController ${this.id}] clips=${names.length} [${names.slice(0, 8).join(', ')}]` +
          ` walk=${!!this.actions.walk} idle=${!!this.actions.idle} legs=${this._hasLegRig}`,
      );
    } catch (_) { /* ignore */ }
    this.facing = root.rotation.y;
    this.state = 'idle';
    this.alive = true;
    this.health = this.maxHealth;
    this._playClip('idle', 0.15);
    return this;
  }

  /**
   * Attach walk/idle (etc.) from a *motion* GLB onto this character.
   *
   * HOW THIS WORKS (Nick):
   * 1. Character GLB = skinned mesh + its own skeleton (bones).
   * 2. Motion GLB = often a "skeleton walking" with AnimationClips on those bones.
   * 3. We map bone names (Mixamo ↔ Meshy) and either:
   *    a) retargetClip onto this character's skeleton, or
   *    b) if names already match, bind the clip tracks directly.
   * 4. CharacterController then plays "walk" when moving — real animation, not just root slide.
   *
   * @param {object} motionGltf GLTFLoader result (must have .animations)
   * @param {object} [opts]
   * @returns {{ ok: boolean, attached: string[], method: string, error?: string }}
   */
  attachMotionGltf(motionGltf, opts = {}) {
    if (!this.root) return { ok: false, attached: [], method: 'none', error: 'no character loaded' };
    const clips = motionGltf?.animations || [];
    if (!clips.length) {
      return { ok: false, attached: [], method: 'none', error: 'motion GLB has no animations' };
    }

    const targetMesh = findSkinnedMesh(this.root);
    if (!targetMesh) {
      // Still try direct clip bind (some rigs put tracks on root bones)
      return this._bindClipsDirect(clips, 'direct-no-skin');
    }

    const sourceRoot = motionGltf.scene;
    const sourceMesh = findSkinnedMesh(sourceRoot);
    if (!sourceMesh) {
      return this._bindClipsDirect(clips, 'direct-no-source-skin');
    }

    // Build name map: motion bone name → character bone name
    const names = buildBoneNameMap(sourceMesh.skeleton.bones, targetMesh.skeleton.bones);
    const mapped = Object.keys(names).length;
    if (mapped < 4) {
      // Not enough bones mapped — try direct bind (same rig family)
      const direct = this._bindClipsDirect(clips, 'direct-low-map');
      if (direct.attached.length) return direct;
      return {
        ok: false,
        attached: [],
        method: 'retarget-failed',
        error: `Only ${mapped} bones mapped — rigs may not match. Export both as Mixamo/Humanoid.`,
        mapSample: names,
      };
    }

    const attached = [];
    if (!this.mixer) this.mixer = new THREE.AnimationMixer(this.root);
    this.clipsPresent = this.clipsPresent || {};

    for (const srcClip of clips) {
      let converted = null;
      try {
        converted = skeletonRetargetClip(targetMesh, sourceMesh, srcClip, {
          names,
          hip: names[sourceMesh.skeleton.bones.find((b) => /hip|pelvis/i.test(b.name))?.name]
            || names[Object.keys(names)[0]]
            || 'Hips',
          useFirstFramePosition: true,
          fps: 30,
        });
      } catch (e) {
        console.warn('[CharacterController] retargetClip failed', srcClip.name, e);
        continue;
      }
      if (!converted || !converted.tracks?.length) continue;

      // Classify into walk/idle/etc.
      const key = this._classifyClipName(srcClip.name || converted.name || '');
      const action = this.mixer.clipAction(converted);
      action.enabled = true;
      action.setEffectiveWeight(0);
      action.play();
      // Prefer motion-pack walk over empty procedural
      if (!this.actions[key] || key === 'walk' || key === 'idle') {
        this.actions[key] = action;
        this.clipsPresent[key] = true;
        attached.push(key + ':' + (srcClip.name || 'clip'));
      }
    }

    // If still no walk, first converted clip becomes walk
    if (!this.actions.walk && attached.length) {
      // leave as classified
    }
    if (!this.actions.idle && this.actions.walk) {
      // hold walk at weight 0 as idle fallback is fine
    }

    this._playClip('idle', 0.1);
    return {
      ok: attached.length > 0,
      attached,
      method: 'retargetClip',
      bonesMapped: mapped,
    };
  }

  /**
   * Load a motion pack GLB (skeleton walk) and attach onto this character.
   */
  async attachMotionUrl(url, GLTFLoader) {
    if (!url || !GLTFLoader) throw new Error('attachMotionUrl needs url + GLTFLoader');
    const loader = new GLTFLoader();
    const gltf = await loader.loadAsync(url);
    return this.attachMotionGltf(gltf);
  }

  /**
   * Full 17-clip animation set (see HANDOFFS/GROK_ANIMATION_SET_INTEGRATION.md +
   * static/motion-lab/controller.html). Each value is a URL to a Meshy action GLB;
   * we take animations[0] and register it on this character's mixer (same skeleton).
   *
   * @param {Record<string,string>} setMap  e.g. { idle, walk_fwd, run, punch, ... }
   * @param {typeof GLTFLoader} GLTFLoader
   * @param {{ baseUrl?: string, spawn?: {x?:number,z?:number} }} [opts]
   * @returns {Promise<{ok:boolean, clips:string[], errors:string[]}>
   */
  async attachAnimationSet(setMap, GLTFLoader, opts = {}) {
    if (!setMap || typeof setMap !== 'object') {
      return { ok: false, clips: [], errors: ['no setMap'] };
    }
    if (!GLTFLoader) throw new Error('attachAnimationSet needs GLTFLoader');
    const loader = new GLTFLoader();
    const base = (opts.baseUrl || '').replace(/\/?$/, '/');
    const resolve = (u) => {
      if (!u) return '';
      if (/^https?:\/\//i.test(u) || u.startsWith('/')) return u;
      return base + u;
    };

    // Map set keys → CharacterController action keys (and keep original names)
    const ALIAS = {
      idle: ['idle'],
      walk_fwd: ['walk', 'walk_fwd'],
      walk_back: ['walk_back'],
      strafe_left: ['strafe_left'],
      strafe_right: ['strafe_right'],
      run: ['run', 'walk'], // run also usable as walk if needed
      jump: ['jump'],
      punch: ['attack_light', 'punch'],
      heavy_punch: ['attack_heavy', 'heavy_punch'],
      kick: ['kick'],
      roundhouse: ['roundhouse'],
      block: ['block'],
      dodge: ['dodge'],
      cast: ['cast'],
      taunt: ['taunt'],
      hurt: ['hit_react', 'hurt'],
      ko: ['ko'],
    };

    const errors = [];
    // Base mesh from idle (or first available) if not already attached
    if (!this.root) {
      const idleUrl =
        resolve(setMap.idle) ||
        resolve(Object.values(setMap).find(Boolean));
      if (!idleUrl) return { ok: false, clips: [], errors: ['no idle url'] };
      try {
        const baseGltf = await loader.loadAsync(idleUrl);
        this.attachGltf(baseGltf, opts.spawn || { x: 0, z: 0 });
      } catch (e) {
        return { ok: false, clips: [], errors: [`idle load: ${e.message || e}`] };
      }
    }
    if (!this.mixer) this.mixer = new THREE.AnimationMixer(this.root);
    this.actions = this.actions || Object.create(null);
    this.clipsPresent = this.clipsPresent || Object.create(null);

    const makeAction = (clip, loopOnce = false) => {
      const action = this.mixer.clipAction(clip, this.root);
      action.enabled = true;
      action.setEffectiveWeight(0);
      if (loopOnce) {
        action.setLoop(THREE.LoopOnce, 1);
        action.clampWhenFinished = true;
      } else {
        action.setLoop(THREE.LoopRepeat, Infinity);
      }
      action.play();
      return action;
    };

    const oneshot = new Set([
      'jump', 'punch', 'heavy_punch', 'kick', 'roundhouse', 'dodge', 'cast', 'taunt', 'hurt', 'ko',
      'attack_light', 'attack_heavy', 'hit_react',
    ]);

    await Promise.all(
      Object.entries(setMap).map(async ([name, rawUrl]) => {
        const url = resolve(rawUrl);
        if (!url) return;
        try {
          const g = await loader.loadAsync(url);
          const clip = (g.animations && g.animations[0]) || null;
          if (!clip) {
            errors.push(`${name}: no animations[0]`);
            return;
          }
          // Unique clip name so mixer doesn't collide
          try {
            clip.name = clip.name || name;
          } catch (_) { /* ignore */ }
          const keys = ALIAS[name] || [name];
          const isOnce = keys.some((k) => oneshot.has(k));
          const action = makeAction(clip, isOnce);
          for (const k of keys) {
            this.actions[k] = action;
            this.clipsPresent[k] = true;
          }
          // Always keep original set name too
          this.actions[name] = action;
          this.clipsPresent[name] = true;
        } catch (e) {
          errors.push(`${name}: ${e.message || e}`);
          console.warn('[CharacterController] animation_set fail', name, e);
        }
      }),
    );

    // Prefer real walk_fwd over any earlier placeholder walk
    if (this.actions.walk_fwd && !this.actions.walk) {
      this.actions.walk = this.actions.walk_fwd;
      this.clipsPresent.walk = true;
    }
    this._playClip('idle', 0.12);
    const clips = Object.keys(this.actions);
    console.info(
      `[CharacterController ${this.id}] animation_set loaded: ${clips.join(', ')}` +
        (errors.length ? ` errors=${errors.length}` : ''),
    );
    return { ok: clips.length > 0, clips, errors };
  }

  _classifyClipName(name) {
    const n = String(name || '').toLowerCase();
    for (const [key, needles] of Object.entries(CLIP_NEEDLES)) {
      if (needles.some((k) => n.includes(k))) return key;
    }
    if (/run|jog|locomotion|cycle/.test(n)) return 'walk';
    if (/stand|rest|tpose|t-pose/.test(n)) return 'idle';
    // default first unknown → walk if missing, else idle
    if (!this.actions?.walk) return 'walk';
    return 'idle';
  }

  _bindClipsDirect(clips, method) {
    if (!this.root) return { ok: false, attached: [], method, error: 'no root' };
    if (!this.mixer) this.mixer = new THREE.AnimationMixer(this.root);
    this.clipsPresent = this.clipsPresent || {};
    const attached = [];
    for (const clip of clips) {
      try {
        const key = this._classifyClipName(clip.name);
        const action = this.mixer.clipAction(clip, this.root);
        action.enabled = true;
        action.setEffectiveWeight(0);
        action.play();
        this.actions[key] = action;
        this.clipsPresent[key] = true;
        attached.push(key + ':' + (clip.name || 'clip'));
      } catch (e) {
        console.warn('[CharacterController] direct bind failed', clip.name, e);
      }
    }
    if (attached.length) this._playClip('idle', 0.1);
    return { ok: attached.length > 0, attached, method };
  }

  _setupClips(gltf, root) {
    this._disposeMixer();
    const clips = gltf.animations || [];
    if (!clips.length) {
      this.clipsPresent = {};
      return;
    }
    // Bind mixer to the *cloned* root so tracks resolve on this seat's skeleton
    this.mixer = new THREE.AnimationMixer(root);
    const used = new Set();

    const makeAction = (clip, weight = 0) => {
      const action = this.mixer.clipAction(clip, root);
      action.enabled = true;
      action.setEffectiveWeight(weight);
      action.play();
      action.setLoop(THREE.LoopRepeat, Infinity);
      return action;
    };

    for (const [key, needles] of Object.entries(CLIP_NEEDLES)) {
      const clip = findClip(clips, needles);
      if (!clip) {
        this.clipsPresent[key] = false;
        continue;
      }
      this.actions[key] = makeAction(clip, 0);
      this.clipsPresent[key] = true;
      used.add(clip);
    }

    // Idle fallback: first clip
    if (!this.actions.idle && clips[0]) {
      this.actions.idle = makeAction(clips[0], 1);
      this.clipsPresent.idle = true;
      used.add(clips[0]);
    }

    // Walk fallback (stops pure slide when Meshy names clips oddly or only 1 clip exists)
    if (!this.actions.walk) {
      // Prefer non-idle-named clips, else any unused, else first clip
      const nonIdle = clips.find((c) => {
        const n = (c.name || '').toLowerCase();
        return n && !/idle|tpose|t-pose|rest|stand|breath|neutral/.test(n);
      });
      const unused = clips.find((c) => !used.has(c));
      const walkClip = nonIdle || unused || clips[0];
      if (walkClip) {
        // Second clipAction on same clip returns same Action in Three — OK:
        // playing it while moving still animates bones (better than ice-skate).
        this.actions.walk = makeAction(walkClip, 0);
        this.actions.walk.timeScale = clips.length === 1 ? 1.35 : 1.0;
        this.clipsPresent.walk = true;
      }
    }
  }

  _playClip(name, fade = 0.2, opts = {}) {
    const next = this.actions[name];
    if (!next) {
      // procedural path — mark state only
      if (this.activeAction) {
        this.activeAction.setEffectiveWeight(0);
      }
      this.activeAction = null;
      return false;
    }
    if (this.activeAction === next) {
      next.setEffectiveWeight(1);
      if (opts.restart) next.reset().play();
      return true;
    }
    if (this.activeAction) {
      this.activeAction.crossFadeTo(next, fade, false);
    }
    next.reset();
    next.setEffectiveWeight(1);
    next.setLoop(opts.loop === false ? THREE.LoopOnce : THREE.LoopRepeat, opts.loop === false ? 1 : Infinity);
    if (opts.loop === false) {
      next.clampWhenFinished = true;
    }
    next.play();
    this.activeAction = next;
    return true;
  }

  _cmdMove(params) {
    if (!this.alive || this.state === 'ko') return { ok: false, error: 'ko' };
    // Interrupt non-attack busy only if not in hitstun/ko
    if (this.state === 'hit_react' && this.isBusy) return { ok: false, error: 'stunned' };

    if (params.target && (params.target.x != null || params.target.z != null)) {
      this.moveTarget = {
        x: Number(params.target.x) || 0,
        z: Number(params.target.z) || 0,
      };
      this.moveIntent = { x: 0, z: 0, active: true };
      return { ok: true, action: 'move', mode: 'target', target: this.moveTarget };
    }

    let dx = 0;
    let dz = 0;
    if (params.direction) {
      dx = Number(params.direction.x) || 0;
      dz = Number(params.direction.z) || Number(params.direction.y) || 0;
    } else {
      dx = Number(params.dx) || Number(params.x) || 0;
      dz = Number(params.dz) || Number(params.z) || 0;
    }
    const len = Math.hypot(dx, dz);
    if (len < 0.05) {
      this.moveIntent = { x: 0, z: 0, active: false };
      this.moveTarget = null;
      if (!this.isBusy && this.state !== 'block') this._setIdle();
      return { ok: true, action: 'move', mode: 'stop' };
    }
    this.moveIntent = { x: dx / len, z: dz / len, active: true };
    this.moveTarget = null;
    // Relative to camera if camera-forward provided by driver
    if (params.camera_relative && params.cam_forward) {
      this._camRel = {
        fx: Number(params.cam_forward.x) || 0,
        fz: Number(params.cam_forward.z) || -1,
        rx: Number(params.cam_right?.x) || 1,
        rz: Number(params.cam_right?.z) || 0,
      };
    } else {
      this._camRel = null;
    }
    return { ok: true, action: 'move', mode: 'direction', direction: this.moveIntent };
  }

  _cmdTurn(params) {
    if (!this.alive) return { ok: false, error: 'ko' };
    if (params.yaw != null) {
      this.facing = Number(params.yaw);
    } else if (params.degrees != null) {
      this.facing += (Number(params.degrees) * Math.PI) / 180;
    } else if (params.delta != null) {
      this.facing += Number(params.delta);
    } else if (params.look_at) {
      const p = this.getPosition();
      const lx = Number(params.look_at.x) - p.x;
      const lz = Number(params.look_at.z) - p.z;
      if (Math.hypot(lx, lz) > 1e-4) this.facing = Math.atan2(lx, lz);
    }
    if (this.root) this.root.rotation.y = this.facing;
    return { ok: true, action: 'turn', facing: this.facing };
  }

  _cmdIdle() {
    if (!this.alive) return { ok: false, error: 'ko' };
    this.moveIntent = { x: 0, z: 0, active: false };
    this.moveTarget = null;
    this.blocking = false;
    if (!this.isBusy) this._setIdle();
    return { ok: true, action: 'idle' };
  }

  _cmdAttack(kind, params) {
    if (!this.alive || this.state === 'ko') return { ok: false, error: 'ko' };
    if (this.isBusy && this.state !== 'walk' && this.state !== 'idle' && this.state !== 'block') {
      return { ok: false, error: 'busy' };
    }
    const combat = this.config.combat || {};
    const isHeavy = kind === 'attack_heavy';
    const dur = Number(
      isHeavy
        ? combat.attack_heavy_duration_ms ?? 520
        : combat.attack_light_duration_ms ?? 320,
    );
    const range = Number(
      isHeavy ? combat.attack_heavy_range ?? 1.9 : combat.attack_light_range ?? 1.65,
    );
    const damage = Number(
      params.damage ??
        (isHeavy ? combat.attack_heavy_damage ?? 18 : combat.attack_light_damage ?? 8),
    );

    this.moveIntent = { x: 0, z: 0, active: false };
    this.moveTarget = null;
    this.blocking = false;
    this.state = kind;
    this.busyUntil = performance.now() + dur;
    this._attackHitWindow = {
      until: performance.now() + dur * 0.65,
      kind,
      range,
      damage,
      resolved: false,
    };
    // Prefer Meshy set names punch / heavy_punch when present
    const clipName =
      kind === 'attack_heavy'
        ? (this.actions.heavy_punch ? 'heavy_punch' : kind)
        : (this.actions.punch ? 'punch' : kind);
    const played = this._playClip(clipName, 0.08, { loop: false, restart: true });
    if (!played) {
      this._proceduralT = 0;
    }
    // Face target if given
    if (params.look_at) this._cmdTurn({ look_at: params.look_at });
    return { ok: true, action: kind, duration_ms: dur, range, damage, clip: played };
  }

  _cmdBlock(params) {
    if (!this.alive || this.state === 'ko') return { ok: false, error: 'ko' };
    const on = params.on !== false && params.release !== true;
    if (!on) {
      this.blocking = false;
      if (!this.isBusy) this._setIdle();
      return { ok: true, action: 'block', on: false };
    }
    this.blocking = true;
    this.moveIntent = { x: 0, z: 0, active: false };
    this.state = 'block';
    const played = this._playClip('block', 0.1);
    if (!played) this._proceduralT = 0;
    return { ok: true, action: 'block', on: true, clip: played };
  }

  _cmdDodge(params) {
    if (!this.alive || this.state === 'ko') return { ok: false, error: 'ko' };
    if (this.isBusy) return { ok: false, error: 'busy' };
    const combat = this.config.combat || {};
    const dur = Number(combat.dodge_invuln_ms ?? 280);
    this.blocking = false;
    this.state = 'dodge';
    this.busyUntil = performance.now() + dur;
    this.invulnUntil = performance.now() + dur;
    // Sidestep relative to facing
    const side = params.side === 'left' ? -1 : 1;
    const dist = Number(params.distance ?? 1.1);
    const yaw = this.facing;
    const ox = Math.cos(yaw) * side * dist;
    const oz = -Math.sin(yaw) * side * dist;
    this._dodgeVel = { x: ox / (dur / 1000), z: oz / (dur / 1000), until: this.busyUntil };
    const played = this._playClip('dodge', 0.05, { loop: false, restart: true });
    if (!played) this._proceduralT = 0;
    return { ok: true, action: 'dodge', duration_ms: dur, clip: played };
  }

  _cmdJump(params) {
    if (!this.alive || this.state === 'ko') return { ok: false, error: 'ko' };
    if (this._jumpVel != null) return { ok: false, error: 'already airborne' };
    const height = Number(params.height ?? 1.4); // initial velocity for this apex (m/s)
    this._jumpVel = height;
    this._jumpY = 0;
    if (this.state !== 'attack_light' && this.state !== 'attack_heavy' && this.state !== 'block') {
      this.state = 'jump';
    }
    // Play 17-set jump clip when present
    if (this.actions.jump) this._playClip('jump', 0.08, { loop: false, restart: true });
    return { ok: true, action: 'jump' };
  }

  _cmdHitReact(params) {
    if (this.state === 'ko') return { ok: false, error: 'ko' };
    const combat = this.config.combat || {};
    const dur = Number(params.duration_ms ?? combat.hit_stun_ms ?? 350);
    this.blocking = false;
    this.moveIntent = { x: 0, z: 0, active: false };
    this.moveTarget = null;
    this.state = 'hit_react';
    this.busyUntil = performance.now() + dur;
    // Knockback opposite facing or along params.dir
    const kb = Number(params.knockback ?? 0.45);
    let dx = Number(params.dx);
    let dz = Number(params.dz);
    if (!Number.isFinite(dx) || !Number.isFinite(dz)) {
      dx = -Math.sin(this.facing) * kb;
      dz = -Math.cos(this.facing) * kb;
    } else {
      const len = Math.hypot(dx, dz) || 1;
      dx = (dx / len) * kb;
      dz = (dz / len) * kb;
    }
    this._knock = { x: dx, z: dz, until: this.busyUntil };
    const played = this._playClip('hit_react', 0.05, { loop: false, restart: true });
    if (!played) this._proceduralT = 0;
    return { ok: true, action: 'hit_react', duration_ms: dur, clip: played };
  }

  _cmdKo() {
    this.alive = false;
    this.health = 0;
    this.blocking = false;
    this.moveIntent = { x: 0, z: 0, active: false };
    this.moveTarget = null;
    this.state = 'ko';
    this.busyUntil = performance.now() + 1e9;
    this._attackHitWindow = null;
    const played = this._playClip('ko', 0.15, { loop: false, restart: true });
    if (!played) this._proceduralT = 0;
    return { ok: true, action: 'ko', clip: played };
  }

  _setIdle() {
    this.state = 'idle';
    this.blocking = false;
    this._playClip('idle', 0.2);
  }

  /**
   * Per-frame update. Call from the stage animate loop.
   * @param {number} dt seconds
   * @param {THREE.Camera} [camera] for camera-relative move if driver uses intent only
   */
  update(dt, camera = null) {
    if (!this.root) return;
    const now = performance.now();

    // Always pin feet
    this.root.position.y = this._charFloorY;

    // Jump (added 2026-07-17 — was entirely missing): real vertical velocity + gravity
    if (this._jumpVel != null) {
      this._jumpVel -= 9.8 * dt;
      this._jumpY = (this._jumpY || 0) + this._jumpVel * dt;
      if (this._jumpY <= 0) {
        this._jumpY = 0;
        this._jumpVel = null;
        if (this.state === 'jump') this._setIdle();
      }
      this.root.position.y = this._charFloorY + this._jumpY;
    }

    // Dodge velocity
    if (this._dodgeVel && now < this._dodgeVel.until) {
      this.root.position.x += this._dodgeVel.x * dt;
      this.root.position.z += this._dodgeVel.z * dt;
      this._clampBounds();
    } else {
      this._dodgeVel = null;
    }

    // Knockback
    if (this._knock && now < this._knock.until) {
      const t = (this._knock.until - now) / Math.max(1, this.busyUntil - (now - dt * 1000));
      const ease = Math.max(0, Math.min(1, t));
      this.root.position.x += this._knock.x * ease * dt * 4;
      this.root.position.z += this._knock.z * ease * dt * 4;
      this._clampBounds();
    } else if (this._knock && now >= this._knock.until) {
      this._knock = null;
    }

    // Attack busy end → idle
    if (
      (this.state === 'attack_light' ||
        this.state === 'attack_heavy' ||
        this.state === 'dodge' ||
        this.state === 'hit_react') &&
      now >= this.busyUntil &&
      this.alive
    ) {
      this._attackHitWindow = null;
      this._setIdle();
    }

    // Locomotion (when not locked into attack/hit/dodge/ko)
    const canMove =
      this.alive &&
      this.state !== 'ko' &&
      this.state !== 'attack_light' &&
      this.state !== 'attack_heavy' &&
      this.state !== 'hit_react' &&
      this.state !== 'dodge' &&
      !this.blocking;

    if (canMove) {
      let ix = 0;
      let iz = 0;

      if (this.moveTarget) {
        const p = this.getPosition();
        ix = this.moveTarget.x - p.x;
        iz = this.moveTarget.z - p.z;
        const dist = Math.hypot(ix, iz);
        if (dist < 0.12) {
          this.moveTarget = null;
          this.moveIntent = { x: 0, z: 0, active: false };
          this._setIdle();
          ix = 0;
          iz = 0;
        } else {
          ix /= dist;
          iz /= dist;
        }
      } else if (this.moveIntent.active) {
        if (this._camRel) {
          // intent x = right, z = forward (screen-up style mapped by driver)
          ix =
            this.moveIntent.x * this._camRel.rx + this.moveIntent.z * this._camRel.fx;
          iz =
            this.moveIntent.x * this._camRel.rz + this.moveIntent.z * this._camRel.fz;
        } else if (camera) {
          const { camFwd, camRight, moveDir } = this._tmp;
          camera.getWorldDirection(camFwd);
          camFwd.y = 0;
          if (camFwd.lengthSq() < 1e-6) camFwd.set(0, 0, -1);
          else camFwd.normalize();
          camRight.crossVectors(camFwd, new THREE.Vector3(0, 1, 0)).normalize();
          // intent: x = strafe, z = forward (W)
          moveDir.set(0, 0, 0);
          moveDir.addScaledVector(camRight, this.moveIntent.x);
          moveDir.addScaledVector(camFwd, this.moveIntent.z);
          if (moveDir.lengthSq() > 1e-8) {
            moveDir.normalize();
            ix = moveDir.x;
            iz = moveDir.z;
          }
        } else {
          ix = this.moveIntent.x;
          iz = this.moveIntent.z;
        }
      }

      const moving = Math.hypot(ix, iz) > 0.05;
      if (moving) {
        const len = Math.hypot(ix, iz);
        ix /= len;
        iz /= len;
        this.root.position.x += ix * this.moveSpeed * dt;
        this.root.position.z += iz * this.moveSpeed * dt;
        this.root.position.y = this._charFloorY;
        this._clampBounds();

        const yaw = Math.atan2(ix, iz);
        let diff = yaw - this.facing;
        while (diff > Math.PI) diff -= Math.PI * 2;
        while (diff < -Math.PI) diff += Math.PI * 2;
        this.facing += diff * Math.min(1, dt * this.turnSpeed);
        this.root.rotation.y = this.facing;

        if (this.state !== 'walk') {
          this.state = 'walk';
          // Prefer walk_fwd / run from 17-set over generic walk
          if (this.actions.walk_fwd) this._playClip('walk_fwd', 0.15);
          else if (this.actions.walk) this._playClip('walk', 0.15);
          else this._playClip('walk', 0.15);
        }
      } else if (this.state === 'walk') {
        this._setIdle();
      }
    }

    // Procedural fallbacks when clips missing
    this._updateProcedural(dt, now);

    if (this.mixer) this.mixer.update(dt);
  }

  _updateProcedural(dt, now) {
    if (!this.root) return;
    this._proceduralT += dt;

    // Walk without a bound walk clip → procedural gait (stops pure "ice skate" slide)
    if (this.state === 'walk' && !this.actions.walk) {
      const w = this._proceduralT * 9; // stride frequency
      const swing = Math.sin(w) * 0.7;
      if (this._hasLegRig) {
        const L = this._legs;
        if (L.upperL) L.upperL.rotation.x = swing;
        if (L.upperR) L.upperR.rotation.x = -swing;
        if (L.lowerL) L.lowerL.rotation.x = Math.max(0, -Math.sin(w)) * 1.05 + 0.08;
        if (L.lowerR) L.lowerR.rotation.x = Math.max(0, Math.sin(w)) * 1.05 + 0.08;
        if (L.footL) L.footL.rotation.x = -swing * 0.4;
        if (L.footR) L.footR.rotation.x = swing * 0.4;
        if (this._leftArm) this._leftArm.rotation.x = -swing * 0.55;
        if (this._rightArm && this.state !== 'attack_light' && this.state !== 'attack_heavy') {
          this._rightArm.rotation.x = swing * 0.55;
        }
      }
      // Always bob + slight lean so walk is visible even if bone names failed
      if (this._jumpVel == null) {
        this.root.position.y = this._charFloorY + Math.abs(Math.sin(w)) * 0.045;
        this.root.rotation.z = Math.sin(w) * 0.04;
        this.root.rotation.x = -0.06; // slight forward lean while moving
      }
    } else if (this.state === 'idle' && !this.actions.idle && this._jumpVel == null) {
      this.root.position.y = this._charFloorY + Math.sin(this._proceduralT * 2) * 0.008;
      this.root.rotation.z *= 0.9;
      this.root.rotation.x *= 0.9;
    } else if (this.state !== 'walk' && this._jumpVel == null) {
      // ease lean/roll back when stopping
      this.root.rotation.z *= 0.85;
      this.root.rotation.x *= 0.85;
    }

    // Relax limbs back to rest when not mid-stride (prevents a frozen mid-step pose)
    if (this.state !== 'walk' && this._hasLegRig) {
      const L = this._legs;
      for (const b of [L.upperL, L.upperR, L.lowerL, L.lowerR, L.footL, L.footR, this._leftArm]) {
        if (b) b.rotation.x *= 0.82;
      }
      if (this._rightArm && this.state !== 'attack_light' && this.state !== 'attack_heavy' && this.state !== 'block') {
        this._rightArm.rotation.x *= 0.82;
      }
    }

    // Attack lunge / arm swing
    if (
      (this.state === 'attack_light' || this.state === 'attack_heavy') &&
      !this.actions[this.state]
    ) {
      const heavy = this.state === 'attack_heavy';
      const phase = Math.min(1, this._proceduralT / (heavy ? 0.45 : 0.28));
      const lunge = Math.sin(phase * Math.PI) * (heavy ? 0.35 : 0.18);
      this.root.position.x += Math.sin(this.facing) * lunge * dt * 8;
      this.root.position.z += Math.cos(this.facing) * lunge * dt * 8;
      if (this._rightArm) {
        this._rightArm.rotation.x = -Math.sin(phase * Math.PI) * (heavy ? 1.4 : 0.9);
      }
      this._clampBounds();
    }

    // Block crouch
    if (this.state === 'block' && !this.actions.block && this._spine) {
      this._spine.rotation.x = 0.25;
    } else if (this._spine && this.state !== 'block' && this.state !== 'ko') {
      // only reset if we set it — soft approach
      this._spine.rotation.x *= 0.85;
    }

    // Hit react wobble
    if (this.state === 'hit_react' && !this.actions.hit_react) {
      this.root.rotation.z = Math.sin(this._proceduralT * 30) * 0.12;
    } else if (this.state !== 'hit_react' && this.state !== 'ko') {
      this.root.rotation.z *= 0.8;
    }

    // KO tip over
    if (this.state === 'ko' && !this.actions.ko) {
      const t = Math.min(1, this._proceduralT * 1.2);
      this.root.rotation.z = t * (Math.PI / 2) * 0.9;
      this.root.position.y = this._charFloorY + Math.sin(t * Math.PI * 0.5) * 0.15;
    }
  }

  _clampBounds() {
    if (!this.root) return;
    const r = Math.hypot(this.root.position.x, this.root.position.z);
    if (r > this.bounds) {
      const s = this.bounds / r;
      this.root.position.x *= s;
      this.root.position.z *= s;
    }
    this.root.position.y = this._charFloorY;
  }

  /**
   * Active attack hit window for combat system (one-shot per swing).
   */
  consumeAttackWindow() {
    const w = this._attackHitWindow;
    if (!w || w.resolved) return null;
    if (performance.now() > w.until) return null;
    w.resolved = true;
    return { kind: w.kind, range: w.range, damage: w.damage, attackerId: this.id };
  }

  peekAttackWindow() {
    const w = this._attackHitWindow;
    if (!w || w.resolved) return null;
    if (performance.now() > w.until) return null;
    return w;
  }

  _disposeMixer() {
    if (this.mixer) {
      try {
        this.mixer.stopAllAction();
        this.mixer.uncacheRoot(this.root || this.mixer.getRoot?.());
      } catch (_) { /* ignore */ }
    }
    this.mixer = null;
    this.actions = Object.create(null);
    this.activeAction = null;
    this.clipsPresent = Object.create(null);
  }

  disposeMeshOnly() {
    this._disposeMixer();
    if (this.root && this.parent) {
      this.parent.remove(this.root);
    }
    this.root = null;
  }

  dispose() {
    this.disposeMeshOnly();
  }
}

export default CharacterController;

// Side-effect: boot world group chat on Agent Field (ES module already imported by the board).
// Loads chat JS + boards boot once; no agent-field.html edit required for chat wire-up.
(function bootWorldChatOnField() {
  try {
    if (typeof window === 'undefined' || typeof document === 'undefined') return;
    const path = window.location && window.location.pathname || '';
    if (!/agent-field/i.test(path)) return;
    if (window.__PERCFECT_FIELD_CHAT_BOOT__) return;
    window.__PERCFECT_FIELD_CHAT_BOOT__ = true;
    function loadScript(src) {
      return new Promise((resolve, reject) => {
        if (document.querySelector(`script[src*="${src.split('?')[0].split('/').pop()}"]`)) {
          resolve();
          return;
        }
        const s = document.createElement('script');
        s.src = src;
        s.async = true;
        s.onload = () => resolve();
        s.onerror = () => reject(new Error('load fail ' + src));
        document.head.appendChild(s);
      });
    }
    loadScript('/static/js/world_group_chat.js?v=4')
      .then(() => loadScript('/static/js/world_chat_boards_boot.js?v=1'))
      .then(() => loadScript('/static/js/field_body_drive.js?v=1'))
      .catch((e) => console.warn('[field-chat]', e));
  } catch (e) {
    console.warn('[field-chat]', e);
  }
})();
