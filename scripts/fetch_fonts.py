#!/usr/bin/env python3
"""Download optional fonts into imagebot/assets/fonts/.

The display fonts used by the cards ship with the repo already. This script
mainly fetches a CJK font (Noto Sans JP) so Japanese/Chinese subtitles like
"進撃の巨人" render even on machines without a system CJK font.

    python scripts/fetch_fonts.py
"""
from __future__ import annotations

from pathlib import Path

import urllib.request

DEST = Path(__file__).resolve().parent.parent / "imagebot" / "assets" / "fonts"

# Full TTFs mirrored on jsDelivr (Open Font License).
FONTS = {
    "NotoSansJP-Bold.ttf":
        "https://cdn.jsdelivr.net/npm/@expo-google-fonts/noto-sans-jp/NotoSansJP_700Bold.ttf",
    "NotoSansJP-Regular.ttf":
        "https://cdn.jsdelivr.net/npm/@expo-google-fonts/noto-sans-jp/NotoSansJP_400Regular.ttf",
}


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    for name, url in FONTS.items():
        out = DEST / name
        if out.exists():
            print(f"  ✓ {name} (already present)")
            continue
        try:
            print(f"  … downloading {name}")
            req = urllib.request.Request(url, headers={"User-Agent": "imagebot"})
            data = urllib.request.urlopen(req, timeout=60).read()
            out.write_bytes(data)
            print(f"  ✓ {name} ({len(data)//1024} KB)")
        except Exception as e:
            print(f"  ✗ {name}: {e}")
    print(f"\nFonts in {DEST}:")
    for p in sorted(DEST.glob('*.ttf')):
        print("   -", p.name)


if __name__ == "__main__":
    main()
