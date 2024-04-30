#!  /usr/bin/python

# p4-gource.py - perforce to gource change log converter
# TODO: actually comment this file

# TODO: save multiple files during log fetching so it can be done incrementally
# TODO: add possibility of multiple paths and excludes by removing it from the regexp and testing paths in p4_to_gource

#exclude : marketplace, plugins, engine, 

import argparse
import os
import re
import subprocess
import sys
import time

def parse_args():
	parser = argparse.ArgumentParser(description="Convert Perforce logs to Gource format.")
	parser.add_argument("-u", "--p4-user", type=str, required=True, help="Perforce username")
	parser.add_argument("-p", "--p4-server", type=str, required=True, help="Perforce server address")
	parser.add_argument("-i", "--include-path", action="append", default=[], help="Include paths for filtering (can specify multiple)")
	parser.add_argument("-x", "--exclude-path", action="append", default=[], help="Exclude paths for filtering (can specify multiple)")
	parser.add_argument("-o", "--output", type=str, default="p4-gource", help="Base name for output files")
	parser.add_argument("-s", "--start-rev", type=int, default=0, help="Starting changelist number")
	parser.add_argument("-e", "--end-rev", type=int, default=None, help="Ending changelist number")
	parser.add_argument("-b", "--batch-size", type=int, default=10000, help="Number of changelists per batch when fetching logs")
	parser.add_argument("--fetch-only", action="store_true", default=False, help="Only fetch logs from P4, do not run Gource or video rendering")
	parser.add_argument("--skip-fetch", action="store_true", default=False, help="Do not fetch, only run Gource and video rendering")
	parser.add_argument("--skip-render", action="store_true", default=False, help="Open gource interactive, do not render video")

	return parser.parse_args()

def calculate_ranges(start_rev, end_rev, batch_size, out_base):
	# Extract existing revision ranges from log filenames
	regex = re.compile(rf"{re.escape(out_base)}_(\d+)-(\d+).p4.log")
	existing_ranges = []

	# List all files and extract valid ranges
	for filename in os.listdir("."):
		match = regex.match(filename)
		if match:
			start, end = map(int, match.groups())
			existing_ranges.append((start, end))

	# Sort ranges and merge overlapping or contiguous ranges
	existing_ranges.sort()
	merged_ranges = []

	for start, end in existing_ranges:
		if merged_ranges and merged_ranges[-1][1] >= start - 1:
			merged_ranges[-1] = (merged_ranges[-1][0], max(merged_ranges[-1][1], end))
		else:
			merged_ranges.append((start, end))

	# Calculate the needed ranges based on the batch size
	needed_ranges = []
	current_rev = start_rev

	for start, end in merged_ranges:
		while current_rev < start and start < end_rev:
			next_batch_end = min(current_rev + batch_size - 1, start - 1, end_rev)
			needed_ranges.append((current_rev, next_batch_end))
			current_rev = next_batch_end + 1
		current_rev = end + 1

	# Check for any remaining revisions after the last merged range
	while current_rev <= end_rev:
		next_batch_end = min(current_rev + batch_size - 1, end_rev)
		needed_ranges.append((current_rev, next_batch_end))
		current_rev = next_batch_end + 1

	return needed_ranges

def fetch_p4_log(p4_server, p4_user, ranges, out_base):
	fetched_files = []
	for start, end in ranges:
		temp_log_filename = f"{out_base}_{start}-{end}_temp.p4.log"
		final_log_filename = f"{out_base}_{start}-{end}.p4.log"

		print(f"Fetching changelists from {start} to {end}")
		with open(temp_log_filename, "wb") as log_file:
			error_occurred = False  # Flag to track if any error occurred
			for i in range(start, end + 1):
				if (i - start) % 100 == 99: # Just to keep printing for heartbeat to the user
					print(f"Fetching changelist {i}")
				cmd = ["p4", "-p", p4_server, "-u", p4_user, "describe", "-s", str(i)]
				try:
					cl = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
					log_file.write(cl)
				except subprocess.CalledProcessError as e:
					if "no such changelist" not in e.output.decode():
						print(f"Error fetching changelist {i}: {e.output.decode()}")
						error_occurred = True
						break  # Exit the changelist loop on error

		if not error_occurred:
			# Rename the temp log file to the final log file if no errors occurred
			os.rename(temp_log_filename, final_log_filename)
			fetched_files.append(final_log_filename)
		else:
			# Remove the temp log file if there was an error and re-raise the exception
			os.remove(temp_log_filename)
			raise Exception(f"Error occurred during fetching, check logs for more details. Aborted fetching at changelist {i}.")
		
	return fetched_files

