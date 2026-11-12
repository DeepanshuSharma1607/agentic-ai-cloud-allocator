"""
web.py - a live log page for your browser (port 8006).

ROLE
    Same information as the terminal viewer, but as a web page: open http://localhost:8006 on this PC - or, with --lan,
    from a phone or another laptop on the same Wi-Fi - and watch every part's logs live.

USAGE
    python -m obs.web                 # this PC only        -> http://localhost:8006
    python -m obs.web --lan           # visible on your network (use only on a network you trust)

WHAT YOU SEE
    - a row of coloured chips, one per part (green = logged just now, grey = gone quiet, red = recent errors)
    - "Problems": recent warnings and errors, grouped, each with a plain-English cause
    - the live log table with filters (part, level, search), a Pause box and a Download button

HOW IT WORKS
    A tiny FastAPI app. The page asks /api/logs every 1.5 seconds for lines newer than the last one it saw.
    All data comes from store.py (the same reader as the terminal viewer).

REMEMBER
    - Logs can contain details of your system; the default is local-only on purpose. --lan is a choice you make.
    - It never writes anything and never talks to the other parts, so it keeps working even when they are broken.

TEST    python -m pytest tests/test_obs.py -q
"""
from __future__ import annotations

import argparse
import json
import os

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, PlainTextResponse

import settings as S
from obs import store
from obs.problems import explain

PORT = int(os.getenv("AEGIS_PORT_LOGS", "8006"))
app = FastAPI(title="AegisCloud logs")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/logs")
def api_logs(since: float = 0.0, app: str = "", level: str = "INFO", q: str = "", limit: int = 300):
    apps = {x for x in app.split(",") if x} or None
    rows = store.read(since=since, apps=apps, level=level, q=q, limit=min(limit, 2000))
    for d in rows:
        if store.LEVELS.get(d.get("level"), 20) >= 30:
            d["why"] = explain(d["msg"])
    return rows


@app.get("/api/apps")
def api_apps():
    return store.app_status()


@app.get("/api/problems")
def api_problems(window_s: float = 900.0):
    return store.problems(window_s)


@app.get("/api/download")
def api_download(app: str = "", level: str = "DEBUG", q: str = ""):
    apps = {x for x in app.split(",") if x} or None
    rows = store.read(apps=apps, level=level, q=q, limit=100000)
    return PlainTextResponse("\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
                             headers={"Content-Disposition": "attachment; filename=aegiscloud_logs.jsonl"})


@app.get("/", response_class=HTMLResponse)
def page():
    return PAGE


PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>AegisCloud logs</title>
<style>
:root{--bg:#0f1115;--fg:#e6e6e6;--mut:#8b93a1;--bd:#262b33;--w:#e0b341;--e:#ef6a62;--ok:#4cc38a}
@media(prefers-color-scheme:light){:root{--bg:#fafafa;--fg:#1c1f24;--mut:#667085;--bd:#dde1e7;--w:#a36b00;--e:#c4281c;--ok:#117a4a}}
body{margin:0;background:var(--bg);color:var(--fg);font:14px system-ui,sans-serif}
header{padding:10px 14px;border-bottom:1px solid var(--bd);display:flex;flex-wrap:wrap;gap:8px;align-items:center}
h1{font-size:16px;margin:0 12px 0 0}
.chip{padding:2px 10px;border-radius:12px;border:1px solid var(--bd);font-size:12px}
.chip.ok{color:var(--ok)}.chip.bad{color:var(--e);border-color:var(--e)}.chip.quiet{color:var(--mut)}
#bar{padding:8px 14px;display:flex;flex-wrap:wrap;gap:8px;border-bottom:1px solid var(--bd)}
input,select,button{background:transparent;color:var(--fg);border:1px solid var(--bd);border-radius:6px;padding:4px 8px}
#prob{padding:6px 14px;border-bottom:1px solid var(--bd);font-size:13px}
#prob div{margin:4px 0}.why{color:var(--mut)}
#log{padding:6px 14px;font:12.5px/1.45 ui-monospace,Consolas,monospace;overflow-x:auto}
.r{white-space:pre-wrap;word-break:break-word}.WARNING{color:var(--w)}.ERROR,.CRITICAL{color:var(--e)}.DEBUG{color:var(--mut)}
.a{display:inline-block;min-width:78px;color:var(--mut)}
</style>
<header><h1>AegisCloud logs</h1><span id=chips></span></header>
<div id=prob></div>
<div id=bar>
 <select id=app><option value="">all parts</option></select>
 <select id=lvl><option>INFO</option><option>WARNING</option><option>ERROR</option><option>DEBUG</option></select>
 <input id=q placeholder="search text" size=22>
 <label><input type=checkbox id=pause> pause</label>
 <button id=dl>download</button><span id=cnt class=chip></span>
</div>
<div id=log></div>
<script>
let since=0,rows=[],seen=new Set();
const $=id=>document.getElementById(id);
const key=d=>d.t+d.app+d.msg;
const clock=t=>new Date(t*1000).toLocaleTimeString();
function line(d){const e=document.createElement('div');e.className='r '+d.level;
 const a=document.createElement('span');a.className='a';a.textContent=clock(d.t)+' '+d.app;e.append(a,d.level.padEnd(8)+' '+d.msg);
 if(d.exc)e.append('\\n'+d.exc);
 if(d.why){const w=document.createElement('div');w.className='why';w.textContent='   -> why: '+d.why;e.append(w)}return e}
async function tick(){
 if($('pause').checked)return;
 const p=new URLSearchParams({since,app:$('app').value,level:$('lvl').value,q:$('q').value,limit:300});
 try{const r=await (await fetch('/api/logs?'+p)).json();const box=$('log');
  const stick=innerHeight+scrollY>=document.body.scrollHeight-40;
  for(const d of r){if(seen.has(key(d)))continue;seen.add(key(d));box.append(line(d));since=Math.max(since,d.t)}
  while(box.children.length>1500)box.firstChild.remove();
  $('cnt').textContent=box.children.length+' lines';if(stick)scrollTo(0,document.body.scrollHeight)}catch(e){}
}
async function side(){
 try{const a=await (await fetch('/api/apps')).json();const c=$('chips');c.innerHTML='';
  const sel=$('app');for(const x of a){if(![...sel.options].some(o=>o.value==x.app))sel.add(new Option(x.app,x.app));
   const s=document.createElement('span');const fresh=x.last_seen_s!==null&&x.last_seen_s<60;
   s.className='chip '+(x.errors?'bad':fresh?'ok':'quiet');s.textContent=x.app+(x.errors?' ('+x.errors+' errors)':fresh?'':' (quiet)');c.append(s,' ')}
  const pr=await (await fetch('/api/problems')).json();const b=$('prob');b.innerHTML='';
  if(!pr.length){b.textContent='No warnings or errors in the last 15 minutes.';b.className='why'}else{b.className='';
   for(const g of pr.slice(0,6)){const d=document.createElement('div');d.className=g.level;
    d.textContent=g.app+' x'+g.count+': '+g.msg;if(g.why){const w=document.createElement('div');w.className='why';w.textContent='   why: '+g.why;d.append(w)}b.append(d)}}
 }catch(e){}
}
function reset(){since=0;seen.clear();$('log').innerHTML=''}
['app','lvl'].forEach(i=>$(i).onchange=reset);$('q').oninput=reset;
$('dl').onclick=()=>location='/api/download?app='+$('app').value+'&q='+encodeURIComponent($('q').value);
setInterval(tick,1500);setInterval(side,4000);tick();side();
</script>"""


def main(argv=None):
    ap = argparse.ArgumentParser(description="AegisCloud live log page")
    ap.add_argument("--lan", action="store_true", help="listen on the whole network, not only this PC")
    ap.add_argument("--port", type=int, default=PORT)
    a = ap.parse_args(argv)
    host = "0.0.0.0" if a.lan else S.HOST
    print(f"Logs page: http://localhost:{a.port}" + ("  (also reachable from other devices on your network)" if a.lan else ""))
    uvicorn.run(app, host=host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
