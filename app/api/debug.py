from collections import deque
from datetime import datetime
from threading import Lock
from time import perf_counter
from typing import Optional
from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import HTMLResponse
from starlette.middleware.base import BaseHTTPMiddleware
from app.utils.auth import verify_web_password
from app.utils.logging import log_manager, vertex_log_manager
import app.config.settings as settings

debug_router = APIRouter(tags=["debug-center"])

class EventBuffer:
    def __init__(self, maxlen=300):
        self.items = deque(maxlen=maxlen)
        self.lock = Lock()
    def add(self, item):
        with self.lock:
            self.items.append(item)
    def recent(self, count=100):
        with self.lock:
            return list(self.items)[-count:]
    def clear(self):
        with self.lock:
            self.items.clear()

request_events = EventBuffer()

class DebugTraceMiddleware(BaseHTTPMiddleware):
    """Track chat request metadata only; never inspect body or headers."""
    async def dispatch(self, request, call_next):
        path = request.url.path
        if request.method.upper() != "POST" or "chat/completions" not in path.rstrip("/"):
            return await call_next(request)
        started = perf_counter()
        status_code, error = 500, None
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception as exc:
            error = (type(exc).__name__ + ": " + str(exc))[:1200]
            raise
        finally:
            request_events.add({
                "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
                "method": request.method, "path": path, "status_code": status_code,
                "duration_ms": round((perf_counter() - started) * 1000, 2), "error": error,
            })

def require_password(password: Optional[str]):
    if not password or not verify_web_password(password):
        raise HTTPException(status_code=401, detail="调试中心密码错误或未提供")

@debug_router.get("/debug", response_class=HTMLResponse, include_in_schema=False)
async def debug_page():
    return HTMLResponse(PAGE)

@debug_router.get("/api/debug/status")
async def debug_status(x_debug_password: Optional[str] = Header(None)):
    require_password(x_debug_password)
    from app.api.dashboard import credential_manager, active_requests_manager, key_manager
    try:
        credentials = credential_manager.get_total_credentials() if credential_manager else 0
    except Exception:
        credentials = 0
    try:
        active = len(active_requests_manager.active_requests) if active_requests_manager else 0
    except Exception:
        active = 0
    return {
        "service": "Hajimi Gemini API Proxy", "vertex_enabled": bool(settings.ENABLE_VERTEX),
        "vertex_express_enabled": bool(settings.ENABLE_VERTEX_EXPRESS),
        "aistudio_key_count": len(key_manager.api_keys) if key_manager else 0,
        "vertex_credential_count": credentials, "active_request_count": active,
        "tracked_requests": len(request_events.recent(300)),
        "local_time": datetime.now().astimezone().isoformat(timespec="seconds"),
    }

@debug_router.get("/api/debug/logs")
async def debug_logs(x_debug_password: Optional[str] = Header(None),
                     limit: int = Query(200, ge=1, le=500),
                     source: str = Query("all", regex="^(all|aistudio|vertex)$"),
                     level: str = Query("all", regex="^(all|INFO|WARNING|ERROR|DEBUG)$")):
    require_password(x_debug_password)
    rows = []
    if source != "vertex":
        rows.extend({**x, "source": "aistudio"} for x in log_manager.get_recent_logs(500))
    if source != "aistudio":
        rows.extend({**x, "source": "vertex"} for x in vertex_log_manager.get_recent_logs(500))
    rows.sort(key=lambda x: x.get("timestamp", ""))
    if level != "all":
        rows = [x for x in rows if str(x.get("level", "")).upper() == level]
    return {"logs": rows[-limit:], "total": len(rows)}

@debug_router.get("/api/debug/requests")
async def debug_requests(x_debug_password: Optional[str] = Header(None),
                         limit: int = Query(100, ge=1, le=300)):
    require_password(x_debug_password)
    return {"requests": request_events.recent(limit)}

@debug_router.post("/api/debug/clear")
async def debug_clear(x_debug_password: Optional[str] = Header(None)):
    require_password(x_debug_password)
    with log_manager.lock:
        log_manager.logs.clear()
    with vertex_log_manager.lock:
        vertex_log_manager.logs.clear()
    request_events.clear()
    return {"status": "success", "message": "调试日志和请求记录已清空"}

