#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
feedgen_journal.py —— 通用「期刊/论文站」RSS 生成器

只适用于"无官方 feed + 有 sitemap + 详情页 SSR 带 citation_* 元信息"的站点
（先用 rss_probe.py 确认）。站别名、sitemap 路径、文章 URL 正则都可配。

用法:
  python3 feedgen_journal.py --site https://example.com --name "某期刊" --limit 30
  python3 feedgen_journal.py --site https://example.com --article-pattern "/zh/article/" --out feed.xml
"""
import argparse, gzip, html, re, sys, time
import urllib.request
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlparse
from xml.sax.saxutils import escape

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TZ = timezone(timedelta(hours=8))


def get(url, tries=3, timeout=30):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw.decode("utf-8", "replace")
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def clean(text):
    """元信息里的上下标常被转义两次：Li/CF&lt;sub&gt;x&lt;/sub&gt; -> Li/CFx
    剥标签不能补空格，否则会变成 'Li/CF x'"""
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


def norm_site(site):
    """取站点 origin（scheme://host）：.../homeNav?lang=zh 不能直接拼 /sitemap.xml"""
    p = urlparse(re.sub(r"[?#].*$", "", site))
    return f"{p.scheme}://{p.netloc}"


def sitemap_urls(site, index_path):
    idx = urljoin(norm_site(site) + "/", index_path.lstrip("/"))
    body = get(idx)
    if "<sitemapindex" in body:
        return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body)
    return [idx]


def collect(site, index_path, pattern):
    """按 sitemap 收集候选文章 URL：[(url, lastmod)]"""
    out = []
    for sm in sitemap_urls(site, index_path):
        try:
            xml = get(sm)
        except Exception:
            continue
        for block in re.findall(r"<url>[\s\S]*?</url>", xml):
            loc = re.search(r"<loc>\s*([^<\s]+)\s*</loc>", block)
            lm = re.search(r"<lastmod>\s*([^<\s]+)\s*</lastmod>", block)
            if not loc:
                continue
            u = html.unescape(loc.group(1).strip())
            if pattern and not re.search(pattern, u):
                continue
            out.append((u, lm.group(1).strip() if lm else ""))
    out.sort(key=lambda t: t[1], reverse=True)
    return out


def parse(url, date_fields):
    page = get(url)
    title = clean(meta(page, "citation_title", "og:title", "twitter:title")) or clean(
        (re.search(r"<title>([^<]*)</title>", page) or [None, ""])[1])
    desc = clean(meta(page, "citation_abstract", "description", "og:description", "dcterms.description"))
    doi = clean(meta(page, "citation_doi"))
    authors = [clean(a) for a in re.findall(
        r'<meta[^>]*name="citation_author"[^>]*content="([^"]*)"', page, re.I)]
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


def build(items, name, site, out, limit, self_url=""):
    now = datetime.now(TZ)
    buf = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" '
           'xmlns:dc="http://purl.org/dc/elements/1.1/">',
           "<channel>",
           f"<title>{escape(name)} — 最新发布</title>",
           f"<link>{escape(site)}</link>",
           f"<description>{escape(name)} 最新发布内容（标题、作者、摘要、DOI），"
           f"由站点 sitemap 与详情页元信息生成，共 {len(items)} 条。</description>",
           "<language>zh-cn</language>",
           f"<lastBuildDate>{now.strftime('%a, %d %b %Y %H:%M:%S %z')}</lastBuildDate>",
           "<ttl>360</ttl>"]
    if self_url:
        buf.append(f'<atom:link href="{escape(self_url)}" rel="self" type="application/rss+xml"/>')
    for it in items[:limit]:
        dt = it["dt"] or now
        tail = [f"作者：{'、'.join(it['authors'][:8])}{'等' if len(it['authors']) > 8 else ''}" if it["authors"] else "",
                f"DOI：{it['doi']}" if it["doi"] else "",
                f"发布日期：{it['raw_date']}" if it["raw_date"] else ""]
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
    ap.add_argument("--site", required=True, help="站点根地址，如 https://www.example.com")
    ap.add_argument("--name", default="", help="频道名称（阅读器里显示）")
    ap.add_argument("--sitemap", default="/sitemap.xml", help="sitemap 索引路径，默认 /sitemap.xml")
    ap.add_argument("--article-pattern", default=r"/article/|/doi/|/paper/|/abs/",
                    help="文章 URL 正则，用来过滤 sitemap 里的非文章页")
    ap.add_argument("--date-fields", default="citation_online_date,citation_publication_date,article:published_time",
                    help="取日期的 meta 名，逗号分隔，按顺序尝试")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--out", default="feed.xml")
    ap.add_argument("--self-url", default="")
    a = ap.parse_args()

    name = a.name or a.site
    arts = collect(a.site, a.sitemap, a.article_pattern)
    print(f"候选文章 {len(arts)} 条，抓取前 {a.limit} 篇…", file=sys.stderr)
    items = []
    for u, lm in arts[:a.limit]:
        try:
            items.append(parse(u, a.date_fields.split(",")))
        except Exception as e:
            print("跳过", u, str(e)[:60], file=sys.stderr)
    # 按真实发布日排序（sitemap lastmod 可能是批量刷新时间，不能当发布时间）
    items.sort(key=lambda x: (x["dt"] or datetime.min.replace(tzinfo=TZ)), reverse=True)
    # sitemap lastmod 被批量重建时会把多年前的旧文顶到前排，按最新一篇为基准丢弃过旧条目
    newest = max((x["dt"] for x in items if x["dt"]), default=None)
    if newest:
        cutoff = newest - timedelta(days=540)
        items = [x for x in items if not x["dt"] or x["dt"] >= cutoff]
        print(f"按 {cutoff:%Y-%m-%d} 之后过滤，剩余 {len(items)} 条", file=sys.stderr)
    n = build(items, name, a.site, a.out, a.limit, a.self_url)
    print(f"已生成 {a.out}，条目 {n}", file=sys.stderr)


if __name__ == "__main__":
    main()
