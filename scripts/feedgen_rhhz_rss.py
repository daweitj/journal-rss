#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RHHz（仁和汇智）平台期刊：官方 RSS 残缺时转成标准 RSS 2.0

适用站点：xxx.mat-test.com 一类，官方 /rss/*.xml 有条目但
  - item 的 dc:date / prism:publicationDate 为空
  - dc:creator 为空
  - description 被多层转义
做法：以官方 feed 为条目索引（标题、摘要以它为准），逐条抓文章页
/article/doi/<doi> 补 citation_publication_date / citation_author /
citation_keywords；抓不到（403/超时）就退回官方数据，日期从种子
feeds/<seed>.json 兜底，保证条目和日期都不丢。
"""
import argparse, html, json, os, re, sys, time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from xml.sax.saxutils import escape

TZ = timezone(timedelta(hours=8))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def get(url, timeout=25, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            last = e
            time.sleep(1.2 * (i + 1))
    raise last


def clean(t):
    """官方摘要被转义多层：循环还原后剥标签，保留 <sub>/<sup> 语义（这里只留文字）"""
    if not t:
        return ""
    for _ in range(3):
        nt = html.unescape(t)
        if nt == t:
            break
        t = nt
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"[ \t\r\n\u00a0]+", " ", t).strip()
    return t


def meta(page, name):
    m = re.search(r'<meta[^>]*name="%s"[^>]*content="([^"]*)"' % re.escape(name), page, re.I)
    return html.unescape(m.group(1)).strip() if m else ""


def parse_official(xml_text):
    root = ET.fromstring(xml_text.encode("utf-8"))
    ns = {"rss": "http://purl.org/rss/1.0/", "dc": "http://purl.org/dc/elements/1.1/",
          "prism": "http://prismstandard.org/namespaces/basic/2.0/"}
    out = []
    for it in root.findall("rss:item", ns):
        link = it.findtext("rss:link", default="", namespaces=ns).strip()
        if not link:
            continue
        out.append(dict(
            link=link,
            title=clean(it.findtext("rss:title", default="", namespaces=ns)),
            desc=clean(it.findtext("rss:description", default="", namespaces=ns)),
            source=clean(it.findtext("dc:source", default="", namespaces=ns)),
            volume=it.findtext("prism:volume", default="", namespaces=ns) or "",
            number=it.findtext("prism:number", default="", namespaces=ns) or "",
        ))
    return out


def fetch_detail(link, timeout, deadline):
    if time.time() > deadline:
        return {}
    try:
        page = get(link, timeout=timeout, tries=2)
    except Exception as e:
        print(f"  [skip] {link} {str(e)[:40]}", file=sys.stderr)
        return {}
    ab = ""
    m = re.search(r'<div class="abstract-cn">(.*?)<div class="abstract-en">', page, re.S)
    if m:
        ab = re.sub(r"<[^>]+>", " ", m.group(1))
        ab = re.sub(r"\s+", " ", html.unescape(ab)).strip()
        ab = re.sub(r"^\s*摘\s*要[:：]?\s*", "", ab)
    else:
        ab = clean(meta(page, "citation_abstract"))
    return dict(
        abstract=ab,
        date=meta(page, "citation_publication_date") or meta(page, "citation_online_date"),
        authors=[a for a in re.findall(
            r'<meta[^>]*name="citation_author"[^>]*content="([^"]*)"', page, re.I) if a.strip()],
        keywords=meta(page, "citation_keywords"),
        volume=meta(page, "citation_volume"),
        number=meta(page, "citation_issue"),
        title=clean(meta(page, "citation_title")),
    )


def to_dt(s):
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            d = datetime.strptime(s.strip(), fmt)
            return d if d.tzinfo else d.replace(tzinfo=TZ)
        except Exception:
            pass
    return None


def mild_clean(t):
    """官方 desc 层层转义，激进 unescape 会把正文当标签吞掉：只还原一层再剥短标签"""
    if not t:
        return ""
    t = html.unescape(t)
    t = re.sub(r"<[^>]{1,40}>", " ", t)
    for a, b in (("&lt;", " "), ("&gt;", " "), ("&amp;", " & "), ("&nbsp;", " ")):
        t = t.replace(a, b)
    return re.sub(r"[ \t\r\n\u00a0]+", " ", t).strip()


def strip_source_tail(desc, journal):
    """去掉官方摘要尾部的 '刊名. 2026 62(10): 1-4.'"""
    if not journal:
        return desc
    return re.sub(r"\s*" + re.escape(journal) + r"\.\s*\d{4}\s+\d+\s*\(\s*\d+\s*\)\s*:\s*[\d\-–，,]+\s*\.?\s*$", "", desc).strip()


def build(items, name, site, out):
    now = datetime.now(TZ)
    L = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" '
         'xmlns:dc="http://purl.org/dc/elements/1.1/">',
         "<channel>",
         f"<title>{escape(name)} — 最新论文</title>",
         f"<link>{escape(site)}/</link>",
         f"<description>{escape(name)} 最新论文（标题、作者、关键词、摘要），"
         "由编辑部官方条目 + 文章页元信息整理</description>",
         "<language>zh-CN</language>",
         f"<lastBuildDate>{now.strftime('%a, %d %b %Y %H:%M:%S %z')}</lastBuildDate>",
         "<ttl>720</ttl>"]
    for it in items:
        L += ["<item>",
              f"<title>{escape(it['title'] or '（无标题）')}</title>",
              f"<link>{escape(it['link'])}</link>",
              f'<guid isPermaLink="true">{escape(it["link"])}</guid>']
        if it["dt"]:
            L.append(f"<pubDate>{it['dt'].strftime('%a, %d %b %Y %H:%M:%S %z')}</pubDate>")
        if it["authors"]:
            L.append(f"<dc:creator>{escape(', '.join(it['authors']))}</dc:creator>")
        body = []
        if it["authors"]:
            body.append("作者：" + "、".join(it["authors"]))
        vol = []
        if it["volume"]:
            vol.append(it["volume"] + "卷")
        if it["number"]:
            vol.append(it["number"] + "期")
        if vol:
            body.append("出处：" + "".join(vol))
        if it["keywords"]:
            body.append("关键词：" + it["keywords"])
        if it["abstract"]:
            body.append(it["abstract"])
        L.append("<description>" + escape("\n".join(body)) + "</description>")
        L.append("</item>")
    L += ["</channel>", "</rss>", ""]
    open(out, "w", encoding="utf-8").write("\n".join(L))


def main():
    ap = argparse.ArgumentParser(description="RHHz 平台期刊 RSS 生成")
    ap.add_argument("--site", required=True)
    ap.add_argument("--rss-url", required=True, help="官方 feed 完整地址")
    ap.add_argument("--name", required=True)
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", default="", help="日期种子 json（可选，{link:{d,a,k}}）")
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--budget", type=int, default=300, help="详情页抓取总预算秒数")
    a = ap.parse_args()

    entries = parse_official(get(a.rss_url, timeout=40))[:a.limit]
    print(f"官方条目 {len(entries)} 条", file=sys.stderr)

    seed = {}
    if a.seed and os.path.exists(a.seed):
        try:
            seed = json.load(open(a.seed, encoding="utf-8"))
            print(f"种子 {len(seed)} 条", file=sys.stderr)
        except Exception:
            pass

    deadline = time.time() + a.budget
    items, fresh_seed = [], {}
    for e in entries:
        d = fetch_detail(e["link"], a.timeout, deadline)
        se = seed.get(e["link"], {}) if isinstance(seed.get(e["link"], {}), dict) else {"d": seed[e["link"]]}
        title = d.get("title") or e["title"]
        authors = d.get("authors") or (se.get("a") if isinstance(se.get("a"), list) else [])
        keywords = d.get("keywords") or (se.get("k") or "")
        abstract = d.get("abstract") or strip_source_tail(mild_clean(e["desc"]), a.name)
        dt = to_dt(d.get("date") or "") or to_dt(se.get("d") or "")
        year = re.search(r"(\d{4})\s+\d+\s*\(\d+\)", e["source"])
        if not dt and year:
            dt = to_dt(year.group(1) + "-01-01")
        vol = d.get("volume") or e["volume"]
        num = d.get("number") or e["number"]
        items.append(dict(title=title, link=e["link"], dt=dt, authors=authors,
                          keywords=keywords, abstract=abstract, volume=vol, number=num))
        fresh_seed[e["link"]] = dict(d=dt.strftime("%Y-%m-%d") if dt else "", a=authors, k=keywords)
        print(f"  {dt.strftime('%Y-%m-%d') if dt else '(无日期)'}  {title[:42]}", file=sys.stderr)

    items.sort(key=lambda x: x["dt"] or datetime.max.replace(tzinfo=TZ), reverse=True)
    build(items, a.name, a.site, a.out)
    if a.seed:
        json.dump(fresh_seed, open(a.seed, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    dated = sum(1 for i in items if i["dt"])
    print(f"写入 {a.out}：{len(items)} 条，{dated} 条有日期", file=sys.stderr)
    if not items:
        sys.exit(1)


if __name__ == "__main__":
    main()
