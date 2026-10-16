import os
import json
import time
import ssl
import hashlib
import re
import urllib.request
import urllib.parse
import threading
import sqlite3
from typing import Optional, Tuple, List, Dict, Any

DB_PATH = os.environ.get("GEMINI_POOL_DB", "/app/data/gemini_pool.db")
DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"

class GeminiAccountPool:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.lock = threading.Lock()
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                label TEXT,
                cookie_raw TEXT NOT NULL,
                sapisid TEXT,
                xsrf_token TEXT,
                gemini_bl TEXT DEFAULT 'boq_gemini-web-uiserver_20261014.17_p0',
                auth_user TEXT DEFAULT '0',
                is_active BOOLEAN NOT NULL DEFAULT 1,
                last_used_at REAL DEFAULT 0,
                last_keepalive_at REAL DEFAULT 0,
                status TEXT DEFAULT 'active',
                error_message TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            """)
            conn.commit()

    @staticmethod
    def parse_cookie_str(raw: str) -> Tuple[Dict[str, str], Optional[str]]:
        raw = raw.strip()
        pairs = {}
        # Support newline separated or semicolon separated
        items = re.split(r'[;\n]+', raw)
        for item in items:
            item = item.strip()
            if "=" in item:
                k, v = item.split("=", 1)
                pairs[k.strip()] = v.strip()
            elif ":" in item:
                k, v = item.split(":", 1)
                pairs[k.strip()] = v.strip()

        sapisid = pairs.get("SAPISID") or pairs.get("__Secure-3PAPISID") or pairs.get("__Secure-1PAPISID")
        
        # If user pasted raw SAPISID token alone
        if not sapisid and len(raw) >= 15 and not any(sep in raw for sep in [";", " ", "\n", "="]):
            sapisid = raw
            pairs["SAPISID"] = raw

        return pairs, sapisid

    @staticmethod
    def make_sapisidhash(sapisid: str) -> str:
        ts = int(time.time())
        h = hashlib.sha1(f"{ts} {sapisid} https://gemini.google.com".encode()).hexdigest()
        return f"SAPISIDHASH {ts}_{h}"

    def upsert_account(self, email: str, cookie_raw: str, label: str = "", auth_user: str = "0") -> Dict[str, Any]:
        cookie_raw = cookie_raw.strip()
        pairs, sapisid = self.parse_cookie_str(cookie_raw)
        if not sapisid:
            raise ValueError("Cookie tidak memiliki SAPISID atau __Secure-3PAPISID valid.")

        now = time.time()
        # Probe Google to extract fresh SNlM0e (XSRF) and cfb2h (gemini_bl)
        xsrf, bl, updated_cookie = self.refresh_account_session(cookie_raw, sapisid, auth_user)

        with self.lock:
            with self._get_conn() as conn:
                conn.execute("""
                INSERT INTO accounts (email, label, cookie_raw, sapisid, xsrf_token, gemini_bl, auth_user, is_active, last_keepalive_at, status, error_message, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, 'active', NULL, ?, ?)
                ON CONFLICT(email) DO UPDATE SET
                    label = excluded.label,
                    cookie_raw = excluded.cookie_raw,
                    sapisid = excluded.sapisid,
                    xsrf_token = coalesce(excluded.xsrf_token, accounts.xsrf_token),
                    gemini_bl = coalesce(excluded.gemini_bl, accounts.gemini_bl),
                    auth_user = excluded.auth_user,
                    is_active = 1,
                    last_keepalive_at = excluded.last_keepalive_at,
                    status = 'active',
                    error_message = NULL,
                    updated_at = excluded.updated_at
                """, (email, label or email, updated_cookie, sapisid, xsrf, bl, auth_user, now, now, now))
                conn.commit()

        return {"email": email, "label": label or email, "status": "active", "has_xsrf": bool(xsrf)}

    def refresh_account_session(self, cookie_raw: str, sapisid: str, auth_user: str = "0") -> Tuple[Optional[str], Optional[str], str]:
        """Probes https://gemini.google.com/app, harvests Set-Cookie updates, and extracts SNlM0e & cfb2h."""
        ts = int(time.time())
        h = hashlib.sha1(f"{ts} {sapisid} https://gemini.google.com".encode()).hexdigest()
        auth_hdr = f"SAPISIDHASH {ts}_{h}"
        
        account_prefix = f"/u/{auth_user}" if (auth_user and auth_user != "0") else ""
        headers = {
            "User-Agent": DEFAULT_UA,
            "Cookie": cookie_raw,
            "Authorization": auth_hdr,
            "X-Same-Domain": "1",
        }
        if auth_user and auth_user != "0":
            headers["X-Goog-AuthUser"] = str(auth_user)

        ctx = ssl.create_default_context()
        req = urllib.request.Request(f"https://gemini.google.com{account_prefix}/app", headers=headers)
        
        cookie_dict, _ = self.parse_cookie_str(cookie_raw)
        xsrf = None
        bl = None

        try:
            with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
                set_cookies = resp.headers.get_all("Set-Cookie") or []
                for sc in set_cookies:
                    part = sc.split(";")[0].strip()
                    if "=" in part:
                        k, v = part.split("=", 1)
                        cookie_dict[k] = v
                
                html = resp.read().decode("utf-8", errors="ignore")
                m_xsrf = re.search(r'"SNlM0e":"([^"]+)"', html)
                if m_xsrf:
                    xsrf = m_xsrf.group(1)
                m_bl = re.search(r'"cfb2h":"([^"]+)"', html)
                if m_bl:
                    bl = m_bl.group(1)
        except Exception:
            pass

        updated_cookie_str = "; ".join(f"{k}={v}" for k, v in cookie_dict.items())
        return xsrf, bl, updated_cookie_str

    def get_accounts(self) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT id, email, label, auth_user, is_active, last_used_at, last_keepalive_at, status, error_message, created_at, updated_at FROM accounts ORDER BY id ASC").fetchall()
            return [dict(r) for r in rows]

    def update_account_cookie(self, email: str, new_cookie_raw: str) -> Dict[str, Any]:
        new_cookie_raw = new_cookie_raw.strip()
        pairs, sapisid = self.parse_cookie_str(new_cookie_raw)
        if not sapisid:
            raise ValueError("Cookie tidak memiliki SAPISID atau __Secure-3PAPISID valid.")

        # Find existing auth_user if present
        auth_user = "0"
        with self._get_conn() as conn:
            row = conn.execute("SELECT auth_user FROM accounts WHERE email = ?", (email,)).fetchone()
            if row and row["auth_user"]:
                auth_user = row["auth_user"]

        xsrf, bl, updated_cookie = self.refresh_account_session(new_cookie_raw, sapisid, auth_user)
        now = time.time()

        with self.lock:
            with self._get_conn() as conn:
                conn.execute("""
                UPDATE accounts SET
                    cookie_raw = ?,
                    sapisid = ?,
                    xsrf_token = coalesce(?, xsrf_token),
                    gemini_bl = coalesce(?, gemini_bl),
                    is_active = 1,
                    status = 'active',
                    error_message = NULL,
                    last_keepalive_at = ?,
                    updated_at = ?
                WHERE email = ?
                """, (updated_cookie, sapisid, xsrf, bl, now, now, email))
                conn.commit()

        return {"email": email, "status": "active", "has_xsrf": bool(xsrf)}

    def delete_account(self, email: str):
        with self.lock:
            with self._get_conn() as conn:
                conn.execute("DELETE FROM accounts WHERE email = ?", (email,))
                conn.commit()

    def set_active(self, email: str, is_active: bool):
        with self.lock:
            with self._get_conn() as conn:
                conn.execute("UPDATE accounts SET is_active = ?, updated_at = ? WHERE email = ?", (1 if is_active else 0, time.time(), email))
                conn.commit()

    def select_next_account(self) -> Optional[Dict[str, Any]]:
        """Least Recently Used (LRU) load balancing across active & healthy accounts."""
        with self.lock:
            with self._get_conn() as conn:
                row = conn.execute("""
                SELECT * FROM accounts 
                WHERE is_active = 1 AND status = 'active'
                ORDER BY last_used_at ASC LIMIT 1
                """).fetchone()
                if row:
                    acct = dict(row)
                    now = time.time()
                    conn.execute("UPDATE accounts SET last_used_at = ? WHERE id = ?", (now, acct["id"]))
                    conn.commit()
                    return acct
        return None

    def mark_account_failed(self, account_id: int, error_msg: str):
        with self.lock:
            with self._get_conn() as conn:
                conn.execute("""
                UPDATE accounts SET status = 'error', error_message = ?, updated_at = ?
                WHERE id = ?
                """, (error_msg[:255], time.time(), account_id))
                conn.commit()

    def run_keepalive_cycle(self):
        """Periodically touches Google Gemini session to keep session cookies active."""
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM accounts WHERE is_active = 1").fetchall()

        for r in rows:
            acct = dict(r)
            try:
                xsrf, bl, updated_cookie = self.refresh_account_session(acct["cookie_raw"], acct["sapisid"], acct["auth_user"])
                now = time.time()
                with self.lock:
                    with self._get_conn() as conn:
                        conn.execute("""
                        UPDATE accounts SET
                            cookie_raw = ?,
                            xsrf_token = coalesce(?, xsrf_token),
                            gemini_bl = coalesce(?, gemini_bl),
                            last_keepalive_at = ?,
                            status = 'active',
                            error_message = NULL,
                            updated_at = ?
                        WHERE id = ?
                        """, (updated_cookie, xsrf, bl, now, now, acct["id"]))
                        conn.commit()
            except Exception:
                pass
