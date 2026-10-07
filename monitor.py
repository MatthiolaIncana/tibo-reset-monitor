#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import base64
import hashlib
import hmac
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

STATE_FILE = Path("state.json")
SHANGHAI = timezone(timedelta(hours=8))

SOURCES = [
    {
        "name": "Codex Resets",
        "url": "https://codex-resets.com/",
        "max_lines": 240,
    },
    {
        "name": "Resets.today",
        "url": "https://resets.today/",
        "max_lines": 280,
    },
]

SIGNAL_WORDS = (
    "reset",
    "propagated",
    "usage limits",
    "usage limit",
    "banked",
    "vote",
)

EXCLUDE_PATTERNS = [
    r"^reset status$",
    r"^usage reset$",
    r"^reset calendar",
    r"^reset history",
    r"^codex reset history",
    r"^codex reset announcements",
    r"^original announcements$",
    r"^total resets$",
    r"^avg\.?\s*reset",
    r"^average interval$",
    r"^latest codex limit reset",
    r"^latest verified",
    r"^reset watch",
    r"^possible reset within\s+\d+",
    r"^next expected",
    r"^show all .*reset",
    r"^hard resets?$",
    r"^resets?$",
    r"^banked reset$",
    r"^verified banked$",
    r"^we watch @thsottiaux",
    r"^reset intelligence",
    r"^the reset record",
    r"^cadence tracked",
    r"^reset pulse",
]

CONFIRMED_PATTERNS = [
    r"\breset(?:s)? all propagated\b",
    r"\ball reset for everyone\b",
    r"\bhave now reset usage\b",
    r"\breset button pressed\b",
    r"\busage limits? (?:have been|has been|are) reset\b",
    r"\breset confirmed\b",
]

UPCOMING_PATTERNS = [
    r"\bwe(?:'|’)ll reset\b",
    r"\bwe will reset\b",
    r"\bwill reset\b",
    r"\breset(?:ting)? usage limits?\b",
    r"\breset landing\b",
    r"\breset incoming\b",
    r"\bmore resets coming\b",
    r"\bpromised a reset\b",
    r"\breset.*\btomorrow\b",
    r"\breset.*\btoday\b",
    r"\breset.*\bnext week\b",
    r"\bor a reset\b",
    r"\breset for (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
]


def now_cn():
    return datetime.now(SHANGHAI)


def iso_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def stable_id(text: str) -> str:
    normalized = normalize(text).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def load_state():
    if not STATE_FILE.exists():
        return {
            "initialized": False,
            "seen": [],
            "source_status": {},
            "last_keepalive": None,
            "all_fail_count": 0,
            "health_alert_sent": False,
        }
    try:
        data = json.loads(STATE_FILE.read_text("utf-8"))
    except Exception:
        data = {}
    data.setdefault("initialized", False)
    data.setdefault("seen", [])
    data.setdefault("source_status", {})
    data.setdefault("last_keepalive", None)
    data.setdefault("all_fail_count", 0)
    data.setdefault("health_alert_sent", False)
    return data


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def fetch_lines(url: str, max_lines: int):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/154 Safari/537.36 TiboResetMonitor/1.0"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    resp = requests.get(url, headers=headers, timeout=25)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    lines = []
    last = None
    for raw in soup.get_text("\n").splitlines():
        line = normalize(raw)
        if not line:
            continue
        if line == last:
            continue
        lines.append(line)
        last = line
        if len(lines) >= max_lines:
            break
    return lines


def excluded(line: str) -> bool:
    low = line.lower()
    if len(line) < 5 or len(line) > 900:
        return True
    for pat in EXCLUDE_PATTERNS:
        if re.search(pat, low, flags=re.I):
            return True
    return False


def line_is_signal(line: str) -> bool:
    low = line.lower()
    return any(word in low for word in SIGNAL_WORDS) and not excluded(line)


def classify(text: str):
    low = text.lower()
    for pat in CONFIRMED_PATTERNS:
        if re.search(pat, low, flags=re.I):
            return "confirmed", "🟢 已确认重置"
    for pat in UPCOMING_PATTERNS:
        if re.search(pat, low, flags=re.I):
            return "upcoming", "🟠 高概率将重置"
    return "vague", "🟡 仅模糊暗示"


