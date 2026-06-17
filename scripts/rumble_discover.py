#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote, urljoin
from xml.etree import ElementTree

import requests


CHANNEL_URL = os.getenv("RUMBLE_CHANNEL_URL", "https://rumble.com/c/nickjfuentes")
OPENRSS_FALLBACK = os.getenv("OPENRSS_FALLBACK", "1") != "0"
PLAYWRIGHT_FALLBACK = os.getenv("PLAYWRIGHT_FALLBACK", "1") != "0"
QUALITY = os.getenv("QUALITY", "240")
KEEP_RELEASES = int(os.getenv("KEEP_RELEASES", "10"))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
GITHUB_OUTPUT = os.getenv("GITHUB_OUTPUT")
STATE_FILE = Path(".rumble_latest.json")

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def log(message):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), message, flush=True)


def http_get(url, **kwargs):
    headers = kwargs.pop("headers", {})
    headers.setdefault("User-Agent", UA)
    headers.setdefault("Accept-Language", "en-US,en;q=0.9")
    r = requests.get(url, headers=headers, timeout=45, **kwargs)
    r.raise_for_status()
    return r


def browser_get_html(url):
    if not PLAYWRIGHT_FALLBACK:
        raise RuntimeError("Playwright fallback disabled")
    log(f"Loading with browser fallback: {url}")
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError(f"Playwright is not available: {exc}") from exc

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )
        page = browser.new_page(
            user_agent=UA,
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        for _ in range(12):
            page.wait_for_timeout(5000)
            if "just a moment" not in page.title().lower():
                break
        html = page.content()
        final_url = page.url
        title = page.title()
        browser.close()
    log(f"Browser loaded: {title} ({final_url})")
    return html


def write_outputs(values):
    if not GITHUB_OUTPUT:
        print(json.dumps(values, indent=2))
        return
    with open(GITHUB_OUTPUT, "a", encoding="utf-8") as f:
        for key, value in values.items():
            value = str(value)
            if "\n" in value:
                marker = f"EOF_{key}"
                f.write(f"{key}<<{marker}\n{value}\n{marker}\n")
            else:
                f.write(f"{key}={value}\n")


def telegram_send(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("Telegram secrets not configured; skipping Telegram message")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    r = requests.post(url, json=payload, timeout=30)
    if not r.ok:
        raise RuntimeError(f"Telegram failed: {r.status_code} {r.text[:500]}")


def find_latest_episode():
    log(f"Checking channel: {CHANNEL_URL}")
    try:
        html = http_get(CHANNEL_URL).text
    except Exception as exc:
        if PLAYWRIGHT_FALLBACK:
            log(f"Direct channel fetch failed; trying browser fallback: {exc}")
            try:
                html = browser_get_html(CHANNEL_URL)
            except Exception as browser_exc:
                log(f"Browser fallback failed: {browser_exc}")
                if OPENRSS_FALLBACK:
                    log("Trying Open RSS fallback")
                    return find_latest_episode_openrss()
                raise
        elif OPENRSS_FALLBACK:
            log(f"Direct channel fetch failed; trying Open RSS fallback: {exc}")
            return find_latest_episode_openrss()
        else:
            raise

    candidates = []
    for href, text in re.findall(r'href="([^"]*v[^"]+?\.html[^"]*)"[^>]*>(.*?)</a>', html, re.I | re.S):
        clean_text = re.sub(r"<[^>]+>", " ", text)
        clean_text = re.sub(r"\s+", " ", clean_text).strip()
        page_url = urljoin("https://rumble.com/", href).split("?")[0]
        blob = f"{page_url} {clean_text}".lower()
        if "america-first" in blob or "america first" in blob:
            candidates.append((page_url, clean_text))

    if not candidates:
        for url in re.findall(r'https?://rumble\.com/(v[^"\']+?\.html)', html, re.I):
            page_url = "https://rumble.com/" + url
            if "america-first" in page_url.lower():
                candidates.append((page_url.split("?")[0], "America First"))

    dedup = []
    seen = set()
    for page_url, title in candidates:
        if page_url not in seen:
            seen.add(page_url)
            dedup.append((page_url, title))

    def ep_number(item):
        page_url, title = item
        m = re.search(r"ep\.?-?\s*(\d+)", f"{page_url} {title}", re.I)
        return int(m.group(1)) if m else -1

    if not dedup:
        if OPENRSS_FALLBACK:
            log("No matching links on channel page; trying Open RSS fallback")
            return find_latest_episode_openrss()
        raise RuntimeError("No America First episode links found on the Rumble channel page")

    dedup.sort(key=ep_number, reverse=True)
    latest = dedup[0]
    log(f"Latest candidate: {latest[0]}")
    return latest


def find_latest_episode_openrss():
    feed_url = "https://openrss.org/" + CHANNEL_URL.removeprefix("https://").removeprefix("http://")
    log(f"Checking Open RSS feed: {feed_url}")
    xml = http_get(feed_url).text
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        log(f"Open RSS XML parse failed; using regex fallback: {exc}")
        candidates = []
        for href in re.findall(r'https://rumble\.com/[^"\'<>\s]+?\.html', xml, re.I):
            clean = href.replace("&amp;", "&").split("?")[0]
            if "america-first" in clean.lower():
                candidates.append((clean, "America First"))
        if not candidates:
            raise
        candidates = list(dict.fromkeys(candidates))
        candidates.sort(key=lambda item: ep_number_from_text(f"{item[0]} {item[1]}"), reverse=True)
        return candidates[0]
    items = []

    # RSS 2.0 shape.
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip().split("?")[0]
        blob = f"{title} {link}".lower()
        if link and ("america first" in blob or "america-first" in blob):
            items.append((link, title))

    # Atom shape, just in case Open RSS changes format.
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for entry in root.findall(".//a:entry", ns):
        title = (entry.findtext("a:title", default="", namespaces=ns) or "").strip()
        link = ""
        for link_el in entry.findall("a:link", ns):
            href = link_el.attrib.get("href", "")
            if href:
                link = href.split("?")[0]
                break
        blob = f"{title} {link}".lower()
        if link and ("america first" in blob or "america-first" in blob):
            items.append((link, title))

    if not items:
        raise RuntimeError("No America First episode links found via Open RSS fallback")

    items.sort(key=lambda item: ep_number_from_text(f"{item[0]} {item[1]}"), reverse=True)
    latest = items[0]
    log(f"Latest Open RSS candidate: {latest[0]}")
    return latest


def ep_number_from_text(text):
    m = re.search(r"ep\.?-?\s*(\d+)", text, re.I)
    return int(m.group(1)) if m else -1


def get_embed_id(page_url):
    try:
        html = http_get(page_url).text
    except Exception as exc:
        if PLAYWRIGHT_FALLBACK:
            log(f"Direct video page fetch failed; trying browser fallback: {exc}")
            html = browser_get_html(page_url)
        else:
            raise
    patterns = [
        r'https://rumble\.com/embed/([^/"?]+)/',
        r'embedUrl\\?":\\?"https://rumble\.com/embed/([^/"?]+)/',
        r'/embed/([^/"?]+)/',
    ]
    for pattern in patterns:
        m = re.search(pattern, html)
        if m:
            return m.group(1)
    raise RuntimeError("Could not find embed id on page")


def get_video_info(embed_id, page_url):
    api_url = f"https://rumble.com/embedJS/u3/?request=video&ver=2&v={embed_id}"
    log(f"Fetching embed API: {api_url}")
    return http_get(api_url, headers={"Referer": page_url, "User-Agent": UA}).json()


def choose_stream(info):
    ua = info.get("ua", {})
    tar = ua.get("tar", {})
    if QUALITY in tar:
        return tar[QUALITY]["url"], tar[QUALITY].get("meta", {})
    if QUALITY in ua and isinstance(ua[QUALITY], list):
        meta = ua[QUALITY][2] if len(ua[QUALITY]) > 2 else {}
        return ua[QUALITY][0], meta
    available = sorted(tar.keys() or ua.keys())
    raise RuntimeError(f"Quality {QUALITY!r} not available. Available: {available}")


def safe_filename(title):
    title = re.sub(r"[\\/:*?\"<>|]+", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    title = title[:120].strip()
    return f"{title} - {QUALITY}p.mp4"


def discover():
    page_url, fallback_title = find_latest_episode()
    embed_id = get_embed_id(page_url)
    info = get_video_info(embed_id, page_url)
    title = info.get("title") or fallback_title or f"Rumble {embed_id}"
    hls_url, meta = choose_stream(info)
    filename = safe_filename(title)
    tag = f"rumble-{embed_id}-{QUALITY}p"
    outputs = {
        "page_url": page_url,
        "embed_id": embed_id,
        "tag": tag,
        "title": title,
        "hls_url": hls_url,
        "filename": filename,
        "filename_encoded": quote(filename),
        "quality": QUALITY,
        "meta_json": json.dumps(meta, sort_keys=True),
    }
    STATE_FILE.write_text(json.dumps(outputs, indent=2))
    write_outputs(outputs)
    log(f"Discovered {title}")
    log(f"Tag: {tag}")
    log(f"HLS: {hls_url}")


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def notify_done():
    state = load_state()
    release_url = os.getenv("RELEASE_URL", "")
    asset_url = os.getenv("ASSET_URL", "")
    telegram_send(
        "New America First episode downloaded\n\n"
        f"{state.get('title', 'Unknown title')}\n"
        f"Quality: {QUALITY}p\n"
        f"Release: {release_url}\n"
        f"Direct file: {asset_url}"
    )


def notify_skip():
    state = load_state()
    log(f"No new episode. Existing tag: {state.get('tag', 'unknown')}")


def cleanup():
    if KEEP_RELEASES <= 0:
        log("Release cleanup disabled")
        return
    result = subprocess.run(
        ["gh", "release", "list", "--limit", "100", "--json", "tagName,createdAt"],
        check=True,
        text=True,
        capture_output=True,
    )
    releases = json.loads(result.stdout)
    rumble_releases = [r for r in releases if r["tagName"].startswith("rumble-")]
    rumble_releases.sort(key=lambda r: r["createdAt"], reverse=True)
    for rel in rumble_releases[KEEP_RELEASES:]:
        tag = rel["tagName"]
        log(f"Deleting old release: {tag}")
        subprocess.run(["gh", "release", "delete", tag, "--cleanup-tag", "--yes"], check=True)


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "discover"
    if command == "discover":
        discover()
    elif command == "notify-done":
        notify_done()
    elif command == "notify-skip":
        notify_skip()
    elif command == "cleanup":
        cleanup()
    else:
        raise SystemExit(f"Unknown command: {command}")


if __name__ == "__main__":
    main()
