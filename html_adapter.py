#!/bin/env python
import asyncio
from dateutil.parser import parse
import aiohttp
import lxml
from lxml import html as lhtml
from lxml.etree import XPath, tostring
from lxml.cssselect import CSSSelector
from io import BytesIO
from feedparser.util import FeedParserDict
import bleach
import mimetypes
import re
import json


class HTMLAdapter:
    def __init__(self, url, item_selector, selectors):
        self.url = url
        self.item_selector = item_selector
        self.selectors = selectors
    def __repr__(self):
        return f"HTMLAdapter({self.url})"

    async def __call__(self, session):
        parsed = {
            "url": self.url,
            "feed": FeedParserDict(title="HTMLAdapter Feed"),
            "entries": [],
        }
        async with session.get(self.url) as resp:
            h = lhtml.parse(BytesIO(await resp.read()))
            h.getroot().make_links_absolute(self.url)
            parsed["feed"]["title"] = h.getroot().findtext("head/title")
            for item_el in self.item_selector(h):
                entry = FeedParserDict()
                for k in self.selectors:
                    t = self.selectors[k](item_el)
                    if t:
                        entry[k] = t
                parsed["entries"].append(entry)

            return FeedParserDict(parsed)


def css_text(sel):
    return (
        lambda h: CSSSelector(sel)(h)[0].text_content() if CSSSelector(sel)(h) else None
    )


def css_html(sel):
    return (
        lambda h: bleach.clean(
            (e[0].text if e[0].text else "")
            + "".join(
                tostring(child, encoding="utf-8").decode("utf-8")
                for child in e[0].iterchildren()
            ),
            strip=True,
        )
        if (e := CSSSelector(sel)(h))
        else None
    )


def css_attr(sel, attr):
    return lambda h: CSSSelector(sel)(h)[0].get(attr)


def css_attr_regex(sel, attr, regex, group):
    return (
        lambda h: m[group]
        if (m := next(re.finditer(regex, css_attr(sel, attr)(h)), None))
        else None
    )


def css_enclosures(sel, attr):
    return lambda h: [
        FeedParserDict(
            href=enc.get(attr),
            type=mimetypes.guess_type(enc.get(attr).split("?")[0])[0],
            length=0,
            rel="enclosure",
        )
        for enc in CSSSelector(sel)(h)
        if enc.get(attr)
    ]


def css_enclosures_regex(sel, attr, regex, group):
    r = re.compile(regex)
    return lambda h: [
        FeedParserDict(
            href=(url := r.search(enc.get(attr, ""))[group]),
            type=mimetypes.guess_type(url.split("?")[0])[0],
            length=0,
            rel="enclosure",
        )
        for enc in CSSSelector(sel)(h)
        if enc.get(attr) and r.search(enc.get(attr))
    ]


async def main():
    async with aiohttp.ClientSession() as session:
        print(
            json.dumps(
                await HTMLAdapter(
                    "https://t.me/s/var_log_shitpost",
                    CSSSelector(".tgme_widget_message"),
                    {
                        "title": css_text(".tgme_widget_message_owner_name"),
                        "description": css_html(".tgme_widget_message_text"),
                        "link": css_attr("a.tgme_widget_message_date", "href"),
                        "id": css_attr("a.tgme_widget_message_date", "href"),
                        "published": css_attr("time", "datetime"),
                        "published_parsed": lambda h: parse(
                            css_attr("time", "datetime")(h)
                        ).timetuple()
                        if css_attr("time", "datetime")(h)
                        else None,
                        "links": lambda h: css_enclosures_regex(
                            ".tgme_widget_message_photo_wrap",
                            "style",
                            r"url\('(.+)'\)",
                            1,
                        )(h)
                        + css_enclosures("video", "src")(h),
                    },
                )(session)
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