def compile_path_patterns(paths):
	""" Compile Perforce-style path patterns into regular expressions. """
	regex_patterns = []
	for path in paths:
		# Replace Perforce wildcard '...' with regex '.*'
		pattern = path.replace('...', '.*')
		# Ensure the pattern matches from the start of the string
		pattern = '^' + re.escape(pattern).replace(r'\.\*', '.*')
		# Compile the pattern for faster matching
		regex_patterns.append(re.compile(pattern))
	return regex_patterns

def filter_file(file, include_paths, exclude_paths):
	""" Filter files based on compiled include and exclude regex patterns. """
	# Compile include and exclude patterns on first use or when paths are updated
	if not hasattr(filter_file, 'include_regexes') or filter_file.prev_include_paths != include_paths:
		filter_file.include_regexes = compile_path_patterns(include_paths)
		filter_file.prev_include_paths = include_paths
	if not hasattr(filter_file, 'exclude_regexes') or filter_file.prev_exclude_paths != exclude_paths:
		filter_file.exclude_regexes = compile_path_patterns(exclude_paths)
		filter_file.prev_exclude_paths = exclude_paths

	# Check if file matches any include pattern
	if not any(regex.match(file) for regex in filter_file.include_regexes):
		return False
	# Check if file matches any exclude pattern
	if any(regex.match(file) for regex in filter_file.exclude_regexes):
		return False
	return True

# Compile regex patterns outside of the function to compile them only once
p4_entry = re.compile(r"^Change \d+ by (?P<author>\w+)@\S+ on (?P<timestamp>\S+ \S+)\s*(?P<pending>\*pending\*)?\s*$")
p4_affected_files = re.compile(r"^Affected files ...\s*$")
p4_file = re.compile(r"^... (?P<file>//[^#]+)#\d+ (?P<action>\w+)\s*$")

p4_action_to_gource = {
	"add": "A",
	"edit": "M",
	"integrate": "M",
	"branch": "A",
	"delete": "D",
	"purge": "D"
}

def p4_to_gource(p4_log_path, gource_log_path, include_paths, exclude_paths):
	if os.path.exists(gource_log_path):
		print(f"Using existing file {gource_log_path}")
		return

	""" Convert Perforce log to a Gource-compatible log format. """
	print(f"Converting P4 to gource format: {p4_log_path} -> {gource_log_path}")
	with open(p4_log_path, 'r') as p4_log, open(gource_log_path, 'w') as gource_log:
		author, timestamp, files, ignore_entry = None, None, False, False
		line_count = 0
		for line in p4_log:
			line_count += 1
			if line_count % 100000 == 0:
				print(f"Now parsing line {line_count}")

			entry = p4_entry.match(line)
			if entry:
				if entry.group("pending"):
					continue  # Skip pending entries as they have not been submitted
				author = entry.group("author").lower()
				timestamp = int(time.mktime(time.strptime(entry.group("timestamp"), "%Y/%m/%d %H:%M:%S")))
				files = False  # Reset file processing
				continue

			if not files and p4_affected_files.match(line):
				files = True
				continue

			if files:
				file = p4_file.match(line)
				if file and filter_file(file.group("file"), include_paths, exclude_paths):
					action_code = p4_action_to_gource.get(file.group("action"), "")
					formatted_entry = f"{timestamp}|{author}|{action_code}|{file.group('file')}\n"
					gource_log.write(formatted_entry)

def discover_p4_logs(out_base):
	""" Scan the directory for all Perforce log files and return their revision ranges. """
	p4_logs = {}
	log_pattern = re.compile(rf"{re.escape(out_base)}_(\d+)-(\d+).p4.log$")
	for filename in os.listdir('.'):
		match = log_pattern.match(filename)
		if match:
			start, end = int(match.group(1)), int(match.group(2))
			p4_logs[(start, end)] = filename
	return p4_logs

def select_logs_for_range(p4_logs, start_rev, end_rev):
	""" Select log files to cover the range as continuously as possible. """
	selected_files = {}
	required_start = start_rev

	# Sort logs by start revision
	sorted_logs = sorted(p4_logs.items(), key=lambda x: x[0][0])

	for (start, end), filename in sorted_logs:
		if start > required_start and selected_files:
			break
		if end >= required_start:
			selected_files[(start, end)] = filename
			required_start = end + 1
			if required_start > end_rev:
				break

	return selected_files

def concatenate_gource_logs(gource_files, final_gource_log):
	""" Concatenate Gource files into one final log. """
	with open(final_gource_log, 'w') as outfile:
		for filename in gource_files:
			with open(filename, 'r') as infile:
				outfile.write(infile.read() + "\n")

