#!/usr/bin/env python3

"""
Usage:
- Write a tracklist.txt file, with the format
# Title: [TITLE]
# Link: [Link to download of audio file, not required]
REM Genre GENRE

00:00 ARTIST - TRACKTITLE
- In case the artist and track title are reversed, rename the file to
  tracklist_title_artist.txt
- `python3 cue_generator.py /path/to/tracklist.txt` generates the .cue file
- Using xACT, first convert the audio file to e.g. an AIFF in the decode panel
- Using the shntool panel, cut the .aiff file
  It would be a good idea to cut them into a subdirectory "tracks"
- Using the lossy panel, convert the track files back from AIFF to e.g. AAC
  with VBR constrained and 192kpbs
- Use the postprocess_cue_tracks.py script to correctly write the metadata from
  the .cue file to the track files - for some reason, xACT doesn't do this 
  during the shntool stage:
  `python3 postprocess_cue_tracks.py /path/to/tracklist.cue`
  This call assumes the tracks to be in the subdirectory /path/to/tracks
  Otherwise, this path needs to be given via --tracks-dir
  See the script for further details
"""

import os
import sys

ORDER_ARTIST_FIRST = True

def get_tracklist_input_file():
	try:
		file_path = sys.argv[1]
	except:
		raise Exception("Missing file path as argument!")
	if os.path.exists(file_path):
		return file_path
	raise Exception("Can't find input file :(")

def read_input_file(path):
	with open(path, "r") as file:
		# content = file.read()
		
		content = []
		line = file.readline()
		
		while line:
			line = line.replace("\n", "")
			content.append(line)
			line = file.readline()

	return content

def construct_output_file_path(input_path):
	return ".".join(input_path.split(".")[:-1]) + ".cue"

def is_timestamp(string):
	for character in string:
		if character.isdigit() or character == ":":
			continue
		return False
	return True

def get_min_sec_from_timestamp(timestamp_string):
	digits = timestamp_string.split(":")
	if len(digits) == 2:
		return (int(digits[0]), int(digits[1]))
	if len(digits) == 3:
		return (int(digits[0])*60 + int(digits[1]), int(digits[2]))
	raise Exception(f"Invalid timestamp: {timestamp_string}")

def get_string1(full_line):
	return full_line.split(" - ")[0].split(":")[-1][3:]

def get_string2(full_line):
	try:
		return full_line.split(" - ")[1]
	except:
		return "UNKNOWN"

def parse_input_file(contents):
	track_counter = 1
	return_string = ""

	for line in contents:
		if line.startswith("Title:") or line.startswith("# Title:"):
			return_string += f"TITLE \"{line.split("Title: ")[-1]}\"\n"
			continue

		# Ignore empty line
		if line == "":
			continue

		# This is possibly a timestamp
		first_substring = line.split(" ")[0]
		
		# If this is a timestamp, convert it to a track record
		if is_timestamp(first_substring):

			artist = get_string1(line)
			title  = get_string2(line)
			if not ORDER_ARTIST_FIRST:
				artist, title = title, artist

			minutes, seconds = get_min_sec_from_timestamp(first_substring)			

			return_string += f"  TRACK {str(track_counter).zfill(2)} AUDIO\n"
			return_string += f"    TITLE \"{title}\"\n"
			return_string += f"    PERFORMER \"{artist}\"\n"
			return_string += f"    INDEX 01 {str(minutes).zfill(2)}:{str(seconds).zfill(2)}\n"

			track_counter += 1

	return return_string
	

if __name__ == "__main__":
	try:
		in_file_path = get_tracklist_input_file()
	except Exception as e:
		print(e)
		exit(1)

	if "_title_artist." in in_file_path:
		ORDER_ARTIST_FIRST = False

	try:
		in_file = read_input_file(in_file_path)
	except Exception as e:
		print(e)
		exit(1)

	try:
		parse_result = parse_input_file(in_file)
		print(parse_result)
		
		with open(construct_output_file_path(in_file_path), "w+") as out_file:
			out_file.write(parse_result)
	except Exception as e:
		print(e)
		exit(1)