def extract_status(lines):
    joined = " ".join(lines[:120]).lower()
    if "elevated signal" in joined or "radar elevated" in joined:
        return "elevated"
    if "possible reset within" in joined:
        return "watch"
    return "normal"


def extract_candidates(source, lines):
    out = []
    seen_local = set()

    for i, line in enumerate(lines):
        if not line_is_signal(line):
            continue

        # 给短回复补一点上下文，例如 “I accept your vote”
        context_parts = []
        if i > 0 and len(line) < 80:
            prev = lines[i - 1]
            if len(prev) <= 240:
                context_parts.append(prev)
        context_parts.append(line)

        text = normalize(" | ".join(context_parts))
        # hash 只看核心当前行，避免“1 hour ago”之类上下文变化造成重复提醒
        sid = stable_id(line)
        if sid in seen_local:
            continue
        seen_local.add(sid)

        kind, label = classify(text)
        out.append(
            {
                "id": sid,
                "kind": kind,
                "label": label,
                "text": text[:700],
                "source": source["name"],
                "url": source["url"],
            }
        )
    return out


def gen_feishu_sign(secret: str, timestamp: int) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def send_feishu(message: str):
    webhook = os.environ.get("FEISHU_WEBHOOK", "").strip()
    if not webhook:
        raise RuntimeError("缺少 GitHub Secret：FEISHU_WEBHOOK")

    secret = os.environ.get("FEISHU_SECRET", "").strip()
    payload = {
        "msg_type": "text",
        "content": {"text": message},
    }

    if secret:
        ts = int(time.time())
        payload["timestamp"] = ts
        payload["sign"] = gen_feishu_sign(secret, ts)

    resp = requests.post(webhook, json=payload, timeout=20)
    resp.raise_for_status()

    try:
        data = resp.json()
    except Exception:
        data = {}

    code = data.get("code")
    if code is None:
        code = data.get("StatusCode")
    if code not in (None, 0):
        raise RuntimeError(f"飞书返回失败：{data}")


def format_alert(items, status_transition=None):
    severity = {"confirmed": 3, "upcoming": 2, "vague": 1}
    items = sorted(items, key=lambda x: severity.get(x["kind"], 0), reverse=True)[:5]

    lines = ["【Tibo Reset Monitor】"]
    if items:
        best = items[0]["label"]
        lines.append(f"判断：{best}")
    elif status_transition == "elevated":
        lines.append("判断：🟠 高概率将重置")
    elif status_transition == "watch":
        lines.append("判断：🟡 进入重置观察窗口")
    else:
        lines.append("判断：发现新的重置信号")

    lines.append(f"检查时间：{now_cn().strftime('%Y-%m-%d %H:%M:%S')}（北京时间）")
    lines.append("")

    if status_transition in ("elevated", "watch") and not items:
        lines.append("追踪站状态出现新的预警级别变化。")
        lines.append("来源：https://codex-resets.com/")
        lines.append("")

    for idx, item in enumerate(items, 1):
        text = item["text"].replace("\n", " ")
        if len(text) > 520:
            text = text[:517] + "..."
        lines.append(f"{idx}. {item['label']}")
        lines.append(f"来源：{item['source']}")
        lines.append(f"内容：{text}")
        lines.append(f"链接：{item['url']}")
        lines.append("")

    lines.append("说明：本监控只使用网页抓取和本地关键词规则，不调用任何 AI / GPT 模型。")
    return "\n".join(lines)


def format_test(candidate_count, source_count):
    return (
        "【Tibo Reset Monitor】\n"
        "✅ 测试通知成功\n"
        f"已连接飞书，当前可访问 {source_count} 个监控源，初始化记录 {candidate_count} 条参考信号。\n"
        "历史内容不会重复推送；从现在起只提醒新出现的有效重置信号。\n"
        "监控频率：每 6 小时一次。\n"
        "模型消耗：0（不调用 GPT / Work / Codex / AI API）。"
    )


