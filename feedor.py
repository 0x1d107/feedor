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
from html import unescape
from urllib.parse import urljoin
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
    JSONAdapter,
)
from hashlib import md5

import sqlite3
from argparse import ArgumentParser


class database:
    # search_tokenizer = 'unicode61'
    search_tokenizer='snowball russian english'
    INIT = """
        CREATE TABLE IF NOT EXISTS entries(
            entryid INTEGER PRIMARY KEY AUTOINCREMENT,
            data json,
            time NUMERIC,
            guid TEXT UNIQUE AS (data->>'$.id') STORED,
            source TEXT AS (data->>'$.source') STORED

        );
    """
    INIT_SEARCH = f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS search USING
        fts5(title,description,source,tokenize='{search_tokenizer}');
    """
    INIT_ETAG="""
        CREATE TABLE IF NOT EXISTS etags (
            feed TEXT UNIQUE,
            etag TEXT,
            time NUMERIC
        );
    """
    REPLACE = """
        REPLACE INTO entries(data,time) values (?,?);
    """
    REPLACE_SEARCH = """
        REPLACE INTO search(rowid,title,description,source) values (?,?,?,?); 
    """
    REPLACE_ETAG = """
        REPLACE INTO etags(feed,etag,time) values (?,?,?);
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
    GET_SEARCH = """ 
        SELECT data,time,entries.rowid FROM entries JOIN search ON entries.rowid = search.rowid WHERE
        search MATCH ? ORDER BY time DESC,entries.rowid DESC;
    """
    GET_ENCLOSURE_URLS = """ 
        select json_each.value->>'href' from entries, json_each(entries.data->'links') where json_each.value->>'rel' = 'enclosure' and json_each.value->>'type' like 'image/%';
    """
    GET_ETAG="""
        SELECT etag,time from etags where feed = ?;
    """

    def __init__(self, dbname="feeds.db"):
        self.conn = sqlite3.connect(dbname)
        self.cursor = self.conn.cursor()
        if 'snowball' in database.search_tokenizer:
            self.conn.enable_load_extension(True)
            self.conn.load_extension('fts5-snowball/fts5stemmer.so')
        self.cursor.execute(database.INIT)
        self.cursor.execute(database.INIT_SEARCH)
        self.cursor.execute(database.INIT_ETAG)

    def __del__(self):
        self.conn.commit()
        self.conn.close()

    def update_entry(self, entry):
        pub_time = get_time(entry)
        self.cursor.execute(database.REPLACE, [json.dumps(entry), pub_time])
        self.cursor.execute(database.REPLACE_SEARCH,[self.cursor.lastrowid,entry.get('title',''),
                                                     entry.get('description',''),entry.get('source','')])

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
    def get_search(self,query,limit=50,page_key=None):
        self.cursor.execute(database.GET_SEARCH,[query])
        entries = []
        for row in self.cursor.fetchall():
            obj = FeedParserDict(json.loads(row[0]))
            if obj.get("links"):
                obj["links"] = map(FeedParserDict, obj["links"])
            entries.append(obj)
        return entries,(0,0)
    def set_etag(self, feed_url,etag):
        ts = int(datetime.datetime.now().timestamp())
        self.cursor.execute(self.REPLACE_ETAG,[feed_url,etag,ts])
    def get_etag(self, feed_url):
        self.cursor.execute(self.GET_ETAG,[feed_url])
        res = self.cursor.fetchall()
        if len(res) == 0:
            return None,None
        return res[0][0],res[0][1]

last_updated_at = None
db = database()
last_updated_at = datetime.datetime.utcfromtimestamp(getmtime("feeds.db")).isoformat()

from more_adapters import lazyblog_adapter,telegram_adapter
adapters = {
    "tg": telegram_adapter,
    "lb": lazyblog_adapter
}


def adapt(url):
    if "::" in url:
        spec = url.split("::")
        return adapters.get(spec[0], lambda x, *_: x)(*spec[1:])
    return url


feeds = []
with open("feeds.txt") as f:
    feeds = [
        adapt(line.strip())
        for line in f.readlines()
        if line.strip() and not line.startswith("#")
    ]


async def fetch(session, url):
    if type(url) is not str:
        d = await url(session)
        print("Fetched", d.url)
        return d
    hdrs={
        'User-Agent': 'feedor.py-rss-aggergator',
        'Content-Encoding': 'gzip'
    }
    etag,ts = db.get_etag(url)
    if etag and not args.no_etag:
        hdrs['If-None-Match'] = etag
    if ts and not args.no_etag:
        hdrs['If-Modified-Since'] = format_datetime(datetime.datetime.fromtimestamp(ts))
    async with session.get(url,headers=hdrs) as response:
        print("Fetched", url, response.status)
        d = feedparser.parse(BytesIO(await response.read()))
        d["url"] = url
        if (etag := response.headers.get('ETag')):
            db.set_etag(url, etag)
        return d


def get_time(e):
    parsed =  e.get("updated_parsed", e.get("published_parsed", time.gmtime(0)))
    if not parsed:
        return calendar.timegm(time.gmtime(0))
    return calendar.timegm(parsed)


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
    "table",
    "thead",
    "tbody",
    "th",
    "tr",
    "td",
    "s",
    "a",
    "sub",
    "sup",
    "ul",
    "ol",
    "li"
]
cleaner = bleach.Cleaner(
    list(bleach.ALLOWED_TAGS) + allowed_tags,
    attributes=bleach.ALLOWED_ATTRIBUTES,
)
cleaner.attributes["img"] = ["src"]

