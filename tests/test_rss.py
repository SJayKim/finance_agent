from datetime import timezone

from app.collector.rss import RssConnector, parse_feed
from app.pipeline.dedup import near_duplicate_groups

# description는 HTML이 엔티티로 인코딩된 채 온다(실제 피드와 동일). guid 우선.
CT_XML = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
<item>
  <title>Bitcoin tops $100K for the first time</title>
  <link>https://cointelegraph.com/news/btc-100k</link>
  <guid>ct-1</guid>
  <description>&lt;p&gt;BTC &lt;b&gt;surges&lt;/b&gt; past 100,000.&lt;/p&gt;</description>
  <pubDate>Tue, 19 Jun 2026 00:30:00 GMT</pubDate>
</item>
<item>
  <title>No guid item falls back to link</title>
  <link>https://cointelegraph.com/news/no-guid</link>
  <description>plain text</description>
  <pubDate>not-a-date</pubDate>
</item>
</channel></rss>"""

CD_XML = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
<item>
  <title>Bitcoin tops $100K for the first time</title>
  <link>https://www.coindesk.com/markets/btc-100k</link>
  <guid>cd-1</guid>
  <description>BTC hits six figures.</description>
  <pubDate>Tue, 19 Jun 2026 00:45:00 GMT</pubDate>
</item>
</channel></rss>"""

DC_XML = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
<item>
  <title>Solana outage halts trading for hours</title>
  <link>https://decrypt.co/sol-outage</link>
  <guid>dc-1</guid>
  <description>Validators stalled.</description>
  <pubDate>Tue, 19 Jun 2026 01:00:00 GMT</pubDate>
</item>
</channel></rss>"""


def test_parse_feed_extracts_items() -> None:
    items = parse_feed("cointelegraph", CT_XML)
    assert len(items) == 2
    assert items[0]["external_id"] == "ct-1"
    assert items[0]["source"] == "cointelegraph"


def test_parse_feed_external_id_falls_back_to_link() -> None:
    items = parse_feed("cointelegraph", CT_XML)
    assert items[1]["external_id"] == "https://cointelegraph.com/news/no-guid"


def test_normalize_strips_html_and_parses_pubdate_utc() -> None:
    conn = RssConnector()
    doc = conn.normalize(parse_feed("cointelegraph", CT_XML)[0])
    assert doc.summary == "BTC surges past 100,000."
    assert doc.body is None  # P5: RSS 본문 grounding 불가
    assert doc.lang == "en"
    assert doc.published_at is not None
    assert doc.published_at.tzinfo == timezone.utc
    assert doc.published_at.hour == 0 and doc.published_at.minute == 30


def test_normalize_handles_bad_pubdate() -> None:
    conn = RssConnector()
    doc = conn.normalize(parse_feed("cointelegraph", CT_XML)[1])
    assert doc.published_at is None
    assert doc.summary == "plain text"


def test_cross_source_syndication_dedup() -> None:
    # 같은 와이어 헤드라인이 두 소스에 → SimHash dedup이 한 군집으로 묶는다.
    conn = RssConnector()
    docs = []
    for source, xml in (("cointelegraph", CT_XML), ("coindesk", CD_XML), ("decrypt", DC_XML)):
        for payload in parse_feed(source, xml):
            docs.append(conn.normalize(payload))
    items = [(i, d.title) for i, d in enumerate(docs) if d.title]
    groups = near_duplicate_groups(items)
    assert any(len(g) == 2 for g in groups)