PAGE = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Hajimi 调试中心</title>
<style>
:root{color-scheme:dark;--p:#121a2d;--l:#293751;--t:#e7edf8;--m:#91a0b9}*{box-sizing:border-box}body{margin:0;background:#0b1020;color:var(--t);font:14px/1.55 system-ui,sans-serif}header{padding:20px max(16px,calc((100vw - 1100px)/2));border-bottom:1px solid var(--l)}main{max-width:1100px;margin:20px auto;padding:0 14px}h1{font-size:22px;margin:0}.muted,small{color:var(--m)}.panel,.card{background:var(--p);border:1px solid var(--l);border-radius:12px;padding:14px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:14px 0}.metric{font-size:23px;font-weight:bold}.row,nav{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:12px 0}button,input,select,textarea{border:1px solid #394c6b;border-radius:8px;padding:9px;background:#0b1425;color:var(--t);font:inherit}button{cursor:pointer;background:#1b2942}button.active,button.primary{background:#24477c}input,textarea{width:100%}textarea{min-height:80px}label{display:block;color:var(--m);margin:8px 0 4px}table{border-collapse:collapse;width:100%;min-width:650px}td,th{text-align:left;padding:8px;border-bottom:1px solid var(--l);vertical-align:top}th{background:#17243a}.wrap{overflow:auto;max-height:55vh;border:1px solid var(--l)}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#09111f;padding:12px;border-radius:8px;max-height:45vh;overflow:auto}.hidden{display:none!important}.login{max-width:420px;margin:10vh auto}.err{color:#ff8585}.hint{font-size:12px;color:var(--m)}.right{margin-left:auto}
</style></head><body><header><h1>🛠 Hajimi 调试中心</h1><small>请求追踪 · Vertex / AI Studio 日志 · 在线接口测试</small></header><main>
<section id="login" class="panel login"><h2>管理验证</h2><p class="muted">请输入网页配置密码（WEB_PASSWORD）。</p><input id="pw" type="password" placeholder="网页配置密码"><p><button class="primary" id="loginBtn">进入调试中心</button></p><div id="loginErr" class="err"></div></section>
<section id="app" class="hidden"><div class="cards" id="metrics"></div><nav><button class="tab active" data-id="requests">请求追踪</button><button class="tab" data-id="logs">实时日志</button><button class="tab" data-id="test">在线测试</button><button class="tab" data-id="system">运行状态</button><button id="logout" class="right">退出</button></nav>
<section id="requests" class="panel"><div class="row"><h2>请求追踪</h2><button onclick="loadRequests()">刷新</button></div><p class="hint">只记录路径、状态码和耗时，不读取请求正文、API Key 或授权头。</p><div class="wrap"><table><thead><tr><th>时间</th><th>方法</th><th>路径</th><th>状态</th><th>耗时</th><th>异常</th></tr></thead><tbody id="reqRows"></tbody></table></div></section>
<section id="logs" class="panel hidden"><div class="row"><h2>运行日志</h2><select id="source"><option value="all">全部来源</option><option value="vertex">Vertex</option><option value="aistudio">AI Studio</option></select><select id="level"><option value="all">全部级别</option><option>ERROR</option><option>WARNING</option><option>INFO</option></select><button onclick="loadLogs()">刷新</button><button id="clear">清空记录</button></div><div class="wrap"><table><thead><tr><th>时间</th><th>来源</th><th>级别</th><th>操作</th><th>信息</th><th>错误详情</th></tr></thead><tbody id="logRows"></tbody></table></div></section>
<section id="test" class="panel hidden"><h2>接口在线测试</h2><p class="hint">会真实调用上游模型并消耗配额。API 密码仅用于本次请求，不会保存。</p><div class="row"><div style="flex:1"><label>模式</label><select id="mode"><option value="vertex">Vertex</option><option value="aistudio">AI Studio</option></select></div><div style="flex:2"><label>模型名称</label><input id="model" placeholder="例如 gemini-2.5-pro"></div></div><label>API 访问密码（PASSWORD）</label><input id="apiPass" type="password" autocomplete="off"><label>测试提示词</label><textarea id="prompt">请用一句话回复：Hajimi 调试中心连接正常。</textarea><p><button class="primary" id="testBtn">发送测试请求</button> <span id="testStatus" class="muted"></span></p><pre id="testResult">测试结果显示在这里。</pre></section>
<section id="system" class="panel hidden"><h2>运行状态</h2><pre id="sys"></pre></section></section></main>
<script>
let pw=sessionStorage.getItem("hajimi_dbg_pw")||"";const $=id=>document.getElementById(id);const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
async function api(path,opt={}){let r=await fetch(path,{...opt,headers:{"X-Debug-Password":pw,...(opt.headers||{})}});if(r.status===401)throw Error("密码验证失败，请重新登录");if(!r.ok)throw Error("HTTP "+r.status+" "+await r.text());return r.json()}
function show(){ $("login").classList.add("hidden");$("app").classList.remove("hidden");refresh()}
function login(){pw=$("pw").value;api("/api/debug/status").then(()=>{sessionStorage.setItem("hajimi_dbg_pw",pw);$("loginErr").textContent="";show()}).catch(e=>$("loginErr").textContent=e.message)}
$("loginBtn").onclick=login;$("pw").onkeydown=e=>{if(e.key==="Enter")login()};$("logout").onclick=()=>{pw="";sessionStorage.removeItem("hajimi_dbg_pw");$("app").classList.add("hidden");$("login").classList.remove("hidden")};
document.querySelectorAll(".tab").forEach(b=>b.onclick=()=>{document.querySelectorAll(".tab").forEach(x=>x.classList.toggle("active",x===b));["requests","logs","test","system"].forEach(id=>$(id).classList.toggle("hidden",id!==b.dataset.id));if(b.dataset.id==="requests")loadRequests();if(b.dataset.id==="logs")loadLogs();if(b.dataset.id==="system")loadStatus()});
async function loadStatus(){let d=await api("/api/debug/status");$("metrics").innerHTML=[["Vertex",d.vertex_enabled?"已启用":"未启用"],["AI Studio 有效密钥",d.aistudio_key_count],["Vertex 凭证",d.vertex_credential_count],["活跃请求",d.active_request_count]].map(x=>'<div class="card"><small>'+x[0]+'</small><div class="metric">'+esc(x[1])+'</div></div>').join("");$("sys").textContent=JSON.stringify(d,null,2)}
async function loadRequests(){let d=await api("/api/debug/requests?limit=300");$("reqRows").innerHTML=d.requests.slice().reverse().map(x=>'<tr><td>'+esc(x.timestamp)+'</td><td>'+esc(x.method)+'</td><td>'+esc(x.path)+'</td><td>'+esc(x.status_code)+'</td><td>'+esc(x.duration_ms)+' ms</td><td class="err">'+esc(x.error||"")+'</td></tr>').join("")||'<tr><td colspan="6">暂无请求</td></tr>'}
async function loadLogs(){let q=new URLSearchParams({limit:"500",source:$("source").value,level:$("level").value}),d=await api("/api/debug/logs?"+q);$("logRows").innerHTML=d.logs.slice().reverse().map(x=>'<tr><td>'+esc(x.timestamp)+'</td><td>'+esc(x.source)+'</td><td>'+esc(x.level)+'</td><td>'+esc(x.operation||x.request_type||"")+'</td><td>'+esc(x.message||x.formatted||"")+'</td><td class="err">'+esc(x.error_message||"")+'</td></tr>').join("")||'<tr><td colspan="6">暂无日志</td></tr>'}
$("source").onchange=loadLogs;$("level").onchange=loadLogs;$("clear").onclick=async()=>{if(confirm("确定清空当前进程内的日志和请求记录？")){await api("/api/debug/clear",{method:"POST"});refresh()}};
$("testBtn").onclick=async()=>{let mode=$("mode").value,model=$("model").value.trim(),key=$("apiPass").value,prompt=$("prompt").value;if(!model||!key||!prompt){$("testStatus").textContent="请填写模型、API 密码和提示词";return}let b=$("testBtn");b.disabled=true;$("testStatus").textContent="请求中…";let t=performance.now();try{let r=await fetch("/"+mode+"/chat/completions",{method:"POST",headers:{"Authorization":"Bearer "+key,"Content-Type":"application/json"},body:JSON.stringify({model,messages:[{role:"user",content:prompt}],stream:false})}),raw=await r.text(),body;try{body=JSON.parse(raw)}catch{body=raw}$("testResult").textContent=JSON.stringify({http_status:r.status,duration_ms:Math.round(performance.now()-t),response:body},null,2);$("testStatus").textContent=r.ok?"测试成功":"测试失败（HTTP "+r.status+"）";await loadLogs();await loadRequests()}catch(e){$("testStatus").textContent="连接失败";$("testResult").textContent=e.stack||e.message}finally{b.disabled=false}};
async function refresh(){try{await loadStatus();await loadRequests();await loadLogs()}catch(e){if(e.message.includes("密码")){$("app").classList.add("hidden");$("login").classList.remove("hidden")}}}
if(pw)api("/api/debug/status").then(show).catch(()=>{pw="";sessionStorage.removeItem("hajimi_dbg_pw")});
setInterval(()=>{if(pw&&!$("app").classList.contains("hidden")){let tab=document.querySelector(".tab.active")?.dataset.id;if(tab==="requests")loadRequests().catch(()=>{});if(tab==="logs")loadLogs().catch(()=>{});loadStatus().catch(()=>{})}},3000);
</script></body></html>"""
