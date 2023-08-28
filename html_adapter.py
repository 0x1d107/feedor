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
class JSONAdapter:
    def __init__(self,url,get_items,get_entry,params=None):
        self.url = url
        self.get_items = get_items
        self.get_entry = get_entry
        self.params = params

    async def __call__(self, session):
        parsed = {
            "url": self.url,
            "feed": FeedParserDict(title="JSONParser Feed"),
            "entries": [],
        }
        async with session.post(self.url,json=self.params) as resp:
            parsed["entries"].extend([FeedParserDict(self.get_entry(e))  for e in
                                      self.get_items(await resp.json())])

            return FeedParserDict(parsed)


def css_text(sel):
    def html2txt(h):
        frag =  CSSSelector(sel)(h) 
        if not frag:
            return None
        frag = frag[0]
        for br in frag.xpath("*//br"):
            br.tail = '\n'+br.tail if br.tail else '\n'
        return frag.text_content()
    return html2txt
allowed_tags=set(bleach.ALLOWED_TAGS) or {'br'}
cleaner = bleach.Cleaner(allowed_tags,strip=True)
def css_html(sel):
    return (
        lambda h: cleaner.clean(
            (e[0].text if e[0].text else "")
            + "".join(
                tostring(child, encoding="utf-8").decode("utf-8")
                for child in e[0].iterchildren()
            ),
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
                    "https://t.me/s/sapporolife",
                    CSSSelector(".tgme_widget_message"),
                    {
                        "title": css_text(".tgme_widget_message_owner_name"),
                        "description": css_text(".tgme_widget_message_text"),
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
