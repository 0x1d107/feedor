#!/bin/env python
import asyncio 
import aiohttp 
from aiohttp import web
from io import BytesIO, StringIO
import feedparser
from feedparser.util import FeedParserDict
import time, calendar
import datetime
from email.utils import format_datetime
import jinja2
import lxml.html as lhtml
from lxml import etree
import lxml.html.clean as lclean
from os.path import getmtime

import bleach
from html_sanitizer.sanitizer import Sanitizer, DEFAULT_SETTINGS


import json
from dateutil.parser import parse
from html_adapter import (
    HTMLAdapter,
    css_attr,
    css_text,
    css_html,
    css_enclosures_regex,
    css_enclosures,
    CSSSelector,
)
from hashlib import md5

import sqlite3
from argparse import ArgumentParser


class database:
    INIT = """
        CREATE TABLE IF NOT EXISTS entries(
            data json,
            time NUMERIC,
            guid TEXT UNIQUE AS (data->>'$.id') STORED,
            source TEXT AS (data->>'$.source') STORED

        );
    """
    REPLACE = """
        REPLACE INTO entries(data,time) values (?,?);
    """
    GET_ALL = """
        SELECT data,time,rowid FROM entries ORDER BY time DESC, rowid DESC ;
    """
    GET_PAGE_FIRST = """
        SELECT data,time,rowid FROM entries ORDER BY time DESC, rowid DESC LIMIT ? ;
    """
    GET_PAGE_NEXT = """
        SELECT data,time,rowid FROM entries WHERE time < ? OR (time = ? AND rowid < ?) ORDER BY time DESC, rowid DESC LIMIT ? ;
    """

    def __init__(self, dbname="feeds.db"):
        self.conn = sqlite3.connect(dbname)
        self.cursor = self.conn.cursor()
        self.cursor.execute(database.INIT)

    def __del__(self):
        self.conn.commit()
        self.conn.close()

    def update_entry(self, entry):
        pub_time = get_time(entry)

        self.cursor.execute(database.REPLACE, [json.dumps(entry), pub_time])

    def get_entries(self, limit=0, page_key=None):
        if not limit:
            self.cursor.execute(database.GET_ALL)
        elif page_key is None:
            self.cursor.execute(database.GET_PAGE_FIRST, [limit])
        else:
            self.cursor.execute(
                database.GET_PAGE_NEXT, [page_key[0], page_key[0], page_key[1], limit]
            )
        entries = []
        for row in self.cursor.fetchall():
            obj = FeedParserDict(json.loads(row[0]))
            # print(obj)
            if obj.get("links"):
                obj["links"] = map(FeedParserDict, obj["links"])
            entries.append(obj)
            page_key = (row[1], row[2])
        return entries, page_key

last_updated_at = None
db = database()
last_updated_at = datetime.datetime.utcfromtimestamp( getmtime('feeds.db')).isoformat()


feeds = []
with open("feeds.txt") as f:
    feeds = [
        line.strip()
        for line in f.readlines()
        if line.strip() and not line.startswith("#")
    ]
"""
feeds.append(
    HTMLAdapter(
        "https://mastodon.ml/@rf",
        CSSSelector(".entry-reblog"),
        {
            "title": css_text(".display-name__account"),
            "description": css_html(".e-content"),
            "link": css_attr("a.u-uid", "href"),
            "id": css_attr("a.u-uid", "href"),
            "published": css_attr("time", "datetime"),
            "published_parsed": lambda h: parse(
                css_attr("time", "datetime")(h)
            ).timetuple(),
            "links": css_enclosures(".attachment-list a", "href"),
        },
    )
)
"""
feeds.append(
    HTMLAdapter(
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
                ".tgme_widget_message_photo_wrap", "style", r"url\('(.+)'\)", 1
            )(h)
            + css_enclosures("video", "src")(h),
        },
    )
)

feeds.append(
    HTMLAdapter(
        "https://t.me/s/sapporolife",
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
                ".tgme_widget_message_photo_wrap", "style", r"url\('(.+)'\)", 1
            )(h)
            + css_enclosures("video", "src")(h),
        },
    )
)


async def fetch(session, url):
    if type(url) is not str:
        d = await url(session)
        print("Fetched", d.url)
        return d
    async with session.get(url) as response:
        d = feedparser.parse(BytesIO(await response.read()))
        d["url"] = url
        print("Fetched", d.url)
        return d


def get_time(e):
    return calendar.timegm(
        e.get("updated_parsed", e.get("published_parsed", time.gmtime(0)))
    )


def rfc3339_time(e):
    return datetime.datetime.fromtimestamp(
        get_time(e), tz=datetime.timezone.utc
    ).isoformat()


def rfc882_time(e):
    return format_datetime(
        datetime.datetime.fromtimestamp(get_time(e), tz=datetime.timezone.utc)
    )


allowed_tags = [
    "p",
    "div",
    "span",
    "q",
    "br",
    "pre",
    "u",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "img",
    "table",
    "thead",
    "tbody",
    "th",
    "tr",
    "td",
    "s",
    "sub",
    "sup",
]
cleaner = bleach.Cleaner(
    bleach.ALLOWED_TAGS + allowed_tags,
    attributes=bleach.ALLOWED_ATTRIBUTES,
)
cleaner.attributes["img"] = ["src"]

