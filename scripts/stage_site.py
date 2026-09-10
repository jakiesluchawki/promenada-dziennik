#!/usr/bin/env python3
"""Stage an explicit public file list and version CSS/JS URLs by their contents."""
from pathlib import Path
import hashlib,re,shutil
PUBLIC_FILES=("index.html","styles.css","app.js","favicon.svg","report.enc.json",".nojekyll")
PUBLIC_DIRS=("assets","fonts","kompakt")
def stage(root):
    root=Path(root);out=root/"_site"
    if out.exists(): shutil.rmtree(out)
    out.mkdir()
    for name in PUBLIC_FILES:shutil.copy2(root/name,out/name)
    for name in PUBLIC_DIRS:shutil.copytree(root/name,out/name)
    for folder in [out,out/"kompakt"]:
        page=folder/"index.html";html=page.read_text()
        for name in ["styles.css","app.js"]:
            version=hashlib.sha256((folder/name).read_bytes()).hexdigest()[:12]
            html=re.sub(r'(href|src)="\./'+re.escape(name)+r'(?:\?[^"]*)?"',lambda m:m.group(1)+'="./'+name+'?v='+version+'"',html)
        page.write_text(html)
    return out
if __name__=="__main__":
    stage(Path(__file__).resolve().parent.parent)
    print("Public site staged with content-versioned assets.")
