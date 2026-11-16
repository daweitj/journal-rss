# journal-rss

六本期刊的最新论文 RSS 源，GitHub Actions 每天 02:00 UTC（北京时间 10:00）重新生成，产物在 `feeds/`。

## 订阅地址

| 期刊 | 地址 |
|---|---|
| Accounts of Materials Research | https://daweitj.github.io/journal-rss/feeds/amr.xml |
| Chemical Reviews | https://daweitj.github.io/journal-rss/feeds/chemrev.xml |
| Journal of Chemical Education | https://daweitj.github.io/journal-rss/feeds/jce.xml |
| 物理学进展 | https://daweitj.github.io/journal-rss/feeds/physics-progress.xml |
| 中国工程科学 | https://daweitj.github.io/journal-rss/feeds/sscae.xml |
| 电源技术 | https://daweitj.github.io/journal-rss/feeds/dyjs.xml |

一次导入全部：`feeds/subscriptions.opml`

## 数据来源

- ACS 三本（AMR、Chemical Reviews、Journal of Chemical Education）：官网被 Cloudflare 拦截，改用 Crossref 公开元数据。
- 物理学进展：南京大学 pip.nju.edu.cn，无官方 RSS，走 sitemap + 文章页 citation 元信息。
- 中国工程科学：engineering.org.cn/sscae，同上。
- 电源技术：manu70.magtech.com.cn/dyjs，同上（sitemap 在 /dyjs/sitemap-index.xml）。

## 说明

- 内容为题录 + 摘要（有则带），没有正文全文。
- 每本期刊在 workflow 里是独立一步，单本失败不影响其他。
