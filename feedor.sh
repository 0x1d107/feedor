#!/bin/bash
cd $(dirname $(readlink -f $0))
.env/bin/python ./feedor.py -sut 1800 > /dev/null &
echo $! > pid_file
python -m webbrowser "http://127.0.0.1:8080/feed.html" 2> /dev/null 1>/dev/null
