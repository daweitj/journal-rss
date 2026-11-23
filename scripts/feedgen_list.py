#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""feedgen_list.py —— 只靠「列表页 + 文章页元信息」的期刊 RSS 生成器

feedgen_journal.py 的 sitemap 版覆盖不到的站用它：
  - 列表页 href 用单引号（RHHz 等模板）
  - 作者写在 citation_authors（复数，逗号分隔）
其余同 feedgen_journal.py：详情页 citation_* 元信息 + 正文摘要兜底。

用法:
  python3 feedgen_list.py --site https://x.com --name "某刊" \
      --list-url https://x.com/ --link-pattern "/article/doi/" --limit 30
"""
import argparse, gzip, html, http.client, re, sys, time
from concurrent.futures import ThreadPoolExecutor
import urllib.request
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlparse
from xml.sax.saxutils import escape

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
TZ = timezone(timedelta(hours=8))


def get(url, tries=3, timeout=30):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                       "Accept-Language": "zh-CN,zh;q=0.9"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                try:
                    raw = r.read()
                except http.client.IncompleteRead as e:
                    raw = e.partial
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw.decode("utf-8", "replace")
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def clean(text):
    if not text:
        return ""
    t = html.unescape(text)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


def meta(page, *names):
    for name in names:
        m = re.search(r'<meta[^>]*(?:name|property)="%s"[^>]*content="([^"]*)"' % re.escape(name), page, re.I)
        if m:
            return html.unescape(m.group(1))
    return ""


def collect_list(list_url, pattern):
    page = get(list_url)
    out = []
    for href in re.findall(r'href=["\']([^"\'>]+)["\']', page):
        if pattern and not re.search(pattern, href):
            continue
        u = urljoin(list_url, html.unescape(href)).split("#")[0]
        if u not in out:
            out.append(u)
    return out


def parse(url, date_fields):
    page = get(url)
    title = clean(meta(page, "citation_title", "og:title", "twitter:title")) or clean(
        (re.search(r"<title>([^<]*)</title>", page) or [None, ""])[1])
    desc = clean(meta(page, "citation_abstract", "description", "og:description", "dcterms.description"))
    if len(desc) < 40:
        best = ""
        for m in re.finditer(r"摘\s*要[\s:：&nbsp;\u00a0]{0,12}([\s\S]{60,3000}?)(?:关键词|关键字|Abstract\b|参考文献|服务|把本文推荐|上一篇|下一篇|作者简介|基金项目|引用本文|全文下载|PDF下载|相关文章|推荐阅读)", page):
            t = clean(m.group(1))
            if len(re.findall(r"[\u4e00-\u9fff]", t)) > 60 and len(t) > len(best):
                best = t
        if best:
            desc = best
    doi = clean(meta(page, "citation_doi"))
    authors = [clean(a) for a in re.findall(
        r'<meta[^>]*name="citation_author"[^>]*content="([^"]*)"', page, re.I)]
    if not authors:
        v = clean(meta(page, "citation_authors"))
        if v:
            authors = [x.strip() for x in re.split(r"[,;，；]", v) if x.strip()]
    raw_date = ""
    for f in date_fields:
        v = clean(meta(page, f))
        if v:
            raw_date = v
            break
    dt = None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(raw_date.strip(), fmt)
            dt = dt if dt.tzinfo else dt.replace(tzinfo=TZ)
            break
        except Exception:
            pass
    return dict(title=title or "（无标题）", link=url, desc=desc, doi=doi,
                authors=authors, raw_date=raw_date, dt=dt)


def build(items, name, site, out, limit):
    now = datetime.now(TZ)
    buf = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" '
           'xmlns:dc="http://purl.org/dc/elements/1.1/">',
           "<channel>",
           f"<title>{escape(name)} — 最新发布</title>",
           f"<link>{escape(site)}</link>",
           f"<description>{escape(name)} 最新发布内容（标题、作者、摘要、DOI），由列表页与文章页元信息生成。</description>",
           "<language>zh-cn</language>",
           f"<lastBuildDate>{now.strftime('%a, %d %b %Y %H:%M:%S %z')}</lastBuildDate>",
           "<ttl>360</ttl>"]
    for it in items[:limit]:
        dt = it["dt"] or now
        tail = [f"作者：{'、'.join(it['authors'][:8])}{'等' if len(it['authors']) > 8 else ''}" if it["authors"] else "",
                f"DOI：{it['doi']}" if it["doi"] else ""]
        body = escape(it["desc"]) + ("\n\n" + escape(" | ".join([t for t in tail if t])) if any(tail) else "")
        buf += ["<item>",
                f"<title>{escape(it['title'])}</title>",
                f"<link>{escape(it['link'])}</link>",
                f'<guid isPermaLink="true">{escape(it["link"])}</guid>',
                f"<description>{body}</description>",
                f"<pubDate>{dt.strftime('%a, %d %b %Y %H:%M:%S %z')}</pubDate>"]
        if it["authors"]:
            buf.append(f"<dc:creator>{escape(it['authors'][0])}</dc:creator>")
        if it["doi"]:
            buf.append(f"<category>{escape(it['doi'])}</category>")
        buf.append("</item>")
    buf += ["</channel>", "</rss>"]
    open(out, "w", encoding="utf-8").write("\n".join(buf))
    return len(items)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True)
    ap.add_argument("--name", default="")
    ap.add_argument("--list-url", required=True, help="列表页，多个用英文逗号分隔")
    ap.add_argument("--link-pattern", default="", help="列表页里文章链接的正则")
    ap.add_argument("--date-fields", default="citation_publication_date,citation_online_date,citation_date,dc.date,article:published_time")
    ap.add_argument("--max-age-days", type=int, default=540)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--out", default="feed.xml")
    a = ap.parse_args()

    name = a.name or a.site
    urls = []
    for lu in [x.strip() for x in a.list_url.split(",") if x.strip()]:
        for u in collect_list(lu, a.link_pattern):
            if u not in urls:
                urls.append(u)
    print(f"列表页候选 {len(urls)} 条，抓取前 {a.limit} 篇…", file=sys.stderr)

    def one(u):
        try:
            return parse(u, a.date_fields.split(","))
        except Exception as e:
            print("跳过", u, str(e)[:60], file=sys.stderr)
            return None

    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
        items = [x for x in ex.map(one, urls[:a.limit * 2]) if x]
    items.sort(key=lambda x: (x["dt"] or datetime.min.replace(tzinfo=TZ)), reverse=True)
    newest = max((x["dt"] for x in items if x["dt"]), default=None)
    if newest and a.max_age_days > 0:
        cutoff = newest - timedelta(days=a.max_age_days)
        items = [x for x in items if not x["dt"] or x["dt"] >= cutoff]
        print(f"按 {cutoff:%Y-%m-%d} 之后过滤，剩余 {len(items)} 条", file=sys.stderr)
    n = build(items, name, a.site, a.out, a.limit)
    print(f"已生成 {a.out}，条目 {n}", file=sys.stderr)
    if n == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
