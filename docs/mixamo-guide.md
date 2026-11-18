# Mixamo → GLB character for the Percfect 3D board

The 3D board (`templates/percfect_3d.html`, served at `/3d`, `/play/3d`, `/studios/play/3d`, `/the-dome`) loads a rigged
GLB with Three.js `GLTFLoader` and drives it with an `AnimationMixer`. This guide gets you a free, auto-rigged,
animated humanoid from Mixamo into that page.

> **Mixamo does not export GLB.** Its download formats are **FBX Binary (.fbx)**, **FBX for Unity (.fbx)**,
> FBX ASCII, DAE (Collada), and (characters only) OBJ. You download FBX, then convert to `.glb` (step 3).
> Mixamo needs a free Adobe ID, so **Nick has to do steps 1–2 himself**.

## 1. Pick (or auto-rig) a character — mixamo.com

1. Go to <https://www.mixamo.com> and sign in with an Adobe ID (free).
2. **Characters** tab → pick a humanoid (e.g. *Y Bot*, *X Bot*, or any stock character).
   - **Own model instead:** **Upload Character** → `.fbx`, `.obj`, or `.zip` (OBJ + textures). Model must be a single
     humanoid mesh in T-pose/A-pose, facing forward. In the Auto-Rigger, place the markers (chin, wrists, elbows,
     knees, groin), keep **Skeleton LOD: Standard Skeleton (65)**, click **Next**. Mixamo creates the skeleton and skin
     weights (this is what gives you skinning).
3. Keep the **same character selected** for every animation download below, so all files share one skeleton
   (same bone names → clips can be combined).

## 2. Download the animations

Search the **Animations** tab for each clip, click it, adjust, then **Download**:

| Clip for the page | Mixamo search | Notes |
|---|---|---|
| `idle` | "Idle" / "Breathing Idle" | Download this one **With Skin** (it carries the mesh). |
| `walk` | "Walking" | Tick **In Place** (right panel). |
| `run`  | "Running" | Tick **In Place**. |
| `cast` | "magic" or "spell" (any standing magic attack / spell cast) | Plays once on the Cast button / Space. |

**Download Settings that matter**

| Setting | Value | Why |
|---|---|---|
| Format | **FBX Binary (.fbx)** | Best for Blender / FBX2glTF. (There is no GLB option.) |
| Skin | **With Skin** for the first file (idle), **Without Skin** for walk/run/cast | Mesh only once; the rest are skeleton + animation. |
| Frames per Second | **30** | Matches what the page expects; 60 doubles file size. |
| Keyframe Reduction | **None** | Avoids jitter; compress later instead. |
| In Place (animation panel) | **On** for walk/run | The page moves the character in code. (The page also strips horizontal hip motion as a safety net.) |

Name the files: `character.fbx` (idle, with skin), `walk.fbx`, `run.fbx`, `cast.fbx`.

## 3. Convert FBX → GLB (skinning + animations)

The page looks for clips by name: **the clip name must contain `idle`, `walk`, `run`, or `cast`**
(also matches `breath/stand`, `jog/sprint`, `spell/magic/charg/attack`). Mixamo names every clip `mixamo.com`
(Blender shows `Armature|mixamo.com|Layer0`), so rename them — or use per-clip file names (option B).

### Option A — Blender (recommended: one GLB with all clips)

Blender 3.6+ / 4.x. Save this as `mixamo_to_glb.py` and run:

```bash
blender -b -P mixamo_to_glb.py -- character.fbx walk.fbx run.fbx cast.fbx character.glb
```

```python
import bpy, sys, os
args = sys.argv[sys.argv.index("--") + 1:]
char_fbx, anim_fbx, out = args[0], args[1:-1], args[-1]

def stem(p):
    return os.path.splitext(os.path.basename(p))[0].lower()

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=char_fbx, ignore_leaf_bones=True, automatic_bone_orientation=False)
rig = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
rig.animation_data_create()
actions = []
if rig.animation_data.action:              # the clip downloaded "With Skin"
    rig.animation_data.action.name = "idle"
    actions.append(rig.animation_data.action)

for path in anim_fbx:                       # walk / run / cast ("Without Skin")
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=path, ignore_leaf_bones=True, automatic_bone_orientation=False)
    new = [o for o in bpy.data.objects if o not in before]
    arm = next(o for o in new if o.type == "ARMATURE")
    act = arm.animation_data.action
    act.name = stem(path)                   # walk / run / cast
    act.use_fake_user = True
    actions.append(act)
    for o in new:
        bpy.data.objects.remove(o, do_unlink=True)

for act in actions:                         # one NLA track per clip -> one glTF animation per clip
    track = rig.animation_data.nla_tracks.new()
    track.name = act.name
    track.strips.new(act.name, int(act.frame_range[0]), act)
rig.animation_data.action = None

bpy.ops.export_scene.gltf(
    filepath=out, export_format="GLB",
    export_skins=True, export_animations=True,
    export_animation_mode="ACTIONS",        # every action -> separate named clip
    export_force_sampling=True, export_frame_step=1,
    export_yup=True)
print("wrote", out, [a.name for a in actions])
```