def generate_gource(start_rev, end_rev, out_base, include_paths, exclude_paths):
	target_gource_filename = f"{out_base}_{start_rev}-{end_rev}.gource"
	
	if os.path.exists(target_gource_filename):
		print(f"Warning: Using existing file {target_gource_filename}")

	# Build with what we have, result may be larger than desired range on purpose
	p4_logs = discover_p4_logs(out_base)
	selected_logs = select_logs_for_range(p4_logs, start_rev, end_rev)
	gource_files = []
	for key, p4_log_path in selected_logs.items():
		gource_log_path = p4_log_path.replace('.p4.log', '.gource')
		p4_to_gource(p4_log_path, gource_log_path, include_paths, exclude_paths)
		gource_files.append(gource_log_path)

	actual_range = list(selected_logs.keys())
	final_log_path = f"{out_base}_{actual_range[0][0]}-{actual_range[-1][1]}.gource"
	concatenate_gource_logs(gource_files, final_log_path)
	print(f"Gource file created at {final_log_path}")
	print(f"Actual revision range covered: {actual_range[0][0]} to {actual_range[-1][1]}")


# TODO: this needs to run on the gource files trimmed by rev range, so first we need to build the gource file containing the rev range we need
def run_gource(log_pattern, output_video=None):
	base_cmd = [
		"gource", log_pattern, "-1280x720", "--camera-mode", "track",
		"--disable-bloom", "--hide", "filenames", "-a", "1", "-s", "0.5",
		"--user-filter", "buildbot", "--highlight-users", "--highlight-colour", "ffff00"
	]
	if output_video:
		video_cmd = " | ffmpeg -y -r 60 -f image2pipe -vcodec ppm -i - -vcodec libx264 -preset fast -pix_fmt yuv420p -crf 1 -threads 0 -bf 0 " + output_video
		subprocess.run(' '.join(base_cmd) + video_cmd, shell=True)
	else:
		subprocess.run(base_cmd)

if __name__ == "__main__":
	args = parse_args()
	if not args.skip_fetch:
		if args.start_rev and args.end_rev: #TODO: if nothing specified, from 1 to the last one, needs to be determined though
			ranges = calculate_ranges(args.start_rev, args.end_rev, args.batch_size, args.output)
			if ranges:
				fetched_files = fetch_p4_log(args.p4_server, args.p4_user, ranges, args.output)
				# Convert fetched logs to Gource logs
				for p4_log_path in fetched_files:
					gource_log_path = p4_log_path.replace('.p4.log', '.gource')
					p4_to_gource(p4_log_path, gource_log_path, args.include_path, args.exclude_path)
			else:
				print(f"All revisions already fetched")
	else:
		print(f"Skipped fetching revisions")

	if args.fetch_only:
		sys.exit(0)

	generate_gource(args.start_rev, args.end_rev, args.output, args.include_path, args.exclude_path)

	# render
	log_files = f"{args.output}_*.p4.log"
	run_gource(log_files, not args.skip-render)
		   


# usage = "usage: %s [options] [FILE]" % sys.argv[0]
# parser = optparse.OptionParser(usage=usage)
# #old options
# parser.add_option("-o", "--out-file", dest="out", help="output filename, defaults to corvus")
# #parser.add_option("-p", "--path-filter", dest="filter", default="//", help="include only paths starting with FILTER")
# (options, args) = parser.parse_args()

# if options.out:
# 	output = options.out
# else:
# 	output = "p4-gource"

# p4_log = "%s.p4.log" % output
# gource_log = "%s.gource" % output
# gource_log = "%s.gource" % output


# path_include = ["//..."]
# path_exclude = []

# def fetch_p4_log(p4_log_file):
# 	output = subprocess.check_output("p4 changes -m 1").decode("utf-8")
# 	last_change = re.search(r'Change (\d+) .*', output).group(1)
# 	print("Fetching %s changelists" % last_change)
# 	with open(input, "wb") as w:
# 		for i in range(1, int(last_change)):
# 			cl = subprocess.check_output(["p4", "describe", "-s", str(i)])
# 			w.write(cl)
# 			if i % 100 == 0:
# 				print("Now fetching changelist %s" % i)

# #main logic
# print("Fatching p4 log")
# if not os.path.exists(p4_log):
# 	fetch_p4_log(p4_log)

# print("Converting log to gource")
# p4_to_gource(open(p4_log, "r", encoding="ISO-8859-1"), open(gource_log, "w"))

# print("Calling gource")
# #https://github.com/acaudwell/Gource/wiki/Videos
# subprocess.call(["gource-0.47.win64\gource.exe",
# 				 "-1280x720",
# 				 "--camera-mode", "track",
# 				 "--disable-bloom",
# 				 "--hide", "filenames",
# 				 "-a", "1",
# 				 "-s", "0.5",
# 				 "--user-filter", "buildbot",
# 				 "--highlight-users",
# 				 "--highlight-colour", "ffff00",
# 				 #"-o", "%s.ppm" % output, # for video output
# 				 gource_log])

