import json
import time
import os
import re
import uuid
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import urllib.parse
import httpx

from gemini_web2api.config import CONFIG
from gemini_web2api.models import MODELS, resolve_model
from gemini_web2api.gemini import (
    _build_payload, _get_url, _get_ssl_ctx,
    clean_text, _extract_texts_from_line, extract_response_text,
    log, HAS_HTTPX
)
from gemini_web2api.tools import (
    messages_to_prompt, parse_tool_calls,
    google_contents_to_prompt, parse_google_function_calls
)
from gemini_web2api.multimodal import detect_image_mime, fetch_image_bytes, upload_image
from pool_manager import GeminiAccountPool, DEFAULT_UA

pool = GeminiAccountPool()

# Background Keep-Alive Daemon
def keepalive_worker():
    while True:
        try:
            time.sleep(1800) # Every 30 minutes
            pool.run_keepalive_cycle()
        except Exception:
            pass

t = threading.Thread(target=keepalive_worker, daemon=True)
t.start()

def _usage(prompt: str, text: str) -> dict:
    p = len(prompt) // 4
    c = len(text or "") // 4
    return {"prompt_tokens": p, "completion_tokens": c, "total_tokens": p + c}

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

class PoolGeminiHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, data: dict):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status: int, html_str: str):
        body = html_str.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _check_admin(self) -> bool:
        expected = os.environ.get("ADMIN_PASSWORD", "sk-admin-AU3mT7PFcZ5t2LBfcmKbs")
        auth = self.headers.get("Authorization", "")
        token = auth.replace("Bearer ", "").strip()
        return token == expected

    def _check_api_auth(self) -> bool:
        allowed_keys = CONFIG.get("api_keys", [])
        if not allowed_keys:
            return True
        auth = self.headers.get("Authorization", "")
        token = auth.replace("Bearer ", "").strip()
        return token in allowed_keys or token == os.environ.get("ADMIN_PASSWORD", "")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        
        # UI & Management APIs
        if path == "/" or path == "/index.html":
            static_file = "/app/static/index.html"
            if not os.path.exists(static_file):
                static_file = os.path.join(os.path.dirname(__file__), "static/index.html")
            with open(static_file, "r", encoding="utf-8") as f:
                return self._send_html(200, f.read())

        if path == "/api/accounts/update-cookie":
            if not self._check_admin():
                return self._send_json(401, {"error": "Unauthorized"})
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            email = body.get("email")
            cookie = body.get("cookie")
            if not email or not cookie:
                return self._send_json(400, {"success": False, "error": "Email dan Cookie wajib diisi"})
            try:
                res = pool.update_account_cookie(email, cookie)
                return self._send_json(200, {"success": True, "account": res})
            except Exception as e:
                return self._send_json(400, {"success": False, "error": str(e)})

        if path == "/api/accounts":
            if not self._check_admin():
                return self._send_json(401, {"error": "Unauthorized"})
            return self._send_json(200, {"success": True, "accounts": pool.get_accounts()})

        if path == "/api/health" or path == "/health":
            return self._send_json(200, {"status": "ok", "service": "gemini-web2api-pool"})

        # OpenAI /v1/models
        if path == "/v1/models":
            if not self._check_api_auth():
                return self._send_json(401, {"error": {"message": "Invalid API key"}})
            models_data = []
            for name, meta in MODELS.items():
                models_data.append({
                    "id": name,
                    "object": "model",
                    "created": 1792137000,
                    "owned_by": "google-web",
                    "description": meta.get("desc", "")
                })
            return self._send_json(200, {"object": "list", "data": models_data})

        self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        path = self.path.split("?")[0]

        # Admin Actions
        if path == "/api/auth/verify":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            if body.get("password") == os.environ.get("ADMIN_PASSWORD", "sk-admin-AU3mT7PFcZ5t2LBfcmKbs"):
                return self._send_json(200, {"success": True, "token": os.environ.get("ADMIN_PASSWORD")})
            return self._send_json(401, {"success": False, "error": "Invalid password"})

        if path == "/api/accounts/update-cookie":
            if not self._check_admin():
                return self._send_json(401, {"error": "Unauthorized"})
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            email = body.get("email")
            cookie = body.get("cookie")
            if not email or not cookie:
                return self._send_json(400, {"success": False, "error": "Email dan Cookie wajib diisi"})
            try:
                res = pool.update_account_cookie(email, cookie)
                return self._send_json(200, {"success": True, "account": res})
            except Exception as e:
                return self._send_json(400, {"success": False, "error": str(e)})

        if path == "/api/accounts":
            if not self._check_admin():
                return self._send_json(401, {"error": "Unauthorized"})
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            try:
                res = pool.upsert_account(
                    email=body["email"],
                    cookie_raw=body["cookie"],
                    label=body.get("label", ""),
                    auth_user=str(body.get("auth_user", "0"))
                )
                return self._send_json(200, {"success": True, "account": res})
            except Exception as e:
                return self._send_json(400, {"success": False, "error": str(e)})

        if path == "/api/accounts/delete":
            if not self._check_admin():
                return self._send_json(401, {"error": "Unauthorized"})
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            pool.delete_account(body.get("email", ""))
            return self._send_json(200, {"success": True})

        if path == "/api/accounts/toggle":
            if not self._check_admin():
                return self._send_json(401, {"error": "Unauthorized"})
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            pool.set_active(body.get("email", ""), body.get("is_active", True))
            return self._send_json(200, {"success": True})

        if path == "/api/accounts/keepalive-now":
            if not self._check_admin():
                return self._send_json(401, {"error": "Unauthorized"})
            threading.Thread(target=pool.run_keepalive_cycle, daemon=True).start()
            return self._send_json(200, {"success": True, "message": "Keepalive cycle started in background"})

        # OpenAI /v1/chat/completions
        if path == "/v1/chat/completions":
            if not self._check_api_auth():
                return self._send_json(401, {"error": {"message": "Invalid API key"}})
            
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            return self._handle_chat_completions(body)

        self._send_json(404, {"error": "Not found"})

    def _execute_gemini_request(self, acct: dict, prompt: str, model_id: int, think_mode: int, stream: bool, extra_fields: dict = None, jspb_header: str = None):
        cookie_raw = acct["cookie_raw"]
        sapisid = acct["sapisid"]
        auth_user = acct["auth_user"]
        xsrf = acct.get("xsrf_token") or CONFIG.get("xsrf_token", "")
        bl = acct.get("gemini_bl") or CONFIG.get("gemini_bl", "boq_gemini-web-uiserver_20261014.17_p0")

        account_prefix = f"/u/{auth_user}" if (auth_user and auth_user != "0") else ""
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://gemini.google.com",
            "Referer": f"https://gemini.google.com{account_prefix}/app",
            "X-Same-Domain": "1",
            "User-Agent": DEFAULT_UA,
            "Cookie": cookie_raw,
            "Authorization": GeminiAccountPool.make_sapisidhash(sapisid)
        }
        if auth_user and auth_user != "0":
            headers["X-Goog-AuthUser"] = str(auth_user)
        if jspb_header:
            headers["x-goog-ext-525001261-jspb"] = jspb_header

        # Build payload
        inner = [None] * 102
        inner[0] = [prompt, 0, None, None, None, None, 0]
        inner[1] = ["en"]
        inner[2] = ["", "", "", None, None, None, None, None, None, ""]
        inner[6] = [0]
        inner[7] = 1
        inner[10] = 1
        inner[11] = 0
        inner[17] = [[think_mode]]
        inner[18] = 0
        inner[27] = 1
        inner[30] = [4]
        inner[41] = [1] if CONFIG.get("temporary_chats", True) else [2]
        if CONFIG.get("temporary_chats", True):
            inner[45] = 1
        inner[53] = 0
        inner[59] = str(uuid.uuid4())
        inner[61] = []
        inner[68] = 1
        inner[79] = model_id
        if extra_fields:
            for k, v in extra_fields.items():
                inner[k] = v

        outer = [None, json.dumps(inner)]
        params = {"f.req": json.dumps(outer)}
        if xsrf:
            params["at"] = xsrf
        body_data = urllib.parse.urlencode(params)

        reqid = int(time.time()) % 1000000
        url = (
            f"https://gemini.google.com{account_prefix}/_/BardChatUi/data/"
            "assistant.lamda.BardFrontendService/StreamGenerate"
            f"?bl={bl}&hl=en&_reqid={reqid}&rt=c"
        )

        return url, headers, body_data

    def _handle_chat_completions(self, body: dict):
        model_name = body.get("model", "gemini-4-argon")
        messages = body.get("messages", [])
        stream = body.get("stream", False)
        tools = body.get("tools")
        tool_choice = body.get("tool_choice")

        prompt, _ = messages_to_prompt(messages, tools, tool_choice)
        res_tuple = resolve_model(model_name)
        resolved_name = res_tuple[0]
        model_id = res_tuple[1]
        think_mode = res_tuple[2]
        extra_fields = res_tuple[4] if len(res_tuple) > 4 else None
        jspb_header = res_tuple[5] if len(res_tuple) > 5 else None

        # Select Account via Load Balancer
        acct = pool.select_next_account()
        if not acct:
            return self._send_json(503, {
                "error": {
                    "message": "Tidak ada akun Google aktif di pool. Silakan tambahkan cookie di WebUI.",
                    "type": "pool_exhausted"
                }
            })

        url, headers, payload = self._execute_gemini_request(acct, prompt, model_id, think_mode, stream, extra_fields, jspb_header)

        if not stream:
            try:
                with httpx.Client(timeout=CONFIG.get("request_timeout_sec", 180), verify=True) as client:
                    resp = client.post(url, content=payload.encode("utf-8"), headers=headers)
                    if resp.status_code != 200:
                        pool.mark_account_failed(acct["id"], f"HTTP {resp.status_code}")
                        return self._send_json(502, {"error": {"message": f"Google upstream returned {resp.status_code}"}})
                    
                    raw_text = resp.text
                    answer = extract_response_text(raw_text)
                    
                    tool_calls = None
                    finish_reason = "stop"
                    if tools and answer and tool_choice != "none":
                        clean_answer, tool_calls = parse_tool_calls(answer)
                        if tool_calls:
                            answer = clean_answer or None
                            finish_reason = "tool_calls"

                    msg = {"role": "assistant", "content": answer}
                    if tool_calls:
                        msg["tool_calls"] = tool_calls

                    return self._send_json(200, {
                        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
                        "object": "chat.completion",
                        "created": int(time.time()),
                        "model": model_name,
                        "choices": [{
                            "index": 0,
                            "message": msg,
                            "finish_reason": finish_reason
                        }],
                        "usage": _usage(prompt, str(answer or ""))
                    })
            except Exception as e:
                pool.mark_account_failed(acct["id"], str(e))
                return self._send_json(500, {"error": {"message": str(e)}})

        # Streaming SSE
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        cmpl_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        created = int(time.time())

        # Initial chunk
        first_chunk = {
            "id": cmpl_id, "object": "chat.completion.chunk", "created": created, "model": model_name,
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]
        }
        self.wfile.write(f"data: {json.dumps(first_chunk)}\n\n".encode())
        self.wfile.flush()

        try:
            with httpx.Client(timeout=CONFIG.get("request_timeout_sec", 180), verify=True) as client:
                with client.stream("POST", url, content=payload.encode("utf-8"), headers=headers) as resp:
                    if resp.status_code != 200:
                        pool.mark_account_failed(acct["id"], f"Stream HTTP {resp.status_code}")
                        err_chunk = {"error": f"Upstream error {resp.status_code}"}
                        self.wfile.write(f"data: {json.dumps(err_chunk)}\n\n".encode())
                        self.wfile.flush()
                        return

                    emitted_raw_text = ""
                    buf = ""
                    for chunk in resp.iter_text():
                        buf += chunk
                        if "BardErrorInfo" in buf:
                            bard_err = re.search(r'BardErrorInfo\s*\[(\d+)\]', buf)
                            if bard_err:
                                raise RuntimeError(f"Gemini upstream rejected request: BardErrorInfo [{bard_err.group(1)}]")
                        while "\n" in buf:
                            line, buf = buf.split("\n", 1)
                            for t in _extract_texts_from_line(line):
                                if t == emitted_raw_text or emitted_raw_text.startswith(t):
                                    continue
                                if not t.startswith(emitted_raw_text):
                                    continue
                                delta = clean_text(t[len(emitted_raw_text):], strip=False)
                                emitted_raw_text = t
                                if delta:
                                    chunk_payload = {
                                        "id": cmpl_id, "object": "chat.completion.chunk", "created": created, "model": model_name,
                                        "choices": [{"index": 0, "delta": {"content": delta}, "finish_reason": None}]
                                    }
                                    self.wfile.write(f"data: {json.dumps(chunk_payload, ensure_ascii=False)}\n\n".encode())
                                    self.wfile.flush()

            # Final chunk: check if tool_calls need to be emitted
            tool_calls = None
            finish_reason = "stop"
            if tools and emitted_raw_text and tool_choice != "none":
                clean_t, tool_calls = parse_tool_calls(emitted_raw_text)
                if tool_calls:
                    finish_reason = "tool_calls"
                    tc_chunk = {
                        "id": cmpl_id, "object": "chat.completion.chunk", "created": created, "model": model_name,
                        "choices": [{"index": 0, "delta": {"tool_calls": tool_calls}, "finish_reason": None}]
                    }
                    self.wfile.write(f"data: {json.dumps(tc_chunk, ensure_ascii=False)}\n\n".encode())
                    self.wfile.flush()

            stop_chunk = {
                "id": cmpl_id, "object": "chat.completion.chunk", "created": created, "model": model_name,
                "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}]
            }
            self.wfile.write(f"data: {json.dumps(stop_chunk)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            if "Broken pipe" not in str(e):
                pool.mark_account_failed(acct["id"], str(e))
        finally:
            self.close_connection = True

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8095))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"Starting Gemini Web2API Pool Gateway on {host}:{port}...")
    server = ThreadedHTTPServer((host, port), PoolGeminiHandler)
    server.serve_forever()
