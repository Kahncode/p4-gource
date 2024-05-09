#!  /usr/bin/python

# TODO: improvement ideas, use -ztag output for the log fetching, and immediately discard based on include/exclude list, this will help make the resulting files a lot smaller
# which also means we would probably generate the gource file directly instead of doing it in two steps, but it requires changing all the parsing and converting

import argparse
import os
import re
import subprocess
import sys
import time
import platform

p4_server = None
p4_user = None
verbose = False

def parse_args():
	parser = argparse.ArgumentParser(description="Extract Perforce data to generate a visualization using Gource. Requires Gource (https://gource.io/).")
	parser.add_argument("-u", "--p4-user", type=str, help="Perforce username")
	parser.add_argument("-p", "--p4-server", type=str, help="Perforce server address")
	parser.add_argument("-i", "--include-path", action="append", default=[], help="Include paths for filtering (can specify multiple)")
	parser.add_argument("-x", "--exclude-path", action="append", default=[], help="Exclude paths for filtering (can specify multiple)")
	parser.add_argument("-o", "--output", type=str, default="p4-gource", help="Base name for output files")
	parser.add_argument("-s", "--start-rev", type=int, default=1, help="Starting changelist number")
	parser.add_argument("-e", "--end-rev", type=int, default=None, help="Ending changelist number")
	parser.add_argument("-b", "--batch-size", type=int, default=1000, help="Number of changelists per batch when fetching logs")
	parser.add_argument("-m", "--regex-match", action="append", default=[], help="Match and reduce paths using regex, requires a replace regex (can specify multiple)")
	parser.add_argument("-r", "--regex-replace", action="append", default=[], help="Reduce paths using regex, requires a match regex (can specify multiple)")
	parser.add_argument("-v", "--verbose", action="store_true", default=False, help="Verbose logging")
	parser.add_argument("--fetch-only", action="store_true", default=False, help="Only fetch logs from P4, do not run Gource or video rendering")
	parser.add_argument("--skip-fetch", action="store_true", default=False, help="Do not fetch, only run Gource and video rendering")
	parser.add_argument("--skip-init", action="store_true", default=False, help="Do not add the list of files present in the repository, only visualize changes in the revision range")
	parser.add_argument("--skip-render", action="store_true", default=False, help="Open gource interactive, do not render video")
	parser.add_argument("--interactive", action="store_true", default=False, help="Lets the user interact with Gource, do no close it automatically")
	parser.add_argument("--gource-args", nargs=argparse.REMAINDER, help="Additional arguments to pass to Gource")

	args = parser.parse_args()
	if not args.end_rev:
		args.end_rev = get_latest_changelist()

	global p4_server
	p4_server = args.p4_server
	global p4_user
	p4_user = args.p4_user

	global verbose
	verbose = args.verbose

	if args.regex_match and args.regex_replace and len(args.regex_match) == len(args.regex_replace):
		pass
	elif not args.regex_match and not args.regex_replace:
		pass
	else:
		raise RuntimeError(f"All match patterns must have a corresponding replace pattern: {zip(args.regex_match, args.regex_replace)}")

	return args

def p4_cmd(args):
	cmd = ["p4"]
	if p4_server is not None:
		cmd.extend(["-p", p4_server])
	if p4_user is not None:
		cmd.extend(["-u", p4_user])
	if args is not None:
		cmd.extend(args)
	return cmd

def get_latest_changelist():
	# Run the p4 changes command to get the latest changelist
	output = subprocess.check_output(p4_cmd(["-ztag", "changes", "-m", "1"]), stderr=subprocess.STDOUT, text=True)

	# Parse the output using regular expressions
	changelist_match = re.search(r'change (\d+)', output)

	if changelist_match:
		changelist_number = int(changelist_match.group(1))
		return changelist_number
	else:
		raise RuntimeError("Failed to parse latest changelist number")

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
		current_rev = max(start_rev, end + 1)

	# Check for any remaining revisions after the last merged range
	while current_rev <= end_rev:
		next_batch_end = min(current_rev + batch_size - 1, end_rev)
		needed_ranges.append((current_rev, next_batch_end))
		current_rev = next_batch_end + 1

	return needed_ranges