sanitizer = Sanitizer()
for t in allowed_tags:
    sanitizer.tags.add(t)
sanitizer.attributes["img"] = ["src"]


async def update_feed(session, url):
    feed = None
    try:
        feed = await fetch(session, url)
    except asyncio.TimeoutError as e:
        print("Request to", url, "timed out !!!", e)
        return
    except aiohttp.ClientConnectionError as e:
        print(e)
        return
    print("Processing")
    for entry in feed.entries:
        entry["source_title"] = feed.feed.title
        if not entry.get("id"):
            entry["id"] = entry.get(
                "link",
                feed.url + ":" + md5(entry.get("description")).hexdigest(),
            )
        entry["source"] = feed.url
        if "description" in entry and entry["description"]:
            tree = lhtml.fromstring(entry.description)
            # lhtml.html_to_xhtml(tree)
            tree.make_links_absolute(feed.url)

            entry["description"] = sanitizer.sanitize(
                lhtml.tostring(tree).decode("utf-8")
            )
        db.update_entry(entry)
    print("Processing done")
    db.conn.commit()




async def gen_feed():
    global last_updated_at
    now = datetime.datetime.now(datetime.timezone.utc)
    last_updated_at = now.isoformat()
    print("Database update at", last_updated_at)

    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        await asyncio.gather(*[update_feed(session, url) for url in feeds])


async def feed_generator():
    while True:
        try:
            await asyncio.sleep(300)
            await asyncio.wait_for(gen_feed(),timeout=90)
        except asyncio.TimeoutError:
            print("Feed generator timed out")

LIMIT = 50

routes = web.RouteTableDef()
env = jinja2.Environment(
    loader=jinja2.FileSystemLoader("templates"),
    autoescape=jinja2.select_autoescape(),
    enable_async=True,
)
feed_template = env.get_template("feed.xml")
atom_template = env.get_template("atom.xml")


async def render_feed(page_key=None, template=feed_template, format_time=rfc882_time,limit = LIMIT):
    # entries,feed_data = await gen_feed()
    entries, page_key = db.get_entries(limit, page_key=page_key)
    return await template.render_async(
        entries=entries,
        page_key=page_key,
        updated=last_updated_at,
        rfc_time=format_time,
    )


@routes.get("/")
@routes.get("/rss.xml")
async def index(request):
    next_param = request.rel_url.query.get("next", None)
    page_key = None
    if next_param:
        page_key = tuple(map(int, next_param.split(":")))
    limit = int(request.rel_url.query.get('limit',LIMIT))
    b = await render_feed(page_key,limit=limit)
    return web.Response(content_type="text/xml", body=b)


@routes.get("/atom.xml")
async def atom_feed(request):
    next_param = request.rel_url.query.get("next", None)
    page_key = None
    if next_param:
        page_key = tuple(map(int, next_param.split(":")))
    limit = int(request.rel_url.query.get('limit',LIMIT))
    b = await render_feed(page_key, template=atom_template, format_time=rfc3339_time,limit=limit)
    return web.Response(content_type="text/xml", body=b)


@routes.get("/feed.css")
async def stylesheet(request):
    return web.FileResponse("feed.css")


@routes.get("/feed.xsl")
async def transform(request):
    return web.FileResponse("feed.xsl")


@routes.get("/atom.xsl")
async def transform(request):
    return web.FileResponse("atom.xsl")


@routes.get("/feed.html")
async def get_html_feed(request):
    next_param = request.rel_url.query.get("next", None)
    page_key = None
    if next_param:
        page_key = tuple(map(int, next_param.split(":")))
    limit = int(request.rel_url.query.get('limit',LIMIT))
    xml_feed = etree.XML((await render_feed(page_key,limit=limit)).encode("utf-8"))
    transform = etree.XSLT(etree.parse("feed.xsl"))
    html_feed = transform(xml_feed)
    lhtml.xhtml_to_html(html_feed)
    return web.Response(body=etree.tostring(html_feed), content_type="text/html")


arg_parser = ArgumentParser()
arg_parser.add_argument("-s", action="store_true", dest="serve", help="Serve feed")
arg_parser.add_argument(
    "-f", dest="file", help="Generate latest feed and write it to file."
)
arg_parser.add_argument('-u',action='store_true',dest='update', help ='Update feeds')
arg_parser.add_argument('-n',type=int,dest='limit',
        help='Limit number of entries shown',default=50)

args = arg_parser.parse_args()
LIMIT = args.limit

if args.update:
    asyncio.run(gen_feed())
if args.file:
    ext = args.file.split('.')[-1]
    with open(args.file, "w") as file:
        if ext == 'atom':
            file.write(asyncio.run(
                render_feed(template=atom_template,format_time=rfc3339_time,limit=LIMIT)))
        elif ext == 'html':

            xml_feed = etree.XML(asyncio.run( render_feed(limit=LIMIT)).encode("utf-8"))
            
            transform = etree.XSLT(etree.parse("feed.xsl"))
            file.write(etree.tostring(transform(xml_feed)).decode('utf-8'))
        else:
            file.write(asyncio.run(render_feed(limit=LIMIT)))
async def serve():
    asyncio.create_task(feed_generator())
    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner)
    await site.start()
    await asyncio.Event().wait()

if args.serve:
    asyncio.run(serve())
