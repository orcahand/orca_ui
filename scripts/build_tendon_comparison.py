"""Build a self-contained visual review against a saved Git revision."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
NOTES = {
    "panel-036-2": "Includes the complete DP/PP bodies and tendon ends in the pin-clearance view.",
    "panel-041-5": "Includes the free tendon end beyond the AP housing in the tucked-tail view.",
    "panel-053-5": "Fits the complete tendon geometry around the thumb AP in the tucked-tail view.",
    "panel-063-1": "Adds translucent DP/PP bodies around the guide-pin routes and frames the complete thumb.",
    "panel-063-2": "Adds missing DP/PP context around the bearings and includes the complete tendon paths.",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default="3985b50")
    parser.add_argument("--output", type=Path, default=ROOT / "tendon-image-comparison.html")
    parser.add_argument("--review-report", type=Path, required=True)
    args = parser.parse_args()
    revision = subprocess.check_output(
        ["git", "rev-parse", "--verify", f"{args.baseline}^{{commit}}"], cwd=ROOT, text=True
    ).strip()
    guide = (ROOT / "frontend/src/components/assembly/guide.ts").read_text()
    titles = {f"p{number}": (chapter, title) for chapter, title, number in
              re.findall(r"add\('([^']+)', '([^']+)', (\d+),", guide)}
    manifest = json.loads((ROOT / "frontend/public/assembly/renders/manifest.json").read_text())
    report = json.loads(args.review_report.read_text())
    images, records = {}, []

    def embed(data):
        digest = hashlib.sha256(data).hexdigest()
        if digest not in images:
            images[digest] = "data:image/webp;base64," + base64.b64encode(data).decode()
        return digest

    for entry in manifest:
        relative = f"frontend/public/assembly/renders/{entry['key']}/{entry['file']}.webp"
        current = (ROOT / relative).read_bytes()
        original = subprocess.check_output(["git", "show", f"{revision}:{relative}"], cwd=ROOT)
        chapter, title = titles.get(entry["step"], ("Assembly", entry["step"]))
        records.append({"config": entry["key"], "file": entry["file"], "step": entry["step"],
                        "chapter": chapter, "title": title, "changed": original != current,
                        "before": embed(original), "after": embed(current),
                        "note": NOTES.get(entry["file"], "Reviewed in the second sweep; unchanged from the saved revision.")})
    records.sort(key=lambda r: (r["file"], r["config"]))
    payload = json.dumps({"revision": revision, "report": report, "records": records, "images": images}).replace("<", "\\u003c")
    output = TEMPLATE.replace("__DATA__", payload)
    args.output.write_text(output)
    print(f"Created {args.output}: {len(records)} illustrations, "
          f"{sum(r['changed'] for r in records)} changed pairs, {len(images)} unique embedded images; "
          f"{args.output.stat().st_size / 1024**2:.1f} MiB")


TEMPLATE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ORCA · Tendon image comparison</title><style>
:root{color-scheme:light;--page:#f5f4ef;--ink:#182c25;--muted:#596960;--mint:#b8cebf;--line:#d3dcd5;--accent:#24533f}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);font:16px/1.5 system-ui,-apple-system,sans-serif}main{max-width:1560px;margin:auto;padding:42px 28px 80px}.intro{max-width:940px}.eyebrow{text-transform:uppercase;font-size:11px;letter-spacing:.12em;font-weight:650;color:var(--accent);margin:0 0 8px}h1{font-size:clamp(32px,4vw,54px);line-height:1.1;letter-spacing:-.04em;margin:12px 0 20px}h2{font-size:22px;line-height:1.2;margin:0}.muted,.intro>p:not(.eyebrow){color:var(--muted)}.review{border:1px solid var(--line);background:#eaf0eb;border-radius:12px;padding:18px 22px;margin:24px 0}.review summary{font-weight:650;cursor:pointer}.review ul{padding-left:22px}.review p,.review li{font-size:14px}.filters{position:sticky;top:0;z-index:2;display:flex;align-items:end;gap:14px;flex-wrap:wrap;padding:16px 0;background:var(--page);border-bottom:1px solid var(--line);margin-bottom:28px}label{display:grid;gap:5px;font-size:12px;color:var(--muted)}select,input,button{font:inherit;border:1px solid #9fb3a5;border-radius:7px;background:#fff;color:var(--accent);padding:10px 12px}select,button{cursor:pointer}select,input{font-size:14px;max-width:100%}button:hover{background:#e3ece5}button:focus-visible,select:focus-visible,input:focus-visible{outline:3px solid #448a6d;outline-offset:3px}#count{margin-left:auto;color:var(--muted);font-size:13px}.card{background:#fff;border:1px solid var(--line);border-radius:14px;overflow:hidden;margin-bottom:30px}.card>header{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:24px 24px 0}.detail{font-size:12px;color:var(--muted);margin:8px 0 0}.change{margin:14px 24px 22px;color:var(--muted);font-size:14px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:2px;background:var(--line)}.single{max-width:1000px;margin:auto}figure{margin:0;background:var(--mint)}figcaption{display:flex;gap:12px;align-items:center;justify-content:space-between;padding:12px 18px;background:#eaf0eb;font-size:13px}figcaption span{font-size:11px;color:var(--muted)}img{display:block;width:100%;height:auto;object-fit:contain}.enlarge{white-space:nowrap;font-size:13px}dialog{border:0;border-radius:12px;padding:0;max-width:calc(100vw - 24px);width:1800px;max-height:94vh;background:var(--page);color:var(--ink)}dialog::backdrop{background:#14291fe0}.dialog-bar{position:sticky;top:0;z-index:3;background:var(--page);display:flex;justify-content:space-between;align-items:center;padding:12px 20px;gap:20px}#expanded .card{margin:0;border:0;border-radius:0}#expanded .enlarge{display:none}.footer{font-size:12px;color:var(--muted);margin-top:35px}.badge{display:inline-block;background:#eaf0eb;border-radius:4px;padding:2px 7px;margin-left:8px}.empty{padding:45px;text-align:center;color:var(--muted)}
@media(max-width:650px){main{padding:28px 12px}.card>header{padding:18px 16px 0}h2{font-size:18px}.change{margin:12px 16px 18px}.pair{grid-template-columns:1fr}.filters{position:static;gap:12px}.filters label{width:100%}#count{margin-left:0}figcaption{padding:10px 14px}.dialog-bar{font-size:13px}.review{padding:16px}}@media print{.filters,.enlarge,dialog{display:none}.card{break-inside:avoid}main{padding:0}.pair{grid-template-columns:1fr 1fr}}
</style></head><body><main>
<div class="intro"><p class="eyebrow">ORCA assembly guide · Second visual sweep</p><h1>Tendon visibility.<br>Before &amp; after.</h1><p>Compare the corrected illustrations with their originals, or browse every current illustration reviewed in the full sweep.</p><p id="provenance"></p></div>
<details class="review" open><summary>Full sweep results</summary><p id="review-result"></p><ul id="review-checks"></ul><p id="review-note"></p></details>
<div class="filters"><label>Show<select id="scope"><option value="changed">Changed images · before / after</option><option value="all">Full sweep · all reviewed images</option></select></label><label>Configuration<select id="config"><option value="">All configurations</option><option value="base-right-dynamixel">Base · Right · Dynamixel</option><option value="base-left-dynamixel">Base · Left · Dynamixel</option><option value="touch-right-dynamixel">Touch · Right · Dynamixel</option><option value="touch-left-dynamixel">Touch · Left · Dynamixel</option></select></label><label>Find a step or image<input type="search" id="search" placeholder="e.g. thumb, AP, panel-063"></label><span id="count" role="status" aria-live="polite"></span></div>
<div id="cards"></div><p class="footer">Self-contained review file · All images embedded · Opens offline without the ORCA UI. Unchanged images appear once; changed images appear as before/after pairs. These are still images; live-view checks are summarized above.</p>
</main><dialog aria-label="Enlarged image comparison"><div class="dialog-bar"><strong>Image review</strong><button id="close" type="button" autofocus>Close ×</button></div><div id="expanded"></div></dialog>
<script id="review-data" type="application/json">__DATA__</script><script>
const data=JSON.parse(document.querySelector('#review-data').textContent),scope=document.querySelector('#scope'),config=document.querySelector('#config'),search=document.querySelector('#search'),cards=document.querySelector('#cards'),dialog=document.querySelector('dialog'),expanded=document.querySelector('#expanded');
const escapeHTML=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const configName=k=>k.split('-').slice(0,2).map(s=>s[0].toUpperCase()+s.slice(1)).join(' · ')+' · Dynamixel';
document.querySelector('#provenance').textContent=`Originals: saved revision ${data.revision.slice(0,7)}. Updates: current local images. Reviewed ${data.report.date}.`;
document.querySelector('#review-result').textContent=data.report.result;
document.querySelector('#review-note').textContent=data.report.note;
document.querySelector('#review-checks').innerHTML=data.report.checks.map(s=>`<li>${escapeHTML(s)}</li>`).join('');
function figure(r,kind){const before=kind==='before',title=before?'Original':r.changed?'Updated':'Current · reviewed';return `<figure><figcaption><b>${title}</b><span>${before?'Before tendon visibility fixes':r.changed?'Current local render':'Unchanged from original'}</span></figcaption><img width="1800" height="1400" loading="lazy" alt="${escapeHTML(title+' — '+r.title+' — '+configName(r.config)+' — '+r.file)}" src="${data.images[r[kind]]}"></figure>`}
function card(r,index){return `<article class="card" data-index="${index}" data-file="${r.file}" data-config="${r.config}"><header><div><p class="eyebrow">${escapeHTML(r.chapter+' / '+configName(r.config))}</p><h2>${escapeHTML(r.title)}</h2><p class="detail">${escapeHTML(r.file)}<span class="badge">${r.changed?'Changed':'Reviewed · unchanged'}</span></p></div><button class="enlarge" type="button">Enlarge ↗</button></header><p class="change">${escapeHTML(r.note)}</p><div class="${r.changed?'pair':'single'}">${r.changed?figure(r,'before'):''}${figure(r,'after')}</div></article>`}
function filter(){const q=search.value.trim().toLowerCase(),matches=data.records.map((r,i)=>({r,i})).filter(({r})=>(scope.value==='all'||r.changed)&&(!config.value||config.value===r.config)&&(!q||`${r.title} ${r.chapter} ${r.file} ${r.step}`.toLowerCase().includes(q)));cards.innerHTML=matches.map(({r,i})=>card(r,i)).join('')||'<p class="empty">No images match these filters.</p>';document.querySelector('#count').textContent=`${matches.length} of ${scope.value==='all'?data.records.length:data.records.filter(r=>r.changed).length} illustrations`}
scope.addEventListener('change',filter);config.addEventListener('change',filter);search.addEventListener('input',filter);filter();
cards.addEventListener('click',e=>{if(!e.target.closest('.enlarge'))return;const index=Number(e.target.closest('article').dataset.index);expanded.innerHTML=card(data.records[index],index);expanded.querySelectorAll('img').forEach(img=>img.loading='eager');dialog.showModal();dialog.scrollTop=0});
document.querySelector('#close').addEventListener('click',()=>dialog.close());dialog.addEventListener('click',e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close()}});dialog.addEventListener('close',()=>expanded.replaceChildren());
</script></body></html>'''


if __name__ == "__main__":
    main()
