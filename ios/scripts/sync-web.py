#!/usr/bin/env python3
"""Copy reviewed public UI into the iOS bundle, excluding all report data."""
from pathlib import Path
import hashlib, shutil
BASE = Path(__file__).resolve().parents[1]
SOURCE = BASE.parent
WEB = BASE / "Promenada/Web"
def main():
    WEB.mkdir(parents=True, exist_ok=True)
    for name in ("assets", "fonts"):
        target = WEB / name
        if target.exists(): shutil.rmtree(target)
        shutil.copytree(SOURCE / name, target)
    js = (SOURCE / "app.js").read_text().split("function fromB64(s)")[0]
    start = js.index("try{const saved=JSON.parse(localStorage")
    end = js.index("\nfunction saveReview()", start)
    js = js[:start] + js[end:]
    (WEB / "app.js").write_text(js + (BASE / "scripts/native-bridge.js").read_text())
    html = (SOURCE / "index.html").read_text()
    html = html.replace("connect-src 'self'", "connect-src 'none'")
    html = html.replace("Promenada · Rodzinny dziennik", "Mahbrus · Rodzinny dziennik")
    html = html.replace(">promenada<", ">mahbrus<").replace("Promenada · rodzinny dziennik", "Mahbrus · rodzinny dziennik")
    (WEB / "index.html").write_text(html)
    (WEB / "styles.css").write_text((SOURCE / "styles.css").read_text() + "\n/* Native safe area is provided by SwiftUI. */\nbody{padding-bottom:84px} @media(max-width:760px){#nav{padding-bottom:10px}}\n")
    shutil.copy2(SOURCE / "favicon.svg", WEB / "favicon.svg")
    assert not (WEB / "report.enc.json").exists()
    print("Bundled reviewed UI; report and credentials are not copied.")
if __name__ == "__main__": main()
