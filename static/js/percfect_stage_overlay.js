/**
 * Percfect stage overlay — 50% green coordinate grid on video + DIY motion map.
 * Color-differentiated tracks + graph movement trails + integration perimeters.
 */

const TRACK_COLORS = ['#00ff88', '#ff66cc'];
const GRID_MAIN = '#00ff88';
const GRID_SUB = '#004422';
const GRID_OPACITY = 0.5;
const MIN_VIS = 0.45;
const TRAIL_LEN = 36;

const BONES = [
  [11, 12], [11, 13], [13, 15], [12, 14], [14, 16],
  [11, 23], [12, 24], [23, 24],
  [23, 25], [25, 27], [24, 26], [26, 28],
];

function defaultStage() {
  return {
    world: { floor_y: 0, grid: { spacing: 1, extent_x: 10, extent_z: 10, show_axes: true } },
  };
}

function vis(lm, i) {
  return (lm[i]?.visibility ?? 1) >= MIN_VIS;
}

function headY(lm) {
  return lm[0]?.y ?? 0;
}

function feetY(lm) {
  return ((lm[27]?.y ?? 0) + (lm[28]?.y ?? 0)) / 2;
}

function hipX(lm) {
  return ((lm[23]?.x ?? 0.5) + (lm[24]?.x ?? 0.5)) / 2;
}

function normToWorld(lm, stage) {
  const ex = stage.world.grid.extent_x;
  const ez = stage.world.grid.extent_z;
  const fy = feetY(lm);
  const cx = hipX(lm);
  return {
    x: (cx - 0.5) * ex,
    y: stage.world.floor_y,
    z: (0.5 - fy) * ez,
  };
}

function convexHull(points) {
  if (points.length < 3) return points.slice();
  const pts = points.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lower = [];
  for (const p of pts) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop();
    lower.push(p);
  }
  const upper = [];
  for (let i = pts.length - 1; i >= 0; i--) {
    const p = pts[i];
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop();
    upper.push(p);
  }
  upper.pop();
  lower.pop();
  return lower.concat(upper);
}

function skeletonHullNorm(lm) {
  const pts = lm
    .map((p, i) => (vis(lm, i) ? [p.x, p.y] : null))
    .filter(Boolean);
  return convexHull(pts);
}

function footprintQuadNorm(lm) {
  if (!vis(lm, 27) || !vis(lm, 28)) return null;
  const lx = lm[27].x;
  const rx = lm[28].x;
  const fy = feetY(lm);
  const hw = Math.max(0.04, Math.abs(lm[24].x - lm[23].x) * 0.55);
  const cx = hipX(lm);
  return [
    [cx - hw, fy],
    [cx + hw, fy],
    [cx + hw * 0.85, fy - 0.04],
    [cx - hw * 0.85, fy - 0.04],
  ];
}

function buildPerimeterFrame(lm, frameIdx, fps, stage, w, h) {
  const xs = [];
  const ys = [];
  lm.forEach((p, i) => {
    if (vis(lm, i)) {
      xs.push(p.x);
      ys.push(p.y);
    }
  });
  const hy = headY(lm);
  const fy = feetY(lm);
  const cx = hipX(lm);
  const mh = fy - hy;
  const sw = Math.abs((lm[11]?.x ?? 0) - (lm[12]?.x ?? 0));
  const ex = stage.world.grid.extent_x;
  const hull = skeletonHullNorm(lm);
  const footprint = footprintQuadNorm(lm);
  const world = normToWorld(lm, stage);
  return {
    frame: frameIdx,
    time_sec: fps ? Math.round((frameIdx / fps) * 10000) / 10000 : 0,
    bbox_norm: xs.length
      ? { x_min: Math.min(...xs), y_min: Math.min(...ys), x_max: Math.max(...xs), y_max: Math.max(...ys) }
      : null,
    scale_box: {
      center_x: cx,
      center_y: (hy + fy) / 2,
      height_norm: mh,
      width_norm: sw,
      grid_height_cells: mh * ex,
      grid_width_cells: sw * ex,
    },
    skeleton_hull_norm: hull,
    footprint_quad_norm: footprint,
    world_anchor: world,
    integration: {
      place_x_norm: cx,
      place_y_norm: fy,
      scale: mh,
      feet_y_norm: fy,
    },
  };
}