def main():
    state = load_state()
    send_test = os.environ.get("SEND_TEST", "").strip().lower() in {
        "1", "true", "yes", "on"
    }

    all_candidates = []
    statuses = {}
    failures = []
    success_sources = 0

    for source in SOURCES:
        try:
            lines = fetch_lines(source["url"], source["max_lines"])
            success_sources += 1
            statuses[source["name"]] = extract_status(lines)
            all_candidates.extend(extract_candidates(source, lines))
            print(
                f"[OK] {source['name']}: "
                f"{len(lines)} lines, "
                f"{statuses[source['name']]} status"
            )
        except Exception as exc:
            failures.append(f"{source['name']}: {exc}")
            print(f"[WARN] {source['name']}: {exc}", file=sys.stderr)

    # 所有源都失败：连续两次才发故障提醒，避免偶发网络波动打扰
    if success_sources == 0:
        state["all_fail_count"] = int(state.get("all_fail_count", 0)) + 1
        if state["all_fail_count"] >= 2 and not state.get("health_alert_sent", False):
            try:
                send_feishu(
                    "【Tibo Reset Monitor】\n"
                    "⚠️ 监控源连续两次全部访问失败。\n"
                    "这不是重置信号，而是监控健康提醒。\n"
                    "请打开 GitHub Actions 查看运行日志。"
                )
                state["health_alert_sent"] = True
            except Exception as exc:
                print(f"[ERROR] health alert failed: {exc}", file=sys.stderr)
        save_state(state)
        raise RuntimeError("所有监控源均访问失败：" + " | ".join(failures))

    # 任一来源恢复后重置健康状态
    if state.get("all_fail_count", 0) or state.get("health_alert_sent", False):
        state["all_fail_count"] = 0
        state["health_alert_sent"] = False

    # 去重
    dedup = {}
    for item in all_candidates:
        dedup.setdefault(item["id"], item)
    all_candidates = list(dedup.values())

    current_ids = [x["id"] for x in all_candidates]
    previous_seen = set(state.get("seen", []))

    # 第一次运行只建立基线，不把历史几十条都发给你
    if not state.get("initialized", False):
        state["initialized"] = True
        state["seen"] = current_ids[-500:]
        state["source_status"] = statuses
        state["last_keepalive"] = iso_now()
        save_state(state)

        if send_test:
            send_feishu(format_test(len(current_ids), success_sources))
            print("[OK] test notification sent")
        else:
            print("[OK] baseline initialized; no historical alert sent")
        return

    new_items = [x for x in all_candidates if x["id"] not in previous_seen]

    # 监控预警等级的“新进入”变化
    prior_status = state.get("source_status", {})
    status_transition = None
    for source_name, status in statuses.items():
        old = prior_status.get(source_name, "normal")
        if status != old and status in ("elevated", "watch"):
            status_transition = status
            break

    if new_items or status_transition:
        send_feishu(format_alert(new_items, status_transition))
        print(f"[OK] alert sent: {len(new_items)} new item(s), transition={status_transition}")
    else:
        print("[OK] no new reset signal")

    if send_test:
        send_feishu(format_test(len(current_ids), success_sources))
        print("[OK] manual test notification sent")

    # 记录已经见过的项目。保留旧 seen，防止页面条目上下移动后再次出现时重复提醒。
    merged_seen = list(previous_seen.union(current_ids))
    if len(merged_seen) > 800:
        merged_seen = merged_seen[-800:]
    state["seen"] = merged_seen
    state["source_status"] = statuses

    # 每 30 天制造一次很小的 state 变动，让公共仓库保持活动，
    # 避免 GitHub 对 60 天无活动的 public repo 自动停掉 scheduled workflow。
    keepalive = state.get("last_keepalive")
    do_keepalive = False
    if not keepalive:
        do_keepalive = True
    else:
        try:
            last = datetime.fromisoformat(keepalive.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - last >= timedelta(days=30):
                do_keepalive = True
        except Exception:
            do_keepalive = True

    if do_keepalive:
        state["last_keepalive"] = iso_now()

    save_state(state)


if __name__ == "__main__":
    main()
