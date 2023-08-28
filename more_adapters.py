from html_adapter import *
from dateutil.parser import isoparse,ParserError
def selector_parse_date(s):
    def dateparser(x):
        try:
            dt = isoparse(s(x))
            if dt:
                return dt.timetuple()
        except ValueError:
            pass
        return None
    return dateparser
def lazyblog_adapter(x,*_): 
    return HTMLAdapter(x, CSSSelector("main li"), {
        "title": css_text("a.title"),
        "link": css_attr("a.title",'href'),
        "description": css_html("p"),
        "id": css_attr("a.title",'href'),
        "published": css_text("time:nth-of-type(1)"),
        "published_parsed": selector_parse_date(css_text("time:nth-of-type(1)"))
        })
def telegram_adapter(x,*_):
    return HTMLAdapter(
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
    )
