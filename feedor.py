#!/bin/env python
import asyncio
import aiohttp
from aiohttp import web
from io import BytesIO,StringIO
import feedparser
from feedparser.util import FeedParserDict
import time,calendar
import jinja2
import lxml.html as lhtml
from lxml import etree
import lxml.html.clean as lclean
import bleach
import json
from dateutil.parser import parse
from html_adapter import HTMLAdapter,css_attr,css_text,css_html,css_enclosures_regex,css_enclosures,CSSSelector
from hashlib import md5

import sqlite3

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
    GET_ALL="""
        SELECT data,time FROM entries ORDER BY time DESC ;
    """
    def __init__(self,dbname='feeds.db'):
        self.conn = sqlite3.connect(dbname)
        self.cursor = self.conn.cursor()
        self.cursor.execute(database.INIT)
    def update_entry(self,entry):
        pub_time= get_time(entry)
        self.cursor.execute(database.REPLACE,[json.dumps(entry),pub_time])
        self.conn.commit()
    def get_entries(self):
        self.cursor.execute(database.GET_ALL)
        entries=[]
        for row in self.cursor.fetchall():
            obj = FeedParserDict(json.loads(row[0]))
            #print(obj)
            if obj.get('links'):
                obj["links"] = map(FeedParserDict,obj['links'])
            entries.append(obj)
        return entries

            
db = database()
    

feeds=[]
with open("feeds.txt") as f:
    feeds = [line.strip() for line in f.readlines()if line.strip() and not line.startswith('#')]

feeds.append(HTMLAdapter("https://mastodon.ml/@rf", CSSSelector(".entry-reblog"), 
        {
            "title":css_text(".display-name__account"),
            "description":css_html(".e-content"),
            "link":css_attr('a.u-uid', 'href'),
            "id":css_attr('a.u-uid', 'href'),
            "published":css_attr('time', 'datetime'),
            "published_parsed":lambda h: parse(css_attr('time', 'datetime')(h)).timetuple(),
            "links":css_enclosures('.attachment-list a','href')
        }))
feeds.append(HTMLAdapter("https://t.me/s/var_log_shitpost", CSSSelector(".tgme_widget_message"), 
        {
            "title":css_text(".tgme_widget_message_owner_name"),
            "description":css_html(".tgme_widget_message_text"),
            "link":css_attr('a.tgme_widget_message_date', 'href'),
            "id":css_attr('a.tgme_widget_message_date', 'href'),
            "published":css_attr('time', 'datetime'),
            "published_parsed":lambda h: parse(css_attr('time', 'datetime')(h)).timetuple()if css_attr('time', 'datetime')(h) else None,
            "links":lambda h:css_enclosures_regex('.tgme_widget_message_photo_wrap', 'style', r"url\('(.+)'\)", 1)(h)+css_enclosures('video', 'src')(h)
        }))

feeds.append(HTMLAdapter("https://t.me/s/sapporolife", CSSSelector(".tgme_widget_message"), 
        {
            "title":css_text(".tgme_widget_message_owner_name"),
            "description":css_html(".tgme_widget_message_text"),
            "link":css_attr('a.tgme_widget_message_date', 'href'),
            "id":css_attr('a.tgme_widget_message_date', 'href'),
            "published":css_attr('time', 'datetime'),
            "published_parsed":lambda h: parse(css_attr('time', 'datetime')(h)).timetuple()if css_attr('time', 'datetime')(h) else None,
            "links":lambda h:css_enclosures_regex('.tgme_widget_message_photo_wrap', 'style', r"url\('(.+)'\)", 1)(h)+css_enclosures('video', 'src')(h)
        }))

async def fetch(session,url):
    if type(url) is not str:
        d = await url(session)
        return d
    async with session.get(url) as response:
        d = feedparser.parse(BytesIO(await response.read()))
        d["url"] = url
        return d
def get_time(e):
    return calendar.timegm(e.get('updated_parsed',e.get('published_parsed',time.gmtime(0))))
async def gen_feed():
    cleaner = bleach.Cleaner(bleach.ALLOWED_TAGS+['p','div','span','q','br','pre','u','h1','h2','h3','h4','h5','h6','img'],attributes=bleach.ALLOWED_ATTRIBUTES)
    cleaner.attributes['img'] = ['src']
    async with aiohttp.ClientSession() as session:
        feed_data = await asyncio.gather(*[fetch(session, url) for url in feeds])
        entries=[]
        for feed in feed_data:
            for entry in feed.entries:
                entry["source_title"] = feed.feed.title
                if not entry.get('id'):
                    entry['id'] = entry.get('link',feed.url +':'+md5(entry.get('description')).hexdigest())
                entry["source"] = feed.url
                if 'description' in entry:
                    tree = lhtml.fromstring(entry.description)
                    #lhtml.html_to_xhtml(tree)
                    tree.make_links_absolute(feed.url)

                    entry["description"] = cleaner.clean(lhtml.tostring(tree).decode('utf-8'))
                entries.append(entry)
                db.update_entry(entry)
async def feed_generator():
    while True:
        await gen_feed()
        await asyncio.sleep(30)
async def render_feed():
    #entries,feed_data = await gen_feed()
    entries = db.get_entries()
    return await feed_template.render_async(entries=entries) 

routes = web.RouteTableDef()
env = jinja2.Environment(loader=jinja2.FileSystemLoader("templates"),autoescape=jinja2.select_autoescape(),enable_async=True)
feed_template = env.get_template("feed.xml")

@routes.get('/')
async def index(request):
    b = await render_feed()
    return web.Response(content_type='text/xml',body = b)

@routes.get('/feed.xsl')
async def stylesheet(request):
    return web.FileResponse("feed.xsl")
@routes.get('/feed.html')
async def get_html_feed(request):
    xml_feed = etree.XML((await render_feed()).encode('utf-8'))
    transform = etree.XSLT(etree.parse('feed.xsl'))
    html_feed =transform(xml_feed)
    lhtml.xhtml_to_html(html_feed)
    return web.Response(body=etree.tostring(html_feed),content_type='text/html')
asyncio.run(gen_feed())
app = web.Application()
app.add_routes(routes)
loop = asyncio.new_event_loop()
feedgen_task = loop.create_task(feed_generator())
asyncio.set_event_loop(loop)
try:
    web.run_app(app)
finally:
    feedgen_task.cancel()
    loop.run_until_complete(feedgen_task)