GUI equivalent: *File → Import → FBX* the character (Armature → **Ignore Leaf Bones** on), import each animation FBX,
in the **Action Editor** rename each action to `idle`/`walk`/`run`/`cast`, assign them to the character's armature
and **Push Down** each into the NLA, delete the extra imported armatures, then *File → Export → glTF 2.0*:
Format **glTF Binary (.glb)**, Include → Data: **Skinning** on, Animation: on, Mode **Actions**, Sampling on.

Verify: drop `character.glb` on <https://gltf-viewer.donmccurdy.com> or <https://gltf.report> — you should see the mesh
deform and 4 clips named idle/walk/run/cast.

### Option B — FBX2glTF (no Blender, one GLB per clip)

```bash
FBX2glTF --binary --input character.fbx --output character   # -> character.glb (mesh + idle)
FBX2glTF --binary --input walk.fbx --output walk               # -> walk.glb (skeleton + walk)
FBX2glTF --binary --input run.fbx  --output run
FBX2glTF --binary --input cast.fbx --output cast
```

(Binaries: <https://github.com/godotengine/FBX2glTF/releases>.) The page loads `character.glb` and then merges clips
from `idle.glb`, `walk.glb`, `run.glb`, `cast.glb` in the same folder; when a clip is still named `mixamo.com`, the
**file name** decides which state it becomes. This only works because all files share the same Mixamo skeleton.

### Optional: shrink it

```bash
npx @gltf-transform/cli optimize character.glb character.glb --compress meshopt --texture-compress webp
```

The page already registers the Draco and Meshopt decoders, so compressed GLBs load as-is.

## 4. Put it in the repo

```
static/models/character.glb      # required (mesh + skin + ideally all clips)
static/models/walk.glb           # optional, option B only
static/models/run.glb            # optional
static/models/cast.glb           # optional
static/models/idle.glb           # optional
```

The page tries, in order: `?model=/static/…glb` (URL param), `/static/models/character.glb` (+ the optional clip
files), then the existing `/static/RIGGED_poyo_walking.glb` + `RIGGED_poyo_running.glb` + `poyo_X_cast.glb`, and
finally a built-in placeholder robot. Any GLB is auto-scaled to ~1.8 m and centred on the dais. Test a file without
replacing anything: `https://percfectai.com/3d?model=/static/models/character.glb`.

```bash
git add static/models/*.glb && git commit -m "Add Mixamo character" && git push origin main   # Render redeploys
```

## 5. `.gitignore` and deployment (checked 2026-11-18)

- `.gitignore` has **no rule for `static/`, `static/models/`, or `*.glb`**. The only static rule is
  `static/uploads/` (user uploads). All current GLBs in `static/` (≈68 MB total; largest `metro_tunnel.glb` 21 MB)
  are committed normally — no Git LFS.
- **Do not add `*.glb` or `static/models/` to `.gitignore`.** Render builds from the Git checkout, so an ignored GLB is
  never deployed and the page silently falls back to the poyo / placeholder character.
- Size limits: GitHub warns on files > 50 MB and rejects > 100 MB. A Mixamo character + 4 clips is typically 2–15 MB
  (smaller after `optimize`), so committing directly is fine.
- **Git LFS is not recommended here**: Render does not document LFS support for builds, so LFS pointers might
  be deployed instead of the real files. If models outgrow GitHub, host them on external storage/CDN (e.g. Supabase
  Storage public bucket with CORS) and load them via `window.percfect3D.loadCharacter(url)`.

## Licence note

Mixamo characters and animations are royalty-free for personal and commercial projects under Adobe's terms; you
cannot redistribute the raw Mixamo files as a standalone asset pack. Check the current Adobe terms before shipping.