def fetch_p4_log(ranges, out_base, include_paths, exclude_paths):
	fetched_files = []
	for start, end in ranges:
		temp_log_filename = f"{out_base}_{start}-{end}_temp.p4.log"
		final_log_filename = f"{out_base}_{start}-{end}.p4.log"

		print(f"Fetching changelists from {start} to {end}")
		with open(temp_log_filename, "w", encoding='utf-8') as log_file:
			error_occurred = False  # Flag to track if any error occurred
			for i in range(start, end + 1):
				if (i - start) % 100 == 99: # Just to keep printing for heartbeat to the user
					print(f"Fetching changelist {i}")

				cmd = p4_cmd(["describe", "-s", str(i)])
				
				max_retries = 5
				retry_count = 0
				success = False
				while not success and retry_count < max_retries:
					try:
						cl = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
						# Check each line of the fetched log
						changelist_description = ""
						changelist_contains_files = False
						for lineb in cl.splitlines():
							try:
								line = lineb.decode('utf-8')
							except UnicodeDecodeError:
								# Try decoding with a different encoding
								line = lineb.decode('latin-1')

							if not line:
								continue 

							if "no such changelist" in line:
								break # Skip this changelist, Perforce has many CL numbers not taken by actual changelists

							file_match = p4_file.match(line)
							if file_match:
								file_path = file_match.group("file")
								if filter_file(file_path, include_paths, exclude_paths):
									changelist_description += line + '\n'
									changelist_contains_files = True
							else:
								changelist_description += line + '\n'

						if changelist_contains_files:
							log_file.write(changelist_description)
									
					except Exception as e:
							print(f"Error fetching changelist {i}: {str(e)}")
							
							retry_count += 1
							print(f"Retry changelist {i} {retry_count}")
					else:
						success = True
				
				if not success:
					error_occurred = True
					break

		if not error_occurred:
			# Rename the temp log file to the final log file if no errors occurred
			os.rename(temp_log_filename, final_log_filename)
			fetched_files.append(final_log_filename)
		else:
			# Leave the temp file for potential diagnosis and recovery, as an error file
			os.rename(temp_log_filename, "ERROR_" + final_log_filename)
			raise Exception(f"Error occurred during fetching, check logs for more details.")
		
	return fetched_files

def format_perforce_search_path(path):
	# Format the given path for Perforce, adding ... wildcard if necessary
	if path.endswith("..."):
		return path
	elif path.endswith("/"):
		return path + "..."
	else:
		return path + "/..."

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
	if filter_file.include_regexes:
		if not any(regex.match(file) for regex in filter_file.include_regexes):
			return False
	# Check if file matches any exclude pattern
	if filter_file.exclude_regexes:
		if any(regex.match(file) for regex in filter_file.exclude_regexes):
			return False
	return True

def reduce_path(path, regex_matches, regex_replaces):
	"""Reduce the path by applying regex matches and replacements."""
	reduced_path = path
	for regex_match, regex_replace in zip(regex_matches, regex_replaces):
		new_reduced_path = re.sub(regex_match, regex_replace, reduced_path)
		if new_reduced_path != reduced_path:
			if verbose:
				print(f"Reduced {reduced_path} to {new_reduced_path}")
			reduced_path = new_reduced_path
	return reduced_path

# Compile regex patterns outside of the function to compile them only once
p4_entry = re.compile(r"^Change \d+ by (?P<author>\S+)@\S+ on (?P<timestamp>\S+ \S+)\s*(?P<pending>\*pending\*)?\s*$")
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

def p4_to_gource(p4_log_path, gource_log_path, include_paths, exclude_paths, regex_match, regex_replace):
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
					action_code = p4_action_to_gource.get(file.group("action"), "M")
					pretty_file = reduce_path(file.group('file'), regex_match, regex_replace)
					formatted_entry = f"{timestamp}|{author}|{action_code}|{pretty_file}\n"
					gource_log.write(formatted_entry)


def fetch_p4_init(first_revision, out_base, include_paths, exclude_paths, regex_match, regex_replace):
	output_filename = f"{out_base}_init_{first_revision}.gource"
	
	if os.path.exists(output_filename):
		print(f"Warning: Using existing file {output_filename}")
		return output_filename
	
	# Format include filters for Perforce
	search_paths = [format_perforce_search_path(path) for path in include_paths]

	# Generate the Gource log file with fake initial revisions
	try:
		with open(output_filename, "w") as f:
			for path in search_paths:
				cmd = p4_cmd(["files", "-e", f"{path}@{first_revision}"])
			
				output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
				if "no such file(s)" in output:
					continue

				for line in output.splitlines():
					match = re.match(r"^(.+?)#(\d+) - (\w+) change (\d+)", line)
					if match:
						file, rev, action, changelist = match.groups()
						if filter_file(file, include_paths, exclude_paths):
							action_code = p4_action_to_gource.get(action, "M")
							pretty_file = reduce_path(file, regex_match, regex_replace)
							formatted_entry = f"0|init|{action_code}|{pretty_file}\n"
							f.write(formatted_entry)
	except subprocess.CalledProcessError as e:
		print(f"Error running p4 files command for path {path}: {str(e)}")
		# Remove the partially written file if it exists
		if os.path.exists(output_filename):
			os.remove(output_filename)
		return None  # Or handle the error in another way
	
	print(f"Generated initial revisions file: {output_filename}")
	return output_filename

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
				outfile.write(infile.read())

