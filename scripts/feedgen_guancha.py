#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成观察者网（guancha.cn）首页的 RSS 源。

站点已无官方 RSS（/rss/ 302 到首页），改为抓首页文章列表 + 详情页元信息。

用法：
  python feedgen_guancha.py --site https://www.guancha.cn \
      --list-url "https://www.guancha.cn/" --limit 30 --out feeds/guancha.xml
"""
import argparse, re, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from xml.sax.saxutils import escape

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

ART_RE = re.compile(r'href="(/[\w-]+/20\d\d_\d\d_\d\d_\d+\.shtml)')


def rfc822(ts):
    return time.strftime("%a, %d %b %Y %H:%M:%S +0800", time.gmtime(ts + 8 * 3600))


def get_text(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:
            print(f"  [warn] {url} 第{i+1}次失败: {str(e)[:60]}", file=sys.stderr)
            time.sleep(2 + i * 2)
    return None


def collect_list(list_urls):
    links, seen = [], set()
    for lu in list_urls:
        html = get_text(lu)
        if not html:
            continue
        for path in ART_RE.findall(html):
            if path in seen:
                continue
            seen.add(path)
            links.append(path)
    return links


def parse_article(base, path):
    url = base.rstrip("/") + path
    html = get_text(url)
    if not html:
        return None
    title_m = re.search(r"<title>(.*?)</title>", html, re.S)
    title = re.sub(r"\s+", " ", title_m.group(1)).strip() if title_m else ""
    desc_m = re.search(r'<meta\s+name="Description"\s+content="([^"]*)"', html, re.I)
    desc = re.sub(r"\s+", " ", desc_m.group(1)).strip() if desc_m else ""
    ts = 0
    time_m = re.search(r'<div class="time fix">\s*<span>(20\d\d-\d\d-\d\d \d\d:\d\d(?::\d\d)?)</span>', html)
    pub_m = re.search(r'"pubDate":"(20\d\d-\d\d-\d\d \d\d:\d\d(?::\d\d)?)"', html)
    raw_time = time_m.group(1) if time_m else (pub_m.group(1) if pub_m else "")
    if raw_time:
        try:
            fmt = "%Y-%m-%d %H:%M:%S" if raw_time.count(":") == 2 else "%Y-%m-%d %H:%M"
            ts = time.mktime(time.strptime(raw_time, fmt)) - 8 * 3600
        except Exception:
            ts = 0
    if not ts:
        d = re.search(r"/(20\d\d)_(\d\d)_(\d\d)_", path)
        if d:
            ts = time.mktime(time.strptime(f"{d.group(1)}-{d.group(2)}-{d.group(3)}", "%Y-%m-%d")) - 8 * 3600
    pic_m = re.search(r'"image":\["(https?://[^"]+)"', html)
    pic = pic_m.group(1) if pic_m else ""
    if not title:
        return None
    return {"title": title, "link": url, "ts": ts, "desc": desc, "pic": pic}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="https://www.guancha.cn")
    ap.add_argument("--list-url", default="https://www.guancha.cn/")
    ap.add_argument("--name", default="观察者网")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    paths = collect_list([u.strip() for u in args.list_url.split(",") if u.strip()])
    print(f"首页候选 {len(paths)} 篇，抓取详情…", file=sys.stderr)
    paths = paths[: args.limit * 2]
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        items = [x for x in ex.map(lambda p: parse_article(args.site, p), paths) if x]
    items.sort(key=lambda x: x["ts"], reverse=True)
    items = items[: args.limit]
    print(f"成功 {len(items)} 篇，含摘要 {sum(1 for i in items if i['desc'])} 篇", file=sys.stderr)

    rows = []
    for it in items:
        body = ""
        if it["pic"]:
            body += f'<p><img src="{escape(it["pic"])}" /></p>'
        if it["desc"]:
            body += f"<p>{escape(it['desc'])}</p>"
        body = body.replace("]]>", "]] >")
        rows.append(f"""    <item>
      <title>{escape(it['title'])}</title>
      <link>{escape(it['link'])}</link>
      <guid isPermaLink="true">{escape(it['link'])}</guid>
      <pubDate>{rfc822(it['ts'])}</pubDate>
      <description><![CDATA[{body}]]></description>
    </item>""")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>{escape(args.name)}</title>
    <link>{args.site}</link>
    <description>{escape(args.name)} 首页最新文章</description>
    <language>zh-cn</language>
    <lastBuildDate>{rfc822(time.time())}</lastBuildDate>
    <generator>feedgen_guancha.py</generator>
{chr(10).join(rows)}
  </channel>
</rss>
"""
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(xml)
    print(f"已生成 {args.out}，条目 {len(rows)}", file=sys.stderr)


if __name__ == "__main__":
    main()
