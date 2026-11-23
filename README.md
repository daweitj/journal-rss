# journal-rss

一批期刊 / 频道的最新内容 RSS 源。GitHub Actions 每天 10:00（北京时间）自动重跑，产物在 `feeds/`。

## 订阅地址

| 期刊 / 栏目 | 地址 |
|---|---|
| Accounts of Materials Research | https://daweitj.github.io/journal-rss/feeds/amr.xml |
| Chemical Reviews | https://daweitj.github.io/journal-rss/feeds/chemrev.xml |
| Journal of Chemical Education | https://daweitj.github.io/journal-rss/feeds/jce.xml |
| Electrochemical Energy Reviews | https://daweitj.github.io/journal-rss/feeds/eer.xml |
| Journal of Materials Science | https://daweitj.github.io/journal-rss/feeds/jms.xml |
| MRS Bulletin | https://daweitj.github.io/journal-rss/feeds/mrsb.xml |
| Progress in Additive Manufacturing | https://daweitj.github.io/journal-rss/feeds/piam.xml |
| 物理学进展 | https://daweitj.github.io/journal-rss/feeds/physics-progress.xml |
| 中国工程科学 | https://daweitj.github.io/journal-rss/feeds/sscae.xml |
| 电源技术 | https://daweitj.github.io/journal-rss/feeds/dyjs.xml |
| 化学进展 | https://daweitj.github.io/journal-rss/feeds/progchem.xml |
| 功能材料 | https://daweitj.github.io/journal-rss/feeds/gncl.xml |
| 材料导报 | https://daweitj.github.io/journal-rss/feeds/mater-rep.xml |
| 金属学报 | https://daweitj.github.io/journal-rss/feeds/ams.xml |
| 机械工程材料 | https://daweitj.github.io/journal-rss/feeds/jxgccl.xml |
| 澎湃新闻·上海书评 | https://daweitj.github.io/journal-rss/feeds/thepaper-shuping.xml |

官方 RSS（不入仓库，直接订阅）：

- Small — https://onlinelibrary.wiley.com/feed/16136829/most-recent
- Batteries & Supercaps — https://chemistry-europe.onlinelibrary.wiley.com/feed/25666223/most-recent

一次导入全部：`feeds/subscriptions.opml`

## 数据来源

- ACS 三本（AMR、Chemical Reviews、Journal of Chemical Education）：官网有 Cloudflare 拦截，改用 Crossref 公开元数据（ISSN 2643-6728 / 0009-2665 / 0021-9584）。
- 物理学进展：pip.nju.edu.cn，无官方 RSS，走 sitemap + 文章页 citation 元信息。
- 中国工程科学：engineering.org.cn/sscae，同上。
- 电源技术：manu70.magtech.com.cn/dyjs，同上（sitemap 在 /dyjs/sitemap-index.xml）。
- 化学进展：hxjz.magtechjournal.com，同上（/sitemaps/sitemap-index.xml）；只覆盖正式发表。
- 功能材料：gncl.cn 的 sitemap 索引里 loc 有拼写错误，改抓首页当期目录 + 文章页元信息。
- 材料导报：mater-rep.com 无 sitemap，抓首页当期目录，摘要从正文“摘要 … 关键词/服务”之间抽取。
- 金属学报：ams.org.cn 的 sitemap 分片 id 与时间不同序，改抓首页 + 近三期期目录。
- Springer 四本：`search.rss` 会 303 到登录页（阅读器报“不包含 RSS 订阅源”），改抓期刊文章列表 + 文章页 `citation_*` / `dc.description`。MRS Bulletin 的 DOI 前缀是 `10.1557` 而非 `10.1007`。
- 机械工程材料：jxgccl.mat-test.com（仁和汇智 RHHz 平台，页面 JS 模板渲染、无 sitemap）。官网自带 RSS 在 `/rss/latest.xml`，但 `dc:date` 与 `prism:publicationDate` 为空、且化学式标题被多层转义破坏，不适用于阅读器。改为以其条目列表为索引，逐条抓文章页取 `citation_publication_date`、作者、`div.abstract-cn` 摘要，生成标准 RSS 2.0。
- 澎湃新闻·上海书评：thepaper.cn/channel_168153，走官方 JSON 接口 `api.thepaper.cn/contentapi/nodeCont/getByChannelId`（`startTime` 游标翻页），摘要取文章页 `meta description`。

## 加新期刊

改 `config/journals.json` 追加一条（`label` / `script` / `out` / `args`），workflow 会自动跑，不用动 yml。

- 有 sitemap 的站：`feedgen_journal.py --site … --sitemap … --article-pattern …`
- 只有列表页的站：`feedgen_journal.py --site … --list-url … --link-pattern …`
- 走 Crossref 的刊：`feedgen_crossref.py --issn …`
- 澎湃频道：`feedgen_thepaper.py --channel <频道ID>`
- 自带残缺 RSS 的站（日期/编码有问题）：`feedgen_jxgccl.py --limit 30 --workers 4`

## 说明

- 内容为题录 + 摘要（有则带），无正文全文。
- 单本抓取失败不影响其他几本（`build_all.py` 逐项捕获异常）。
