#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
px_comment.py —— 给作品写评语（本地记账 + 可选真发到 Pixiv 评论区）
============================================================================
口径：
  · 默认**只存本地**：追加到 `<home>/comments.jsonl`，不发任何网络请求。
  · 只有设置里同时打开 `autoComment` 与 `commentPost`、并且调用时传了
    `post=True`，才会真的 POST 到 pixiv 的 web 接口 —— 那是公开评论，
    作者能看到、撤不回来，所以默认关、并且受 `commentMaxPerDay` 限流。
  · 发不出去不抛异常：返回 `{ok:true, posted:false, postError:"..."}`，
    本地那条照样留着，回头可以人工补发。
  · web 接口要的是**网页登录态**（credential.json 里的 webCookie），
    不是 App API 的 refresh_token —— 两者不是一回事。
============================================================================
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

import requests

HOME = Path(os.environ.get("PIXIV_DUTY_HOME") or Path(__file__).parent)
CRED_FILE = Path(os.environ.get("PIXIV_CREDENTIAL_FILE") or (HOME / "credential.json"))
CONFIG_FILE = HOME / "config.json"
COMMENTS_FILE = HOME / "comments.jsonl"

WEB_ADD = "https://www.pixiv.net/ajax/illusts/comments/add"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
MAX_LEN = 400


def _log(msg: str) -> None:
    try:
        line = f"[{datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}] [comment] {msg}\n"
        with open(HOME / "duty.log", "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def _read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _cfg() -> dict:
    return _read_json(CONFIG_FILE, {}) or {}


def _cred() -> dict:
    return _read_json(CRED_FILE, {}) or {}


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _entries(posted_only: bool = False) -> list:
    out = []
    try:
        for line in COMMENTS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if posted_only and not e.get("posted"):
                continue
            out.append(e)
    except Exception:
        pass
    return out


def _append(entry: dict) -> None:
    try:
        COMMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(COMMENTS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        _log(f"写 comments.jsonl 失败：{e}")


def _post_web(pid: int, text: str) -> dict:
    """真发到 web 评论区：需要 PHPSESSID 那套 cookie。"""
    cookie_map = _cred().get("webCookie") or {}
    sessid = cookie_map.get("PHPSESSID")
    if not sessid:
        return {"ok": False, "message": "没有网页登录态（webCookie.PHPSESSID 缺失）——只能存本地；请先在设置里重新登录一次"}
    cookie = "; ".join(f"{k}={v}" for k, v in cookie_map.items() if v)
    headers = {
        "User-Agent": UA,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Referer": f"https://www.pixiv.net/artworks/{pid}",
        "Origin": "https://www.pixiv.net",
        "Cookie": cookie,
        "Accept-Language": "zh-CN,zh;q=0.9,ja;q=0.8",
    }
    body = {"illust_id": str(pid), "comment": text, "comment_parent_id": None}
    try:
        r = requests.post(WEB_ADD, json=body, headers=headers, timeout=25)
    except Exception as e:
        return {"ok": False, "message": f"{type(e).__name__}: {str(e)[:180]}"}
    raw = ""
    data = None
    try:
        data = r.json()
        raw = json.dumps(data, ensure_ascii=False)[:300]
    except Exception:
        raw = (r.text or "")[:300]
    ok = r.status_code == 200 and isinstance(data, dict) and data.get("error") is False
    msg = None
    if not ok:
        if isinstance(data, dict):
            msg = str(data.get("message") or "").strip() or f"HTTP {r.status_code}"
        else:
            msg = f"HTTP {r.status_code}"
    return {"ok": ok, "message": msg, "raw": raw, "status": r.status_code}


def submit(id: int, text: str, kind: str = "auto", post: bool = False) -> dict:
    try:
        pid = int(id)
    except Exception:
        return {"ok": False, "code": "BAD_REQUEST", "message": f"id 不是数字：{id}"}

    body = str(text or "").strip()
    if not body:
        return {"ok": False, "code": "BAD_REQUEST", "message": "评语是空的"}
    if len(body) > MAX_LEN:
        body = body[:MAX_LEN]

    cfg = _cfg()
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "date": _today(),
        "id": pid,
        "kind": str(kind or "auto"),
        "text": body,
        "posted": False,
        "postError": None,
    }

    want_post = bool(post) and bool(cfg.get("commentPost"))
    if want_post:
        cap = int(cfg.get("commentMaxPerDay") or 0)
        if cap > 0:
            used = sum(1 for e in _entries(posted_only=True) if e.get("date") == entry["date"])
            if used >= cap:
                want_post = False
                entry["postError"] = f"今天已发 {used} 条，达到上限 {cap}；这条只存本地"
        if want_post:
            r = _post_web(pid, body)
            entry["posted"] = bool(r.get("ok"))
            entry["postError"] = None if r.get("ok") else (r.get("message") or "发送失败")
            entry["postRaw"] = r.get("raw")
            _log(f"{'已发评论' if entry['posted'] else '发评论失败'} id={pid} {entry['postError'] or ''}".strip())
    elif bool(post):
        entry["postError"] = "设置里没打开「真的发出去」，只存本地"

    _append(entry)
    if not entry["posted"]:
        _log(f"本地评语 id={pid} len={len(body)}")

    return {
        "ok": True,
        "id": pid,
        "posted": entry["posted"],
        "postError": entry["postError"],
        "local": True,
        "file": str(COMMENTS_FILE),
        "text": body,
        "todayPosted": sum(1 for e in _entries(posted_only=True) if e.get("date") == entry["date"]),
        "cap": int(cfg.get("commentMaxPerDay") or 0),
    }


def listing(id: int = 0, limit: int = 20) -> dict:
    items = _entries()
    if id:
        try:
            want = int(id)
        except Exception:
            want = 0
        items = [e for e in items if int(e.get("id") or 0) == want]
    items = items[-max(1, min(int(limit or 20), 200)):]
    return {"ok": True, "count": len(items), "items": items, "file": str(COMMENTS_FILE)}
