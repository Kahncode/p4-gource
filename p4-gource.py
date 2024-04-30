#!  /usr/bin/python

# p4-gource.py - perforce to gource change log converter

# original usage:
# $ head=`p4 changes -m 1 | awk '{ print $2 }'`
# $ for ((i = 1; i <= $head; ++i)); do p4 describe -s $i >> p4.log; done
# $ ./p4-gource.py -p //depot/trunk -o trunk.gource p4.log
# $ gource --highlight-all-users trunk.gource

# Modifications by Samuel Kahn <samuel@darewise.com>
# The script will now fetch the history from perforce if the default file
# (p4.log) is not found
# The script will also call gource directly after

# TODO: save multiple files during log fetching so it can be done incrementally
# TODO: add possibility of multiple paths and excludes by removing it from the regexp and testing paths in p4_to_gource

#exclude : marketplace, plugins, engine, 

from __future__ import print_function
import os
import sys
import re
import time
import optparse
import subprocess
import os.path

usage = "usage: %s [options] [FILE]" % sys.argv[0]
parser = optparse.OptionParser(usage=usage)
#old options
parser.add_option("-o", "--out-file", dest="out", help="output filename, defaults to corvus")
#parser.add_option("-p", "--path-filter", dest="filter", default="//", help="include only paths starting with FILTER")
(options, args) = parser.parse_args()

if options.out:
	output = options.out
else:
	output = "p4-gource"

p4_log = "%s.p4.log" % output
gource_log = "%s.gource" % output
gource_log = "%s.gource" % output


path_include = ["//..."]
path_exclude = []

p4_entry = re.compile("^Change \d+ by (?P<author>\w+)@\S+ on (?P<timestamp>\S+ \S+)\s*(?P<pending>\*pending\*)?\s*$")
p4_affected_files = re.compile("^Affected files ...\s*$")
p4_file = re.compile("^... (?P<file>//[^#]+)#\d+ (?P<action>\w+)\s*$")

p4_action_to_gource = {
	"add" : "A"
	, "edit" : "M"
	, "integrate" : "M"
	, "branch" : "A"
	, "delete" : "D"
	, "purge" : "D"
}

def filter_file(file):
	match = False
	for include in path_include:
		if file.startswith(include):
			match = True
			break

	if not match:
		return False

	for exclude in path_exclude:
		if file.startswith(exclude):
			return False

	return True


def p4_to_gource(p4_log, gource_log):
	author = None
	timestamp = None
	files = False
	ignore_entry = False
	line_count = 0
	for line in p4_log:
		line_count+=1
		if line_count % 100000 == 0:
			print("Now parsing line %s" % line_count)

		entry = p4_entry.match(line)
		if entry:
			#skip pending entries as they have not been submitted
			ignore_entry = entry.group("pending") is not None
			author = entry.group("author").lower()
			timestamp = int(time.mktime(time.strptime(entry.group("timestamp"), "%Y/%m/%d %H:%M:%S")))
			files = False
			continue
		if not files:
			if p4_affected_files.match(line):
				files = True
		elif not ignore_entry:
			file = p4_file.match(line)
			if file and filter_file(file.group("file")):
				print("%d|%s|%s|%s|" % (timestamp
					, author
					, p4_action_to_gource[file.group("action")]
					, file.group("file")), file=gource_log)

def fetch_p4_log(p4_log_file):
	output = subprocess.check_output("p4 changes -m 1").decode("utf-8")
	last_change = re.search(r'Change (\d+) .*', output).group(1)
	print("Fetching %s changelists" % last_change)
	with open(input, "wb") as w:
		for i in range(1, int(last_change)):
			cl = subprocess.check_output(["p4", "describe", "-s", str(i)])
			w.write(cl)
			if i % 100 == 0:
				print("Now fetching changelist %s" % i)

#main logic
print("Fatching p4 log")
if not os.path.exists(p4_log):
	fetch_p4_log(p4_log)

print("Converting log to gource")
p4_to_gource(open(p4_log, "r", encoding="ISO-8859-1"), open(gource_log, "w"))

print("Calling gource")
#https://github.com/acaudwell/Gource/wiki/Videos
subprocess.call(["gource-0.47.win64\gource.exe",
				 "-1280x720",
				 "--camera-mode", "track",
				 "--disable-bloom",
				 "--hide", "filenames",
				 "-a", "1",
				 "-s", "0.5",
				 "--user-filter", "buildbot",
				 "--highlight-users",
				 "--highlight-colour", "ffff00",
				 #"-o", "%s.ppm" % output, # for video output
				 gource_log])

