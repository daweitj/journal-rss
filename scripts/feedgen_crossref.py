#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
feedgen_crossref.py —— 用 Crossref 元数据给「抓不到官网」的期刊生成 RSS

适用：官网被 Cloudflare / 登录墙拦住（ACS、Wiley、Elsevier 等），但期刊被 Crossref 收录。
优点：Crossref API 公开、无机器人拦截，GitHub Actions 可稳定每天抓。
代价：只有元数据（标题、作者、日期、DOI、可能的摘要），没有正文。

用法:
    python3 feedgen_crossref.py --issn 2643-6728 --name "Accounts of Materials Research" \\
        --limit 30 --out feed.xml [--mailto you@example.com]
"""
import argparse, gzip, html, json, re, sys, time
import urllib.request
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
from xml.sax.saxutils import escape

UA = "rss-feed-builder/1.0 (mailto:%s)"
TZ = timezone(timedelta(hours=8))

# 各刊都会混入“版式页”条目（封面、编委会、勘误等），不是文章，需剔除
NOISE_TITLE = re.compile(
    r"(Masthead|Publication Information|Issue Information|Editorial Board|Table of Contents|"
    r"Front Cover|Back Cover|In This Issue|Issue Cover|Correction to|Erratum|Retraction|"
    r"Call for Papers|Announcement)", re.I)


def fetch(url, mailto, timeout=40, tries=4):
    """Crossref 对匿名客户端限流（实测连续 4 次即 429），带退避重试"""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA % mailto,
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode("utf-8"))
        except Exception as e:
            last = e
            code = getattr(e, "code", None)
            wait = getattr(e, "headers", None)
            retry_after = 0
            if wait is not None:
                try:
                    retry_after = int(wait.get("Retry-After") or 0)
                except Exception:
                    retry_after = 0
            delay = max(retry_after, 5 * (2 ** i))
            print(f"   Crossref 返回 {code or e}，{delay}s 后重试（{i+1}/{tries}）", file=sys.stderr)
            time.sleep(delay)
    raise last


def clean(text):
    if not text:
        return ""
    t = re.sub(r"<[^>]+>", " ", text)      # 去 JATS/HTML 标签
    t = html.unescape(t)
    t = re.sub(r"\s+", " ", t).strip()      # Crossref 标题里常有换行，压成单空格
    return t


def date_of(item):
    for key in ("published", "published-print", "published-online", "issued", "created"):
        dp = (item.get(key) or {}).get("date-parts") or []
        if dp and dp[0]:
            parts = list(dp[0]) + [1, 1]
            try:
                y, m, d = int(parts[0]), int(parts[1] or 1), int(parts[2] or 1)
                return datetime(y, m, d, tzinfo=TZ)
            except Exception:
                continue
    return None


def build(items, name, issn, out, site=""):
    now = datetime.now(TZ)
    buf = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/" '
           'xmlns:atom="http://www.w3.org/2005/Atom">', "<channel>",
           f"<title>{escape(name)} — 最新论文</title>",
           f"<link>{escape(site or 'https://api.crossref.org/journals/' + issn + '/works')}</link>",
           f"<description>{escape(name)}（ISSN {escape(issn)}）最新收录论文，"
           f"数据来自 Crossref 元数据，共 {len(items)} 条。</description>",
           "<language>en</language>",
           f"<lastBuildDate>{now.strftime('%a, %d %b %Y %H:%M:%S %z')}</lastBuildDate>",
           "<ttl>360</ttl>"]
    for it in items:
        tags = [f"作者：{it['authors']}" if it["authors"] else "",
                f"DOI：{it['doi']}",
                f"类型：{it['type']}" if it["type"] else ""]
        body = escape(it["abstract"]) + "\n\n" + escape(" | ".join([t for t in tags if t]))
        buf += ["<item>",
                f"<title>{escape(it['title'])}</title>",
                f"<link>{escape(it['link'])}</link>",
                f'<guid isPermaLink="true">{escape(it["link"])}</guid>',
                f"<description>{body}</description>",
                f"<pubDate>{it['dt'].strftime('%a, %d %b %Y %H:%M:%S %z')}</pubDate>"]
        if it["authors"]:
            buf.append(f"<dc:creator>{escape(it['authors'].split('、')[0])}</dc:creator>")
        buf.append(f"<category>{escape(it['doi'])}</category>")
        buf.append("</item>")
    buf += ["</channel>", "</rss>"]
    open(out, "w", encoding="utf-8").write("\n".join(buf))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--issn", required=True, help="期刊 ISSN，如 2643-6728")
    ap.add_argument("--name", default="", help="期刊全名")
    ap.add_argument("--site", default="", help="期刊首页 URL（频道链接）")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--out", default="feed.xml")
    ap.add_argument("--mailto", default="rss-builder@example.com",
                    help="Crossref 建议提供联系邮箱，便于限流时联系")
    args = ap.parse_args()

    name = args.name or args.issn
    url = (f"https://api.crossref.org/journals/{quote(args.issn)}/works"
           f"?sort=published&order=desc&rows={min(args.limit * 3 + 10, 200)}"
           "&select=DOI,title,author,published,published-print,published-online,"
           "issued,created,abstract,type,container-title,URL"
           f"&mailto={quote(args.mailto)}")
    msg = fetch(url, args.mailto)["message"]
    print(f"Crossref 返回 {msg.get('total-results')} 条记录", file=sys.stderr)

    items = []
    for it in msg["items"]:
        dt = date_of(it)
        if not dt:
            continue
        doi = it.get("DOI", "")
        raw_title = (it.get("title") or [""])[0]
        # 剔除期刊版式页/非研究内容（各刊都有一批这类“文章”）
        if NOISE_TITLE.search(raw_title):
            continue
        items.append(dict(
            title=clean((it.get("title") or ["(无标题)"])[0]) or "(无标题)",
            link=f"https://doi.org/{doi}",
            doi=doi,
            dt=dt,
            type=it.get("type", ""),
            abstract=clean(it.get("abstract", ""))[:1500],
            authors="、".join(
                clean((a.get("family") or "") + (" " + a.get("given") if a.get("given") else ""))
                for a in (it.get("author") or [])[:8]
            ),
        ))
    items.sort(key=lambda x: x["dt"], reverse=True)
    items = items[: args.limit]
    build(items, name, args.issn, args.out, args.site)
    with_ab = sum(1 for i in items if i["abstract"])
    print(f"已生成 {args.out}：{len(items)} 条，其中带摘要 {with_ab} 条", file=sys.stderr)


if __name__ == "__main__":
    main()
