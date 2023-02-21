#!/home/nitro/Projects/feedor/.env/bin/python
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
    JSONAdapter,
)
from hashlib import md5

import sqlite3
from argparse import ArgumentParser


class database:
    INIT = """
        CREATE TABLE IF NOT EXISTS entries(
            entryid INTEGER PRIMARY KEY AUTOINCREMENT,
            data json,
            time NUMERIC,
            guid TEXT UNIQUE AS (data->>'$.id') STORED,
            source TEXT AS (data->>'$.source') STORED

        );
    """
    INIT_SEARCH = """
        CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts4(title,description);
    """
    REPLACE = """
        REPLACE INTO entries(data,time) values (?,?);
    """
    REPLACE_SEARCH = """
        REPLACE INTO search(rowid,title,description) values (?,?,?); 
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

    def __init__(self, dbname="feeds.db"):
        self.conn = sqlite3.connect(dbname)
        self.cursor = self.conn.cursor()
        self.cursor.execute(database.INIT)
        self.cursor.execute(database.INIT_SEARCH)

    def __del__(self):
        self.conn.commit()
        self.conn.close()

    def update_entry(self, entry):
        pub_time = get_time(entry)

        self.cursor.execute(database.REPLACE, [json.dumps(entry), pub_time])
        self.cursor.execute(database.REPLACE_SEARCH,[self.cursor.lastrowid,entry.get('title',''),
                                                     entry.get('description','')])


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

last_updated_at = None
db = database()
last_updated_at = datetime.datetime.utcfromtimestamp(getmtime("feeds.db")).isoformat()

adapters = {
    "tg": lambda x, *_: HTMLAdapter(
        f"https://t.me/s/{x}",
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
    ),
    "mk": lambda host,user,*_: JSONAdapter(
            f"https://{host}/api/users/notes",
            lambda rsp: rsp,
            lambda it: {"title": it['user']['username']
                        +(" RT "+it['renote']['user']['username'] if it.get('renote') else ''),
                        "description": it["text"] if it.get('text') else 
                        it['renote'].get('text','') if
                        it.get('renote') else '',
                        "link":f"https://{host}/notes/{it['id']}",
                        "id":f"https://{host}/notes/{it['id']}",
                        "published":it["createdAt"],
                        "published_parsed":parse(it['createdAt']).timetuple(),
                        "links":
                        [FeedParserDict(href=f['url'],length=f['size'],type=f['type'],rel='enclosure') 
                         for f in (it['files']+(it['renote']['files'] if it.get('renote') else []))]
                        },
            params={'userId':user,'limit':50}
        ),
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
                feed.url
                + ":"
                + md5(entry.get("description").encode("utf-8")).hexdigest(),
            )
        entry["source"] = feed.url
        if "description" in entry and entry["description"]:
            tree = lhtml.fromstring(entry.description)
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
            await asyncio.sleep(600)
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
    page_key=None, template=feed_template, format_time=rfc882_time, limit=LIMIT
):
    entries, page_key = db.get_entries(limit, page_key=page_key)
    return await template.render_async(
        entries=entries,
        page_key=page_key,
        updated=last_updated_at,
        rfc_time=format_time,
    )

async def search_feed(query):
    entries,page_key = db.get_search(query)

    return await feed_template.render_async(entries=entries,page_key=page_key,
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
    query = request.rel_url.query.get('q')
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
            xml_feed = etree.XML(asyncio.run(render_feed(limit=LIMIT)).encode("utf-8"))
            transform = etree.XSLT(etree.parse("feed.xsl"))
            file.write(etree.tostring(transform(xml_feed)).decode("utf-8"))
        else:
            file.write(asyncio.run(render_feed(limit=LIMIT)))


async def serve():
    global feed_gen_task
    feed_gen_task = asyncio.create_task(feed_generator())
    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner)
    await site.start()
    await asyncio.Event().wait()


if args.serve:
    asyncio.run(serve())
