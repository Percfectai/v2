import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const JOINT_RADIUS = 0.04;
const BONE_COLOR = 0x00ff88;
const JOINT_COLOR = 0x66ffcc;
const GRID_COLOR_MAIN = 0x00ff88;
const GRID_COLOR_SUB = 0x004422;

const POSE_CONNECTIONS = [
  [11, 12], [11, 13], [13, 15], [12, 14], [14, 16],
  [11, 23], [12, 24], [23, 24],
  [23, 25], [25, 27], [24, 26], [26, 28],
];

function defaultStage() {
  return {
    version: 1,
    type: '3d_stage',
    world: {
      up: [0, 1, 0],
      floor_y: 0,
      grid: { spacing: 1.0, extent_x: 10, extent_z: 10, show_axes: true },
    },
    camera: {
      fov_deg: 50,
      position: [0, 1.6, 5],
      target: [0, 0, 0],
      near: 0.1,
      far: 100,
    },
    calibration_source: 'green_grid',
  };
}

function landmarkToWorld(lm, stage) {
  const ex = stage.world.grid.extent_x;
  const ez = stage.world.grid.extent_z;
  const x = (lm.x - 0.5) * ex;
  const z = (0.5 - lm.y) * ez;
  const y = stage.world.floor_y + Math.max(0, -lm.z * 2.5);
  return new THREE.Vector3(x, y, z);
}

export function createStage3D(canvas) {
  if (!canvas) return null;

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0x0a0a12, 1);

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0x0a0a12, 8, 28);

  let stage = defaultStage();
  const extent = () => Math.max(stage.world.grid.extent_x, stage.world.grid.extent_z);
  let gridHelper = null;
  let axesHelper = null;

  function rebuildGrid() {
    if (gridHelper) scene.remove(gridHelper);
    if (axesHelper) scene.remove(axesHelper);
    const size = extent();
    const divisions = Math.max(10, Math.round(size / stage.world.grid.spacing));
    gridHelper = new THREE.GridHelper(size, divisions, GRID_COLOR_MAIN, GRID_COLOR_SUB);
    gridHelper.material.opacity = 0.42;
    gridHelper.material.transparent = true;
    gridHelper.position.y = stage.world.floor_y;
    scene.add(gridHelper);
    if (stage.world.grid.show_axes) {
      axesHelper = new THREE.AxesHelper(size * 0.35);
      axesHelper.position.y = stage.world.floor_y + 0.01;
      scene.add(axesHelper);
    }
  }

  rebuildGrid();

  const camera = new THREE.PerspectiveCamera(
    stage.camera.fov_deg,
    1,
    stage.camera.near,
    stage.camera.far,
  );
  camera.position.fromArray(stage.camera.position);

  const controls = new OrbitControls(camera, canvas);
  controls.target.fromArray(stage.camera.target);
  controls.enableDamping = true;
  controls.maxPolarAngle = Math.PI * 0.49;
  controls.update();

  const ambient = new THREE.AmbientLight(0xffffff, 0.55);
  const key = new THREE.DirectionalLight(0xffffff, 0.85);
  key.position.set(2, 4, 3);
  scene.add(ambient, key);

  const skeletonGroup = new THREE.Group();
  scene.add(skeletonGroup);

  let motionFrames = [];
  let frameIndex = 0;
  let animId = null;
  let playing = false;

  function resize() {
    const w = canvas.clientWidth || 640;
    const h = canvas.clientHeight || 360;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }

  function clearSkeleton() {
    while (skeletonGroup.children.length) {
      const obj = skeletonGroup.children.pop();
      if (obj.geometry) obj.geometry.dispose();
      if (obj.material) obj.material.dispose();
    }
  }

  function drawSkeleton(landmarks) {
    clearSkeleton();
    if (!landmarks || landmarks.length < 29) return;

    const points = landmarks.map((lm) => landmarkToWorld(lm, stage));
    const jointGeo = new THREE.SphereGeometry(JOINT_RADIUS, 10, 10);
    const jointMat = new THREE.MeshStandardMaterial({
      color: JOINT_COLOR,
      emissive: 0x003322,
      transparent: true,
      opacity: 0.9,
    });

    points.forEach((p, i) => {
      if ((landmarks[i].visibility ?? 1) < 0.35) return;
      const m = new THREE.Mesh(jointGeo, jointMat);
      m.position.copy(p);
      skeletonGroup.add(m);
    });

    const lineMat = new THREE.LineBasicMaterial({ color: BONE_COLOR, transparent: true, opacity: 0.75 });
    POSE_CONNECTIONS.forEach(([a, b]) => {
      if (a >= points.length || b >= points.length) return;
      if ((landmarks[a].visibility ?? 1) < 0.35 || (landmarks[b].visibility ?? 1) < 0.35) return;
      const geo = new THREE.BufferGeometry().setFromPoints([points[a], points[b]]);
      skeletonGroup.add(new THREE.Line(geo, lineMat));
    });
  }

  function tick() {
    animId = requestAnimationFrame(tick);
    controls.update();
    renderer.render(scene, camera);
    if (playing && motionFrames.length > 1) {
      frameIndex = (frameIndex + 1) % motionFrames.length;
      drawSkeleton(motionFrames[frameIndex].landmarks);
    }
  }

  resize();
  tick();

  const ro = typeof ResizeObserver !== 'undefined'
    ? new ResizeObserver(() => resize())
    : null;
  if (ro) ro.observe(canvas);

  return {
    setStage(json) {
      stage = { ...defaultStage(), ...json, world: { ...defaultStage().world, ...(json.world || {}) } };
      rebuildGrid();
      const c = stage.camera;
      camera.fov = c.fov_deg;
      camera.position.fromArray(c.position);
      controls.target.fromArray(c.target);
      camera.updateProjectionMatrix();
    },

    async loadStageFromApi() {
      try {
        const res = await fetch('/api/calibrate-stage', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
        if (res.ok) this.setStage(await res.json());
      } catch (_) {
        this.setStage(defaultStage());
      }
    },

    async loadMotionFromUrl(url) {
      motionFrames = [];
      frameIndex = 0;
      clearSkeleton();
      if (!url) return;
      const res = await fetch(url);
      if (!res.ok) throw new Error('Could not load motion data');
      const data = await res.json();
      motionFrames = Array.isArray(data) ? data : (data.frames || []);
      if (motionFrames.length) {
        drawSkeleton(motionFrames[0].landmarks);
        playing = motionFrames.length > 1;
      }
    },

    setPlaying(on) {
      playing = !!on && motionFrames.length > 1;
    },

    destroy() {
      if (animId) cancelAnimationFrame(animId);
      if (ro) ro.disconnect();
      clearSkeleton();
      controls.dispose();
      renderer.dispose();
    },
  };
}