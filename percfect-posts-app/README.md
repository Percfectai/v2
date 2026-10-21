# The Percfect Post (live at /percfectposts)

Google AI Studio app shipped as a static SPA on percfectai.com.

Rebuild after UI changes:

```bash
cd percfect-posts-app
npm install
npm run build
```

Output goes to `static/percfectposts/`. Flask serves it at `/percfectposts`. APIs live in `percfect_posts_bp.py`.
