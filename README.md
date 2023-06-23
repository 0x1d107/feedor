# feedor.py - aiohttp-based RSS feed aggregator
feedor.py is a (yet another) RSS feed aggregator. Its main purpose is to combine many different
rss-atom-json-whatever feeds into a single unified feed that can be consumed through a web browser
or an external rss feed reader. It also can act as a planet feed for multiple weblogs.

## Installation

```
python -m venv env
source env/bin/activate
pip install -r requirements.txt
```

Edit feedor.py to set your preferred [fts5 tokenizer](https://www.sqlite.org/fts5.html#tokenizers).
```py
...
class database:
    search_tokenizer = 'unicode61'
...
```
If you want to enable `snowball` tokenizer, clone <https://github.com/abiliojr/fts5-snowball>
recursively
into fts5-snowball subdirectory, and compile it by running `make -C fts5-snowball`. 

Then you need to create a file `feeds.txt` with all feed urls (a single url on each line) that you
want to subscribe to. Run `./feedor.py -u` to fetch all feeds that you've subscribed to.

## Usage 
```
usage: feedor.py [-h] [-s] [-f FILE] [-u] [-n LIMIT] [-t UPDATE_PERIOD]
                 [--no-etag] [-p HOST_PORT]

options:
  -h, --help        show this help message and exit
  -s                Serve feed
  -f FILE           Generate latest feed and write it to file.
  -u                Update feeds
  -n LIMIT          Limit number of entries shown
  -t UPDATE_PERIOD  Seconds between database updates
  --no-etag         Disables ETag and Last-Modified checks
  -p HOST_PORT      Host and port to listen to
```

By default, the web server runs at port 8080. If your browser doesn't support xslt properly (looking
at you, firefox), use `/feed.html` endpoint, where XSLT transformation happens on the
server.

If you want to use feedor.py as a desktop RSS reader, you may want to run feedor.py with `-u` flag
only first and then run it with `-s` flag. That way feedor.py won't update every 15 minutes while you're reading your feed.

`feeds.db` contains the cached feed entries and the search index. If the database gets too large,
you can delete it and run `./feedor.py -u` to recreate it.

