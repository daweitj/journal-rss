# journal-rss

几本期刊的最新论文 RSS 源，GitHub Actions 每天 10:00（北京时间）重新生成，产物在 `feeds/`。

## 订阅地址

| 期刊 | 地址 |
|---|---|
| Accounts of Materials Research | https://daweitj.github.io/journal-rss/feeds/amr.xml |
| Chemical Reviews | https://daweitj.github.io/journal-rss/feeds/chemrev.xml |
| Journal of Chemical Education | https://daweitj.github.io/journal-rss/feeds/jce.xml |
| 物理学进展 | https://daweitj.github.io/journal-rss/feeds/physics-progress.xml |
| 中国工程科学 | https://daweitj.github.io/journal-rss/feeds/sscae.xml |
| 电源技术 | https://daweitj.github.io/journal-rss/feeds/dyjs.xml |
| 化学进展 | https://daweitj.github.io/journal-rss/feeds/progchem.xml |
| 功能材料 | https://daweitj.github.io/journal-rss/feeds/gncl.xml |
| 材料导报 | https://daweitj.github.io/journal-rss/feeds/mater-rep.xml |
| 金属学报 | https://daweitj.github.io/journal-rss/feeds/ams.xml |

一次导入全部：`feeds/subscriptions.opml`

## 数据来源

- ACS 三本（AMR、Chemical Reviews、Journal of Chemical Education）：官网有 Cloudflare 拦截，改用 Crossref 公开元数据（ISSN 2643-6728 / 0009-2665 / 0021-9584）。
- 物理学进展：南京大学 pip.nju.edu.cn，无官方 RSS，走 sitemap + 文章页 citation 元信息。
- 中国工程科学：engineering.org.cn/sscae，同上。
- 电源技术：manu70.magtech.com.cn/dyjs，同上（sitemap 在 /dyjs/sitemap-index.xml）。
- 化学进展：hxjz.magtechjournal.com，同上（sitemap 由 robots.txt 给出：/sitemaps/sitemap-index.xml）；只覆盖正式发表。
- 功能材料：gncl.cn，无 sitemap 可用（索引里的 loc 有拼写错误），改抓首页当期目录 + 文章页 citation 元信息。
- 材料导报：mater-rep.com，无 sitemap，抓首页当期目录；摘要写在正文里，脚本从“摘要 … 关键词/服务”之间抽取。
- 金属学报：ams.org.cn，sitemap 分片的 id 与时间不同序，改抓首页 + 近三期期目录。

## 说明

- 内容为题录 + 摘要（有则带），无正文全文。
- 单本抓取失败不影响其他几本。