sanitizer = Sanitizer()
for t in allowed_tags:
    sanitizer.tags.add(t)
sanitizer.attributes["img"] = ["src"]
import nh3
def html_sanitize(html):
    return nh3.clean(html,tags=set(allowed_tags))


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
    print("Processing",len(feed.entries),'entries')
    for entry in feed.entries:
        entry["source_title"] = feed.feed.title
        if not entry.get("id"):
            entry["id"] = entry.get(
                "link",
                feed.url
                + ":"
                + md5(entry.get("description").encode("utf-8")).hexdigest(),
            )
        entry["source"] = feed.url
        if "link" in entry:
            entry["link"] = urljoin(feed.url,entry.link)
        if "description" in entry and entry["description"]:
            tree = lhtml.fromstring(entry.description)
            tree.make_links_absolute(feed.url)
            entry["description"] = html_sanitize(
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
            await asyncio.sleep(args.update_period)
            await asyncio.wait_for(gen_feed(), timeout=90)
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


async def render_feed(
    page_key=None, template=feed_template, format_time=rfc882_time, limit=LIMIT,
    static=False
):
    entries, page_key = db.get_entries(limit, page_key=page_key)
    return await template.render_async(
        entries=entries,
        page_key=page_key,
        updated=last_updated_at,
        rfc_time=format_time,
        static=static
    )

async def search_feed(query):
    entries,page_key = db.get_search(query)

    return await feed_template.render_async(entries=entries,
                                            updated=last_updated_at,rfc_time=rfc882_time)

@routes.get("/")
@routes.get("/rss.xml")
async def index(request):
    next_param = request.rel_url.query.get("next", None)
    page_key = None
    if next_param:
        page_key = tuple(map(int, next_param.split(":")))
    limit = int(request.rel_url.query.get("limit", LIMIT))
    b = await render_feed(page_key, limit=limit)
    return web.Response(content_type="text/xml", body=b)


@routes.get("/atom.xml")
async def atom_feed(request):
    next_param = request.rel_url.query.get("next", None)
    page_key = None
    if next_param:
        page_key = tuple(map(int, next_param.split(":")))
    limit = int(request.rel_url.query.get("limit", LIMIT))
    b = await render_feed(
        page_key, template=atom_template, format_time=rfc3339_time, limit=limit
    )
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
    limit = int(request.rel_url.query.get("limit", LIMIT))
    xml_feed = etree.XML((await render_feed(page_key, limit=limit)).encode("utf-8"))
    transform = etree.XSLT(etree.parse("feed.xsl"))
    html_feed = transform(xml_feed)
    lhtml.xhtml_to_html(html_feed)
    return web.Response(body=etree.tostring(html_feed), content_type="text/html")
@routes.get("/search")
async def get_html_search(request):
    query = unescape(request.query.get('q'))
    xml_feed = etree.XML((await search_feed(query)).encode("utf-8"))
    transform = etree.XSLT(etree.parse("feed.xsl"))
    html_feed = transform(xml_feed)
    lhtml.xhtml_to_html(html_feed)
    return web.Response(body=etree.tostring(html_feed), content_type="text/html")


arg_parser = ArgumentParser()
arg_parser.add_argument("-s", action="store_true", dest="serve", help="Serve feed")
arg_parser.add_argument(
    "-f", dest="file", help="Generate latest feed and write it to file."
)
arg_parser.add_argument("-u", action="store_true", dest="update", help="Update feeds")
arg_parser.add_argument(
    "-n", type=int, dest="limit", help="Limit number of entries shown", default=50
)
arg_parser.add_argument('-t',dest="update_period", type= int, help="Seconds between database updates",default=3600)
arg_parser.add_argument('--no-etag', action='store_true', help="Disables ETag and Last-Modified checks")
def host_tuple(x):
    l=x.split(':')
    if not len(l):
        return (None,None)
    if len(l) == 1:
        t= l[0]
        if '.' in t:
            return (t,None)
        else:
            return (None,int(t))
    if len(l)>=2:
        return (l[0],int(l[1]))

arg_parser.add_argument('-p',dest="host_port",
                        help="Host and port to listen to",
                        type=host_tuple,default="127.0.0.1:8080")

args = arg_parser.parse_args()
LIMIT = args.limit

feed_gen_task = None
if args.update:
    asyncio.run(gen_feed())
if args.file:
    ext = args.file.split(".")[-1]
    with open(args.file, "w") as file:
        if ext == "atom":
            file.write(
                asyncio.run(
                    render_feed(
                        template=atom_template, format_time=rfc3339_time, limit=LIMIT
                    )
                )
            )
        elif ext == "html":
            xml_feed = etree.XML(asyncio.run(render_feed(limit=LIMIT,static=True)).encode("utf-8"))
            transform = etree.XSLT(etree.parse("feed.xsl"))
            file.write(etree.tostring(transform(xml_feed)).decode("utf-8"))
        else:
            file.write(asyncio.run(render_feed(limit=LIMIT,static=True)))


async def serve():
    global feed_gen_task
    if args.update:
        feed_gen_task = asyncio.create_task(feed_generator())
    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    host,port = args.host_port
    site = web.TCPSite(runner,host=host,port=port)
    await site.start()
    await asyncio.Event().wait()


if args.serve:
    asyncio.run(serve())