def generate_gource(start_rev, end_rev, out_base, include_paths, exclude_paths, skip_init, regex_match, regex_replace):
	target_gource_filename = f"{out_base}_{start_rev}-{end_rev}.gource"
	
	if os.path.exists(target_gource_filename):
		print(f"Warning: Using existing file {target_gource_filename}")
		return target_gource_filename

	# Build with what we have, result may be larger than desired range on purpose
	p4_logs = discover_p4_logs(out_base)
	selected_logs = select_logs_for_range(p4_logs, start_rev, end_rev)
	gource_files = []
	for key, p4_log_path in selected_logs.items():
		gource_log_path = p4_log_path.replace('.p4.log', '.gource')
		p4_to_gource(p4_log_path, gource_log_path, include_paths, exclude_paths, regex_match, regex_replace)
		gource_files.append(gource_log_path)

	actual_range = list(selected_logs.keys())

	if not skip_init:
		#fetch or create "init" gource file, which contains a view of all the files present in the repository at the first revision
		first_revision = actual_range[0][0]
		gource_files.insert(0, fetch_p4_init(first_revision, out_base, include_paths, exclude_paths, regex_match, regex_replace))

	target_gource_filename = f"{out_base}_{actual_range[0][0]}-{actual_range[-1][1]}.gource"
	concatenate_gource_logs(gource_files, target_gource_filename)
	print(f"Gource file created at {target_gource_filename}")
	print(f"Actual revision range covered: {actual_range[0][0]} to {actual_range[-1][1]}")
	return target_gource_filename

def find_gource_executable():
	""" Attempt to run Gource commands and return the first successful one. """
	commands = ["gource"]  # Default command for Unix-like systems
	if platform.system() == "Windows":
		# Add Windows-specific executables
		commands.extend(["gource.cmd", "gource.exe"])

	for command in commands:
		try:
			# Use subprocess.Popen to interact with Gource's interactive prompt
			process = subprocess.Popen([command, "-help"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
			# Send an "Enter" key press to proceed through the interactive prompt
			process.communicate(input='\n')
			# Wait for the process to complete
			process.wait()
			# Check if the process terminated successfully
			if process.returncode == 0:
				print(f"{command} is available and functional.")
				return command
			else:
				print(f"{command} was found but failed to execute properly.")
		except FileNotFoundError:
			continue

	raise EnvironmentError("No valid Gource executable found.")

def run_gource(gource, gource_log_path, gource_args, interactive, output_video, out_base):
	print("Running Gource")
	base_cmd = [gource, gource_log_path]

	if gource_args:
		base_cmd.extend(gource_args)

	if output_video:

		if not interactive:
			base_cmd.extend(["--stop-at-end", "--disable-input"])

		output_filename = f"{out_base}.mp4"

		base_cmd.extend(["-o", "-"])

		# TODO: improve FFMPEG parameters as it produces video that are not compressed enough
		ffmpeg_cmd = [
			"ffmpeg", "-y", "-r", "60", "-f", "image2pipe", "-vcodec", "ppm", "-i", "-",
			"-vcodec", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-crf", "1",
			"-threads", "0", "-bf", "0", output_filename
		]

		print("Executing Gource:", ' '.join(base_cmd))
		print("Executing FFmpeg:", ' '.join(ffmpeg_cmd))

		gource_output = subprocess.Popen(base_cmd, stdout=subprocess.PIPE)
		ffmpeg_process = subprocess.run(ffmpeg_cmd, stdin=gource_output.stdout)

	else:
		print("Executing Gource:", ' '.join(base_cmd))
		subprocess.run(base_cmd, check=True)

if __name__ == "__main__":
	args = parse_args()

	gource = find_gource_executable()

	if not args.skip_fetch:
		if args.start_rev >= 1 and args.end_rev > args.start_rev:
			print(f"Fetching revision range: {args.start_rev} to {args.end_rev}")
			ranges = calculate_ranges(args.start_rev, args.end_rev, args.batch_size, args.output)
			if ranges:
				fetched_files = fetch_p4_log(ranges, args.output, args.include_path, args.exclude_path)
				# Convert fetched logs to Gource logs
				for p4_log_path in fetched_files:
					gource_log_path = p4_log_path.replace('.p4.log', '.gource')
					p4_to_gource(p4_log_path, gource_log_path, args.include_path, args.exclude_path, args.regex_match, args.regex_replace)
			else:
				print(f"All revisions already fetched")
		else: 
			raise RuntimeError("Invalid revision range: {args.start_rev} to {args.end_rev}")
	else:
		print(f"Skipped fetching revisions")

	if args.fetch_only:
		sys.exit(0)

	#generate_gource_log
	gource_log_path = generate_gource(args.start_rev, args.end_rev, args.output, args.include_path, args.exclude_path, args.skip_init, args.regex_match, args.regex_replace)

	# render
	run_gource(gource, gource_log_path, args.gource_args, args.interactive, not args.skip_render, args.output)

	print(f"Done")