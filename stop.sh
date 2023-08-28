#!/bin/bash
cd $(dirname $(readlink -f $0))
[ -r pid_file ] || exit 1
xargs kill < pid_file
rm pid_file
