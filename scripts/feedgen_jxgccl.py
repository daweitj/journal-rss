#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""《机械工程材料》(Materials for Mechanical Engineering) 最新论文 RSS 生成器。

站点 https://jxgccl.mat-test.com 属仁和汇智 RHHz 平台，页面 JS 渲染、无 sitemap。
官网 RSS(/rss/latest.xml) 能拿到条目和 DOI，但 dc:date/prism:publicationDate 全空,
标题还被多层转义破坏，不能直接给阅读器。

做法：官网 RSS 作条目索引 -> 串行抓 /article/doi/<doi> 取 citation_publication_date、
标题、作者、关键词，摘要优先取 div.abstract-cn（保留 sub/sup）-> 输出 RSS 2.0。
抓不到的条目退回官方数据不丢；日期依次从上一版 feed、feeds/jxgccl-dates.json 继承。
该站对境外/连续请求会 403 或超时，故固定串行 + 限预算 + 日期持久化。
"""
import json
import os
import re
import html
import sys
import time
import argparse
import traceback
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import format_datetime, parsedate_to_datetime
from datetime import datetime, timezone

SITE = "https://jxgccl.mat-test.com"
LIST_FEED = SITE + "/rss/latest.xml"
ERR_FILE = "feeds/jxgccl-error.txt"
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def http_get(url, timeout=25, retries=2):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:
            last = e
            if i < retries - 1:
                time.sleep(2)
    raise last


def clean_text(t):
    if not t:
        return ""
    for _ in range(6):
        nt = html.unescape(t)
        if nt == t:
            break
        t = nt
    t = re.sub(r"</?[a-zA-Z][^<>]{0,20}>", "", t)
    t = re.sub(r"</?[a-zA-Z][^<>]{0,20}<", "", t)
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
            link=link, doi=doi,
            title_raw=it.findtext("rss:title", default="", namespaces=ns),
            desc_raw=it.findtext("rss:description", default="", namespaces=ns),
            volume=it.findtext("prism:volume", default="", namespaces=ns),
            number=it.findtext("prism:number", default="", namespaces=ns),
            pages=it.findtext("prism:startingPage", default="", namespaces=ns),
        ))
    return items


def meta_of(page_html):
    out = {}
    for tag in re.finditer(r"<meta\b[^>]*>", page_html, re.I):
        s = tag.group(0)
        nm = re.search(r'name\s*=\s*"([^"]*)"', s, re.I)
        cm = re.search(r'content\s*=\s*"([^"]*)"', s, re.I)
        if nm and cm and nm.group(1).startswith("citation_"):
            out.setdefault(nm.group(1), []).append(cm.group(1))
    return out


def abstract_from_page(page_html):
    m = re.search(r'<div class="abstract-cn">(.*?)<div class="abstract-en">', page_html, re.S)
    if not m:
        return ""
    blk = m.group(1)
    blk = re.sub(r"<b>\s*摘要[:：]?\s*</b>", "", blk, flags=re.I)
    blk = re.sub(r"<p[^>]*>\s*(?:&nbsp;|\s)*</p>", "", blk, flags=re.I)
    blk = re.sub(r"<(?:div|script|style|img)[^>]*>", "", blk, flags=re.I)
    blk = re.sub(r"</(?:div|script|style|img)>", "", blk, flags=re.I)
    blk = re.sub(r"[ \t\r\n]+", " ", blk)
    blk = re.sub(r"</?[a-zA-Z][^<>]{0,18}<", "", blk)
    return blk.strip()


def fallback_entry(e):
    return dict(title=clean_text(e["title_raw"]), link=e["link"], doi=e["doi"],
                authors=[], date="", pub_dt=None, keywords="",
                volume=e["volume"], number=e["number"], pages=e["pages"],
                abstract=strip_html_keep_para(e["desc_raw"]))


def fetch_article(e, timeout=25, deadline=None):
    page, m = "", {}
    for attempt in range(2):
        if deadline and time.time() > deadline:
            print(f"  [budget] 预算用尽，{e['doi']} 退回官方数据", file=sys.stderr, flush=True)
            return fallback_entry(e)
        try:
            page = http_get(e["link"], timeout=timeout, retries=1)
            m = meta_of(page)
        except Exception as ex:
            print(f"  [retry{attempt}] {e['link']} -> {ex}", file=sys.stderr, flush=True)
            time.sleep(1)
            continue
        if (m.get("citation_publication_date") or m.get("citation_online_date")
                or m.get("citation_date")) and m.get("citation_title"):
            break
        time.sleep(1)
    if not page or not m.get("citation_title"):
        print(f"  [fallback] {e['link']} 详情页不可用", file=sys.stderr, flush=True)
        return fallback_entry(e)

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


def load_prev(path):
    d = {}
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return d
    for it in root.findall(".//item"):
        link = (it.findtext("link") or "").strip()
        pd_txt = it.findtext("pubDate")
        if not (link and pd_txt):
            continue
        try:
            dt = parsedate_to_datetime(pd_txt.strip()).astimezone(timezone.utc)
            d[link] = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        except Exception:
            continue
    return d


def load_seed(path):
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return {k: datetime.strptime(v, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                for k, v in raw.items()}
    except Exception:
        return {}


def save_seed(path, items, seed):
    merged = dict(seed)
    for it in items:
        if it["pub_dt"]:
            merged[it["link"]] = it["pub_dt"]
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({k: v.strftime("%Y-%m-%d") for k, v in sorted(merged.items())},
                      f, ensure_ascii=False, indent=1)
    except Exception as e:
        print(f"  [warn] 日期种子写入失败: {e}", file=sys.stderr, flush=True)


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
    ap.add_argument("--workers", type=int, default=1, help="保留参数；该站对并发敏感，实际固定串行")
    ap.add_argument("--timeout", type=int, default=25, help="单页超时秒数")
    ap.add_argument("--budget", type=int, default=780, help="详情页抓取总预算秒数")
    a = ap.parse_args()

    entries = parse_list_feed(http_get(LIST_FEED, timeout=45, retries=5))
    print(f"官方 feed 条目 {len(entries)}，取前 {min(a.limit, len(entries))} 条", flush=True)
    todo = entries[:a.limit]
    prev = load_prev(a.out)
    if prev:
        print(f"上一次产物可复用日期 {len(prev)} 条", flush=True)
    seed_path = os.path.join(os.path.dirname(os.path.abspath(a.out)), "jxgccl-dates.json")
    seed = load_seed(seed_path)
    if seed:
        print(f"日期种子 {len(seed)} 条（{seed_path}）", flush=True)

    deadline = time.time() + a.budget
    results = []
    for e in todo:
        r = fetch_article(e, a.timeout, deadline)
        if r["pub_dt"] is None:
            for src in (prev, seed):
                if r["link"] in src:
                    r["pub_dt"] = src[r["link"]]
                    r["date"] = r["pub_dt"].strftime("%Y-%m-%d")
                    print(f"  (沿用已有日期) {r['date']}  {r['title'][:36]}", flush=True)
                    break
            else:
                print(f"  (无日期) {r['title'][:42]}", flush=True)
        else:
            print(f"  {r['date']}  {r['title'][:42]}", flush=True)
        results.append(r)

    results.sort(key=lambda x: x["pub_dt"] or datetime.max.replace(tzinfo=timezone.utc), reverse=True)
    write_rss(results, a.out)
    save_seed(seed_path, results, seed)
    if os.path.exists(ERR_FILE):
        os.remove(ERR_FILE)
    dated = sum(1 for r in results if r["pub_dt"])
    print(f"写入 {a.out}：{len(results)} 条（其中 {dated} 条有发布日期）", flush=True)
    if not results:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException:
        msg = traceback.format_exc()
        print(msg, file=sys.stderr, flush=True)
        try:
            with open(ERR_FILE, "w", encoding="utf-8") as f:
                f.write(msg)
        except Exception:
            pass
        sys.exit(1)