export function createStageOverlay({ wrap, video, canvas, hud }) {
  const ctx = canvas.getContext('2d');
  let stage = defaultStage();
  let tracks = [];
  let jobMeta = null;
  let rosterLinks = [];
  let showGrid = true;
  let showSkel = true;
  let showPerim = true;
  let showTrail = true;
  let animId = null;
  const trails = tracks.map(() => []);

  function resize() {
    const rect = wrap.getBoundingClientRect();
    const vw = video.videoWidth || 1280;
    const vh = video.videoHeight || 720;
    if (!vw || !vh) return;
    const scale = Math.min(rect.width / vw, (rect.height || rect.width * 9 / 16) / vh, 1);
    const dw = Math.floor(vw * scale);
    const dh = Math.floor(vh * scale);
    wrap.style.aspectRatio = `${vw} / ${vh}`;
    video.style.width = `${dw}px`;
    video.style.height = `${dh}px`;
    canvas.width = vw;
    canvas.height = vh;
    canvas.style.width = `${dw}px`;
    canvas.style.height = `${dh}px`;
  }

  function drawGrid(w, h) {
    if (!showGrid) return;
    const ext = stage.world.grid.extent_x;
    const steps = 20;
    ctx.save();
    ctx.globalAlpha = GRID_OPACITY;
    for (let i = 0; i <= steps; i++) {
      const t = i / steps;
      const nx = t;
      const ny = t;
      ctx.strokeStyle = i % 5 === 0 ? GRID_MAIN : GRID_SUB;
      ctx.lineWidth = i % 5 === 0 ? 1.2 : 0.6;
      ctx.beginPath();
      ctx.moveTo(nx * w, 0);
      ctx.lineTo(nx * w, h);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(0, ny * h);
      ctx.lineTo(w, ny * h);
      ctx.stroke();
    }
    if (stage.world.grid.show_axes) {
      ctx.globalAlpha = 0.45;
      ctx.strokeStyle = '#ff4466';
      ctx.beginPath();
      ctx.moveTo(w * 0.5, 0);
      ctx.lineTo(w * 0.5, h);
      ctx.stroke();
      ctx.strokeStyle = '#4488ff';
      ctx.beginPath();
      ctx.moveTo(0, h * 0.92);
      ctx.lineTo(w, h * 0.92);
      ctx.stroke();
    }
    ctx.restore();
  }

  function drawTrack(track, ti, w, h) {
    const color = track.color || TRACK_COLORS[ti % TRACK_COLORS.length];
    const frame = pickFrame(track.frames, video.currentTime, jobMeta?.fps || 30);
    if (!frame?.landmarks) return;
    const lm = frame.landmarks;
    const perim = buildPerimeterFrame(lm, frame.frame, jobMeta?.fps, stage, w, h);

    if (showTrail) {
      const gx = hipX(lm);
      const gy = feetY(lm);
      if (!trails[ti]) trails[ti] = [];
      trails[ti].push([gx * w, gy * h]);
      if (trails[ti].length > TRAIL_LEN) trails[ti].shift();
      if (trails[ti].length > 1) {
        ctx.save();
        ctx.strokeStyle = color;
        ctx.globalAlpha = 0.55;
        ctx.lineWidth = 2;
        ctx.beginPath();
        trails[ti].forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
        ctx.stroke();
        ctx.restore();
      }
    }

    if (showSkel) {
      ctx.save();
      ctx.strokeStyle = color;
      ctx.globalAlpha = 0.78;
      ctx.lineWidth = 2;
      BONES.forEach(([a, b]) => {
        if (!vis(lm, a) || !vis(lm, b)) return;
        ctx.beginPath();
        ctx.moveTo(lm[a].x * w, lm[a].y * h);
        ctx.lineTo(lm[b].x * w, lm[b].y * h);
        ctx.stroke();
      });
      lm.forEach((p, i) => {
        if (!vis(lm, i)) return;
        ctx.fillStyle = color;
        ctx.globalAlpha = 0.9;
        ctx.beginPath();
        ctx.arc(p.x * w, p.y * h, 3.5, 0, Math.PI * 2);
        ctx.fill();
      });
      ctx.restore();
    }

    if (showPerim && perim.skeleton_hull_norm?.length >= 3) {
      const pts = perim.skeleton_hull_norm.map(([x, y]) => [x * w, y * h]);
      ctx.save();
      ctx.fillStyle = color === TRACK_COLORS[0] ? 'rgba(0,255,136,0.1)' : 'rgba(255,102,204,0.1)';
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.setLineDash([6, 4]);
      ctx.beginPath();
      pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.restore();
    }

    if (hud && ti === 0) {
      const wpos = perim.world_anchor;
      hud.textContent = `Grid · X ${wpos.x.toFixed(2)} Z ${wpos.z.toFixed(2)} · height ${perim.scale_box.grid_height_cells.toFixed(1)} cells · frame ${frame.frame}`;
    }
  }

  function draw() {
    const w = canvas.width;
    const h = canvas.height;
    if (!w || !h) return;
    ctx.clearRect(0, 0, w, h);
    drawGrid(w, h);
    tracks.forEach((t, i) => drawTrack(t, i, w, h));
  }

  function tick() {
    animId = requestAnimationFrame(tick);
    if (!video.paused && !video.ended) draw();
  }

  function pickFrame(frames, timeSec, fps) {
    if (!frames?.length) return null;
    const idx = Math.round(timeSec * fps);
    let best = frames[0];
    let bestD = Math.abs(best.frame - idx);
    for (const f of frames) {
      const d = Math.abs(f.frame - idx);
      if (d < bestD) {
        best = f;
        bestD = d;
      }
    }
    return best;
  }

  async function loadMotionUrl(url, color, label) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`motion data ${res.status}`);
    const data = await res.json();
    const frames = Array.isArray(data) ? data : data.frames || [];
    return { frames, color, label, motionUrl: url };
  }

  return {
    setLayers({ grid, skeleton, perimeter, trail }) {
      if (grid !== undefined) showGrid = grid;
      if (skeleton !== undefined) showSkel = skeleton;
      if (perimeter !== undefined) showPerim = perimeter;
      if (trail !== undefined) showTrail = trail;
      draw();
    },

    async loadStage() {
      try {
        const res = await fetch('/api/calibrate-stage', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: '{}',
        });
        if (res.ok) stage = { ...defaultStage(), ...(await res.json()) };
      } catch (_) {
        stage = defaultStage();
      }
    },

    setRosterLinks(links) {
      rosterLinks = links || [];
    },

    async loadFromAnalysis(data, base) {
      const dual = data.character_count === 2
        && data.motion_data_1
        && data.motion_data_2;
      const videoUrl = dual
        ? `${base}${data.background_video || data.character_1_video}`
        : `${base}${data.character_video}`;
      const trackSpecs = dual
        ? [
            { url: `${base}${data.motion_data_1}`, label: 'Character 1' },
            { url: `${base}${data.motion_data_2}`, label: 'Character 2' },
          ]
        : [{ url: `${base}${data.motion_data}`, label: 'Character 1' }];

      let w = 1280;
      let h = 720;
      if (data.resolution && /(\d+)x(\d+)/.test(data.resolution)) {
        const m = data.resolution.match(/(\d+)x(\d+)/);
        w = parseInt(m[1], 10);
        h = parseInt(m[2], 10);
      }
      await fetch('/api/calibrate-stage', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image_width: w, image_height: h }),
      }).then((r) => r.ok && r.json()).then((j) => { if (j) stage = { ...defaultStage(), ...j }; }).catch(() => {});

      jobMeta = {
        job_id: data.job_id,
        fps: parseFloat(data.fps) || 30,
        width: w,
        height: h,
        resolution: data.resolution,
        character_count: dual ? 2 : 1,
        overlay_opacity: GRID_OPACITY,
      };

      tracks = [];
      trails.length = 0;
      for (const spec of trackSpecs) {
        tracks.push(await loadMotionUrl(spec.url, spec.color, spec.label));
        trails.push([]);
      }

      video.src = videoUrl;
      video.loop = true;
      await new Promise((res, rej) => {
        video.onloadedmetadata = () => { resize(); res(); };
        video.onerror = rej;
      });
      draw();
      if (!animId) tick();
    },

    exportPerimeterTrack() {
      if (!jobMeta || !tracks.length) return null;
      const w = canvas.width || jobMeta.width || 1280;
      const h = canvas.height || jobMeta.height || 720;
      const fps = jobMeta.fps || 30;
      const characters = tracks.map((t, i) => {
        const roster = rosterLinks[i] || null;
        const frames = t.frames.map((f) => {
          const pf = buildPerimeterFrame(f.landmarks, f.frame, fps, stage, w, h);
          if (pf.bbox_norm) {
            pf.perimeter_px = {
              bbox: [
                Math.round(pf.bbox_norm.x_min * w),
                Math.round(pf.bbox_norm.y_min * h),
                Math.round(pf.bbox_norm.x_max * w),
                Math.round(pf.bbox_norm.y_max * h),
              ],
            };
          }
          if (roster?.motion_profile?.anchor) {
            const mh = pf.scale_box.height_norm;
            const rh = roster.motion_profile.anchor.body_height_norm;
            if (rh > 0) pf.integration.scale_factor_vs_roster = mh / rh;
          }
          return pf;
        });
        return {
          track_id: i,
          label: t.label,
          track_color: t.color || TRACK_COLORS[i],
          motion_data_url: t.motionUrl,
          roster_character_id: roster?.id ?? null,
          frames,
        };
      });
      return {
        version: 1,
        type: 'perimeter_track',
        source: {
          job_id: jobMeta.job_id,
          width: w,
          height: h,
          fps,
          character_count: jobMeta.character_count,
        },
        stage: {
          calibration_source: stage.calibration_source || 'green_grid',
          grid_spacing: stage.world?.grid?.spacing ?? 1,
          extent_x: stage.world?.grid?.extent_x ?? 10,
          extent_z: stage.world?.grid?.extent_z ?? 10,
          overlay_opacity: GRID_OPACITY,
        },
        characters,
      };
    },

    downloadPerimeterTrack() {
      const doc = this.exportPerimeterTrack();
      if (!doc) return;
      const blob = new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `perimeter_track_${jobMeta.job_id || 'motion'}.json`;
      a.click();
      URL.revokeObjectURL(a.href);
    },

    draw,
    resize,
  };
}