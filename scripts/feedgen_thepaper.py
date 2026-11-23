#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成澎湃新闻频道页的 RSS 源（官方 JSON 接口 + 文章页 meta description 取摘要）。

用法：
  python feedgen_thepaper.py --channel 168153 --name "澎湃新闻·上海书评" \
      --site https://www.thepaper.cn --limit 30 --out feeds/thepaper-shuping.xml
"""
import argparse, json, re, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from email.utils import formatdate
from xml.sax.saxutils import escape

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
API = "https://api.thepaper.cn/contentapi/nodeCont/getByChannelId"


def get_text(url, headers=None, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:
            print(f"  [warn] {url} 第{i+1}次失败: {str(e)[:60]}", file=sys.stderr)
            time.sleep(2 + i * 2)
    return None


def fetch_list(channel, want):
    items, page = [], 1
    hdr = {"User-Agent": UA, "Content-Type": "application/json",
           "Referer": "https://www.thepaper.cn/"}
    payload = {"channelId": str(channel), "pageSize": 20}
    cursor = None
    while len(items) < want and page <= 8:
        if cursor:
            payload["startTime"] = cursor
        body = json.dumps(payload).encode()
        raw = None
        for i in range(3):
            try:
                req = urllib.request.Request(API, data=body, headers=hdr, method="POST")
                with urllib.request.urlopen(req, timeout=25) as r:
                    raw = r.read().decode("utf-8", "ignore")
                break
            except Exception as e:
                print(f"  [warn] 列表第{page}页失败: {str(e)[:60]}", file=sys.stderr)
                time.sleep(2 + i * 2)
        if not raw:
            break
        try:
            data = json.loads(raw)["data"]
        except Exception:
            break
        for it in data.get("list") or []:
            cid = str(it.get("contId") or "")
            if not cid:
                continue
            items.append({
                "id": cid,
                "title": it.get("name") or "",
                "ts": int(it.get("pubTimeLong") or 0),
                "link": f"https://www.thepaper.cn/newsDetail_forward_{cid}",
            })
        cursor = data.get("startTime")
        if not data.get("hasNext") or not cursor:
            break
        page += 1
        time.sleep(0.4)
    seen, out = set(), []
    for it in items:
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        out.append(it)
    out.sort(key=lambda x: x["ts"], reverse=True)
    return out[:want]


def fetch_abstract(item):
    html = get_text(item["link"])
    if not html:
        return item
    for pat in (r'<meta name="description" content="([^"]*)"',
                r'<meta property="og:description" content="([^"]*)"'):
        m = re.search(pat, html)
        if m and len(m.group(1)) > 40:
            item["desc"] = re.sub(r"\s+", " ", m.group(1)).strip()
            break
    m = re.search(r'<meta property="og:image" content="([^"]*)"', html)
    if m:
        item["pic"] = m.group(1)
    return item


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", required=True, help="频道 ID，如 168153")
    ap.add_argument("--name", required=True, help="频道名，写进 feed 标题")
    ap.add_argument("--site", default="https://www.thepaper.cn")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    items = fetch_list(args.channel, args.limit)
    print(f"频道 {args.channel} 候选 {len(items)} 条，抓取摘要…", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        items = list(ex.map(fetch_abstract, items))
    got = sum(1 for i in items if i.get("desc"))
    print(f"摘要成功 {got}/{len(items)}", file=sys.stderr)
    if items:
        newest = max(i["ts"] for i in items)
        items = [i for i in items if newest - i["ts"] <= 540 * 86400000]

    rows = []
    for it in items:
        ts = it["ts"] / 1000 if it["ts"] else time.time()
        pub = formatdate(ts, usegmt=True).replace("+0000", "+0800")
        body_html = ""
        if it.get("pic"):
            body_html += f'<p><img src="{escape(it["pic"])}" /></p>'
        txt = (it.get("desc") or "").strip()
        if txt:
            body_html += f"<p>{escape(txt)}</p>"
        body_html = body_html.replace("]]>", "]] >")
        rows.append(f"""    <item>
      <title>{escape(it['title'])}</title>
      <link>{escape(it['link'])}</link>
      <guid isPermaLink="true">{escape(it['link'])}</guid>
      <pubDate>{pub}</pubDate>
      <description><![CDATA[{body_html}]]></description>
    </item>""")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>{escape(args.name)}</title>
    <link>{args.site}/channel_{args.channel}</link>
    <description>{escape(args.name)} 最新文章</description>
    <language>zh-cn</language>
    <lastBuildDate>{formatdate(time.time(), usegmt=True)}</lastBuildDate>
    <generator>feedgen_thepaper.py</generator>
{chr(10).join(rows)}
  </channel>
</rss>
"""
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(xml)
    print(f"已生成 {args.out}，条目 {len(rows)}", file=sys.stderr)


if __name__ == "__main__":
    main()
