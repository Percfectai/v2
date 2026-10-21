#!/usr/bin/env python3
"""
Quick test client for the Percfect Motion Analyzer v2
Run after you deploy to Render or locally with uvicorn.
"""

import os
import requests
from pathlib import Path

API_BASE = os.environ.get(
    "MOTION_API_URL", "https://percfect-motion-analyzer.onrender.com"
)

def test_analyze(video_path: str):
    video_path = Path(video_path)
    if not video_path.exists():
        print(f"❌ File not found: {video_path}")
        return

    print(f"🚀 Uploading {video_path.name} ({video_path.stat().st_size / 1024:.1f} KB)...")

    with open(video_path, "rb") as f:
        files = {"video": (video_path.name, f, "video/mp4")}
        try:
            resp = requests.post(f"{API_BASE}/analyze-motion", files=files, timeout=300)
            resp.raise_for_status()
            data = resp.json()

            print("✅ SUCCESS")
            print(f"   Job ID: {data.get('job_id')}")
            print(f"   Character video: {API_BASE}{data.get('character_video')}")
            print(f"   Background video: {API_BASE}{data.get('background_video')}")
            print(f"   Motion data JSON: {API_BASE}{data.get('motion_data')}")
            print(f"   Metadata:       {API_BASE}{data.get('metadata')}")
            print(f"   Stats: {data.get('motion_frames')} motion frames | {data.get('fps')} fps | {data.get('resolution')} | {data.get('duration_sec')}s")

            print("\n🎉 Ready to feed into your motionV2 frontend + character compositor!")
            return data
        except Exception as e:
            print(f"❌ Error: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(e.response.text)

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python test_motion_client.py /path/to/short_performance.mp4")
        sys.exit(1)
    test_analyze(sys.argv[1])