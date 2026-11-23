#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""《机械工程材料》(Materials for Mechanical Engineering) RSS 生成器

站点：https://jxgccl.mat-test.com  （仁和汇智 RHHz 平台，页面 JS 模板渲染，无 sitemap）
数据源分层：
  1. 站点官方 RSS(1.0) https://jxgccl.mat-test.com/rss/latest.xml
     —— 提供条目 DOI、摘要原文；缺陷是 dc:date 与 prism:publicationDate 均为空、
        部分标题被多层转义破坏（如 H&lt;sub&lt;2&lt;/sub&lt;S…）
  2. 逐条抓文章详情页 /article/doi/<doi>
     —— 取 citation_publication_date / citation_online_date（真实发布日）、
        citation_title（规范标题）、citation_author（作者）、
        div.abstract-cn 内的干净中文摘要（保留 sub/sup 上下标）
输出标准 RSS 2.0，按发布日期倒序。
"""
import re
import html
import sys
import time
import argparse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import format_datetime
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

SITE = "https://jxgccl.mat-test.com"
LIST_FEED = SITE + "/rss/latest.xml"
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def http_get(url, timeout=30, retries=2):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:  # noqa: BLE001
            last = e
            if i < retries - 1:
                time.sleep(1.5)
    raise last


def clean_text(t):
    """多层转义 + 正常/畸形 HTML 标签统一清理（不补空格，避免 Li/CF x）"""
    if not t:
        return ""
    for _ in range(6):
        nt = html.unescape(t)
        if nt == t:
            break
        t = nt
    t = re.sub(r"</?[a-zA-Z][^<>]{0,20}>", "", t)      # <sub>xxx</sub>
    t = re.sub(r"</?[a-zA-Z][^<>]{0,20}<", "", t)      # 畸形 <sub< / </sub<
    t = t.replace("<", "").replace(">", "")
    return re.sub(r"[ \t\r\n]+", " ", t).strip()


def strip_html_keep_para(t):
    if not t:
        return ""
    for _ in range(5):
        nt = html.unescape(t)
        if nt == t:
            break
        t = nt
    t = re.sub(r"</?(?:p|br|div)[^<>]{0,20}<", "", t)
    t = re.sub(r"(?i)<br\s*/?>", "\n", t)
    t = re.sub(r"(?i)</p\s*>", "\n\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = t.replace("<", "").replace(">", "")
    t = html.unescape(t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def parse_list_feed(xml_text):
    root = ET.fromstring(xml_text.encode("utf-8"))
    ns = {
        "rss": "http://purl.org/rss/1.0/",
        "dc": "http://purl.org/dc/elements/1.1/",
        "prism": "http://prismstandard.org/namespaces/basic/2.0/",
    }
    items = []
    for it in root.findall("rss:item", ns):
        link = it.findtext("rss:link", default="", namespaces=ns)
        doi = it.findtext("prism:doi", default="", namespaces=ns)
        if not link and doi:
            link = f"{SITE}/article/doi/{doi}"
        items.append(dict(
            link=link,
            doi=doi,
            title_raw=it.findtext("rss:title", default="", namespaces=ns),
            desc_raw=it.findtext("rss:description", default="", namespaces=ns),
            source=it.findtext("dc:source", default="", namespaces=ns),
            volume=it.findtext("prism:volume", default="", namespaces=ns),
            number=it.findtext("prism:number", default="", namespaces=ns),
            pages=it.findtext("prism:startin gPage", default="", namespaces=ns),
        ))
    return items


def meta_of(page_html):
    """兼容属性顺序的 <meta> 解析"""
    out = {}
    for tag in re.finditer(r"<meta\b[^>]*>", page_html, re.I):
        s = tag.group(0)
        nm = re.search(r'name\s*=\s*"([^"]*)"', s, re.I)
        cm = re.search(r'content\s*=\s*"([^"]*)"', s, re.I)
        if nm and cm and nm.group(1).startswith("citation_"):
            out.setdefault(nm.group(1), []).append(cm.group(1))
    return out


def abstract_from_page(page_html):
    """从文章页 div.abstract-cn 提取中文摘要，保留 sub/sup 上下标"""
    m = re.search(r'<div class="abstract-cn">(.*?)<div class="abstract-en">', page_html, re.S)
    if not m:
        return ""
    blk = m.group(1)
    blk = re.sub(r"<b>\s*摘要[:：]?\s*</b>", "", blk, flags=re.I)
    blk = re.sub(r"<p[^>]*>\s*(?:&nbsp;|\s)*</p>", "", blk, flags=re.I)
    blk = re.sub(r"<(?:div|script|style|img)[^>]*>", "", blk, flags=re.I)
    blk = re.sub(r"</(?:div|script|style|img)>", "", blk, flags=re.I)
    blk = re.sub(r"[ \t\r\n]+", " ", blk)
    blk = re.sub(r"</?[a-zA-Z][^<>]{0,18}<", "", blk)   # 仅清理畸形 <sub< 形式
    return blk.strip()


def fetch_article(e):
    """抓单篇文章详情页，返回补全后的条目"""
    page, m = "", {}
    for attempt in range(3):
        try:
            page = http_get(e["link"], timeout=30)
            m = meta_of(page)
        except Exception as ex:  # noqa: BLE001
            print(f"  [retry{attempt}] {e['link']} -> {ex}", file=sys.stderr, flush=True)
            time.sleep(1.5)
            continue
        if (m.get("citation_publication_date") or m.get("citation_online_date")
                or m.get("citation_date")) and m.get("citation_title"):
            break
        time.sleep(1)
    if not page:
        print(f"  [skip] {e['link']} 抓取失败", file=sys.stderr, flush=True)
        return None

    title = clean_text((m.get("citation_title") or [e["title_raw"]])[0])
    authors = [clean_text(a) for a in (m.get("citation_author") or []) if clean_text(a)]
    date = ((m.get("citation_publication_date") or [""])[0]
            or (m.get("citation_online_date") or [""])[0]
            or (m.get("citation_date") or [""])[0])
    kw = clean_text((m.get("citation_keywords") or [""])[0]).rstrip("，, ")
    vol = (m.get("citation_volume") or [e["volume"]])[0]
    num = (m.get("citation_issue") or [e["number"]])[0]
    fp = (m.get("citation_firstpage") or [""])[0]
    lp = (m.get("citation_lastpage") or [""])[0]
    pages = f"{fp}-{lp}" if fp and lp else (fp or e["pages"] or "")
    abstract = abstract_from_page(page) or strip_html_keep_para(e["desc_raw"])
    abstract = re.sub(r"机械工程材料\.?\s*\d{4}\s*\d+\s*\(\d+\)\s*[:：]\s*[\d\-–]+\s*\.?\s*$",
                      "", abstract).strip()

    pub_dt = None
    if re.match(r"^\d{4}-\d{2}-\d{2}", date):
        pub_dt = datetime.strptime(date[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)

    return dict(title=title or clean_text(e["title_raw"]), link=e["link"], doi=e["doi"],
                authors=authors, date=date, pub_dt=pub_dt, keywords=kw,
                volume=vol, number=num, pages=pages, abstract=abstract)


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def write_rss(items, out, site=SITE, title="机械工程材料 (Materials for Mechanical Engineering)"):
    now = datetime.now(timezone.utc)
    L = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:prism="http://prismstandard.org/namespaces/basic/2.0/">',
        "  <channel>",
        f"    <title>{esc(title)}</title>",
        f"    <link>{esc(site)}/</link>",
        f"    <atom:link href=\"{esc(site)}/feed.xml\" rel=\"self\" type=\"application/rss+xml\"/>",
        "    <description>《机械工程材料》最新论文（优先在线发表 + 当期目录），由官网元数据整理</description>",
        "    <language>zh-CN</language>",
        f"    <lastBuildDate>{format_datetime(now)}</lastBuildDate>",
        "    <generator>journal-rss / feedgen_jxgccl</generator>",
    ]
    for it in items:
        L.append("    <item>")
        L.append(f"      <title>{esc(it['title'])}</title>")
        L.append(f"      <link>{esc(it['link'])}</link>")
        L.append(f'      <guid isPermaLink="true">{esc(it["link"])}</guid>')
        if it["pub_dt"]:
            L.append(f"      <pubDate>{format_datetime(it['pub_dt'])}</pubDate>")
        if it["authors"]:
            L.append(f"      <dc:creator>{esc(', '.join(it['authors']))}</dc:creator>")
        if it["doi"]:
            L.append(f"      <prism:doi>{esc(it['doi'])}</prism:doi>")
        if it["volume"]:
            L.append(f"      <prism:volume>{esc(it['volume'])}</prism:volume>")
        if it["number"]:
            L.append(f"      <prism:number>{esc(it['number'])}</prism:number>")
        body = []
        if it["authors"]:
            body.append("<p><b>作者：</b>" + esc(", ".join(it["authors"])) + "</p>")
        meta_line = []
        if it["volume"] and it["number"]:
            meta_line.append(f"{it['volume']}卷{it['number']}期")
        if it["pages"]:
            meta_line.append(f"页 {it['pages']}")
        if it["doi"]:
            meta_line.append("DOI " + it["doi"])
        if meta_line:
            body.append("<p><b>出处：</b>" + esc("，".join(meta_line)) + "</p>")
        if it["keywords"]:
            body.append("<p><b>关键词：</b>" + esc(it["keywords"]) + "</p>")
        if it["abstract"]:
            body.append("<p>" + it["abstract"].replace("]]>", "]]&gt;") + "</p>")
        L.append("      <description><![CDATA[" + "".join(body) + "]]></description>")
        L.append("    </item>")
    L += ["  </channel>", "</rss>", ""]
    open(out, "w", encoding="utf-8").write("\n".join(L))


def main():
    ap = argparse.ArgumentParser(description="机械工程材料 RSS 生成")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--out", default="feeds/jxgccl.xml")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()

    entries = parse_list_feed(http_get(LIST_FEED, timeout=40))
    print(f"官方 feed 条目 {len(entries)}，取前 {min(a.limit, len(entries))} 条", flush=True)
    todo = entries[:a.limit]

    results = []
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futs = {pool.submit(fetch_article, e): e for e in todo}
        for fut in as_completed(futs):
            try:
                r = fut.result()
            except Exception as ex:  # noqa: BLE001
                print(f"  [err] {ex}", file=sys.stderr, flush=True)
                continue
            if r:
                results.append(r)
                print(f"  {r['date'] or '(无日期)'}  {r['title'][:42]}", flush=True)

    results.sort(key=lambda x: (x["pub_dt"] is not None,
                                x["pub_dt"] or datetime.min.replace(tzinfo=timezone.utc)),
                 reverse=True)
    write_rss(results, a.out)
    dated = sum(1 for r in results if r["pub_dt"])
    print(f"写入 {a.out}：{len(results)} 条（其中 {dated} 条有发布日期）", flush=True)
    if not results:
        sys.exit(1)


if __name__ == "__main__":
    main()
