"""Generate docs/index.html — a static GitHub Pages build of the app that replays canned
example runs (Pages has no Python/LLM backend). It is the real src/alpha/web/index.html
with a network shim prepended: window.fetch is overridden to serve docs/demo-data.json,
and /api/review/stream is replayed as a real ReadableStream (trace steps + token-by-token
briefing) so the live streaming UX is preserved with zero backend.

    python scripts/build_static_demo.py      # after capture_demo_data.py
"""
import json

APP = open("src/alpha/web/index.html", encoding="utf-8").read()
DEMO = json.load(open("docs/demo-data.json", encoding="utf-8"))

BANNER = """
<div style="background:#101722;border-bottom:1px solid #1f2937;color:#8b98a9;font:12.5px/1.4 -apple-system,Segoe UI,sans-serif;padding:8px 16px;text-align:center">
  <b style="color:#2dd4bf">Static demo</b> — canned example runs (GitHub Pages has no model).
  Try the suggestions below. For the live local/Azure LLM, <a href="https://github.com/aptsalt/alpha-advisor" style="color:#2dd4bf">clone &amp; run the repo</a>.
</div>
"""

SHIM = """
<script id="demo-shim">
const DEMO = __DEMO__;
function pickExample(q){q=(q||'').toLowerCase();
  if(q.includes('guarantee')||q.includes('insider'))return 'blocked';
  if(q.includes('marcus')||q.includes('c-1002'))return 'marcus';
  return 'jane';}
function jsonResponse(o){return new Response(JSON.stringify(o),{headers:{'Content-Type':'application/json'}});}
const _fetch=window.fetch.bind(window);
window.fetch=async(url,opts={})=>{
  url=(typeof url==='string')?url:url.url; let m;
  if(url.endsWith('/api/health'))return jsonResponse({ok:true,provider:'mock',chat_model:'demo'});
  if(url.endsWith('/api/clients'))return jsonResponse(DEMO.clients);
  if(url.endsWith('/api/portfolio/scan'))return jsonResponse(DEMO.scan);
  if(m=url.match(/\\/api\\/graph\\/([^/]+)$/))return jsonResponse(DEMO.graph[m[1]]||{nodes:[],edges:[]});
  if(url.match(/\\/api\\/review\\/[^/]+\\/eval$/)){const ex=window.__ex||DEMO.examples.jane;
    return jsonResponse(ex.eval||{overall:0,citation_coverage:{score:0,cited:0,total:0},groundedness:{score:0,unsupported:[]},suitability:{score:0,missed:[]}});}
  if(url.match(/\\/api\\/review\\/[^/]+\\/decision$/)){const ex=window.__ex||DEMO.examples.jane;const f=ex.final||{};
    return jsonResponse({decision:'approved',final:(f.draft||f.final||''),audit_ok:true});}
  if(url.endsWith('/api/review/stream')){const body=JSON.parse(opts.body||'{}');
    const ex=DEMO.examples[pickExample(body.request)];window.__ex=ex;return streamResponse(ex);}
  return _fetch(url,opts);
};
function streamResponse(ex){
  const enc=new TextEncoder();const frame=o=>enc.encode('data: '+JSON.stringify(o)+'\\n\\n');
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const stream=new ReadableStream({async start(c){
    c.enqueue(frame({type:'run',run_id:'demo'}));
    for(const step of (ex.trace||[])){await sleep(240);c.enqueue(frame({type:'node',node:step.node,trace:[step]}));}
    const f=ex.final||{};
    if(f.type==='awaiting_approval'){
      const words=(f.draft||'').match(/\\S+\\s*/g)||[];
      for(const w of words){await sleep(12);c.enqueue(frame({type:'draft_token',text:w}));}
      await sleep(150);c.enqueue(frame(f));
    }else{await sleep(200);c.enqueue(frame(f));}
    c.enqueue(frame({type:'done'}));c.close();
  }});
  return new Response(stream,{headers:{'Content-Type':'text/event-stream'}});
}
</script>
"""

shim = SHIM.replace("__DEMO__", json.dumps(DEMO))
html = APP.replace("<head>", "<head>\n" + shim, 1)
html = html.replace('<div class="app">', BANNER + '<div class="app">', 1)

open("docs/index.html", "w", encoding="utf-8").write(html)
open("docs/.nojekyll", "w").write("")
print("wrote docs/index.html (", len(html), "bytes )")
