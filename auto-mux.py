import json
import mimetypes
import os
import re
import subprocess
import sys
import time

def main():
	# These variables may be set by shell arguments
	folderToScan = os.getcwd()
	bFilmMode    = False

	# Languages to include when remuxing the file.
	# Language codes follow ISO 639-1 / 639-2.
	langToKeep = [
		"eng",
		"mul", # "multiple languages"
	]

	if len(sys.argv) > 1:
		for arg in sys.argv:
			if arg.lower() == "f":
				bFilmMode = True

			elif os.path.exists('"{}"'.format(arg)):
				folderToScan = arg

			# additional languages may be specified, e.g. "lang:jap"
			elif arg.find("lang:") == 0:
				langArgs = [code.lower() for code in arg[len("lang:"):].split(",") if code.strip() != ""]
				langToKeep.extend(langArgs)

	# Output path for remuxed files
	timestamp  = time.strftime("%Y-%m-%d")
	outputPath = os.path.join(folderToScan, "auto-mux " + timestamp)

	# Executables
	mkvmergePath = "/cygdrive/c/program files/mkvtoolnix/mkvmerge.exe"
	filebotPath  = "/cygdrive/c/program files/filebot/filebot.launcher.exe"

	if not os.path.isfile(mkvmergePath):
		print("Invalid mkvmerge executable path.")
		return

	if not os.path.isfile(filebotPath):
		print("Invalid FileBot executable path.")
		return

	# FileBot settings passed as command line arguments
	filebotSettings = {
		"film": {
			"db": "TheMovieDB",
			"format": R"{n.colon(' - ')}"
		},
		"tv": {
			"db": "TVmaze",
			"format": R"{e00} - {t.colon(' - ')}"
		}
	}

	totalDataRemoved = 0

	# File extensions to include in the file search.
	allowedExtensions = (
		".mkv",
		".m2ts",
		".m4v",
		".mp4",
		".ts",
		".vob",
	)

	# Cover image file, assumed to be named "cover.jpg" (or other filetypes).
	# If present, this will be populated during the scan for media files below.
	cover = {}

	# Search for media files in the current directory.
	# files is a list of dicts containing filenames, paths, and sizes.
	files = []

	print("\nRunning script in {mode} mode; scanning for files...\n".format(mode = "film" if bFilmMode else "TV"))

	for file in os.listdir(folderToScan):
		fileExt = os.path.splitext(file)[1]

		# Check for media files.
		if fileExt in allowedExtensions:
			files.append({
				"name"        : file,
				"name_no_ext" : os.path.splitext(file)[0],
				"path"        : cygwinPathToWinPath(os.path.join(folderToScan, file)),
				"size"        : os.path.getsize(file)
			})

		# Check for a cover file if one hasn't been found already.
		elif not cover and re.search(r"^cover\.(jp(e)?g|png|gif|bmp)$", file.lower()):
			cover["filename"] = file
			cover["mimetype"] = mimetypes.guess_type(file)[0]

	# No media files found in the current directory.
	# Assume it's a blu-ray folder and search for m2ts files.
	if not files:
		print("No files found; searching for Blu-ray files...")
		print()

		for root, directories, filenames in os.walk(folderToScan):

			# Main media files are contained within a folder called STREAM.
			if re.search(r"(\\|\/)STREAM$", root):

				# Work under the assumption that the largest
				# file in the STREAM folder is the film/TV show.
				largestFile = {}

				# Begin searching the STREAM folder.
				for filename in filenames:

					# Ensure it's a media file.
					fileExt = os.path.splitext(filename)[1]

					if fileExt in allowedExtensions:
						currentFile = os.path.join(root, filename)
						currentSize = os.path.getsize(currentFile)

						# If largestFile is empty, this is the first file being processed, so append it.
						# Otherwise, compare the filesize to the largest media file found so far.
						if not largestFile or currentSize > largestFile["size"]:
							largestFile = {
								"path": cygwinPathToWinPath(currentFile),
								"size": currentSize
							}

				# If a media file has been found, get the file's parent folder name.
				if largestFile:

					# Parent folder (typically \TvShow\BDMV\)
					folderName = os.path.split(root)[0]

					# Traverse folders upwards until we're out of \BDMV\STREAM\
					# This will give us a name to use for the file instead of 00000.m2ts
					while re.search(r"(\\|\/)BDMV$", folderName):

						# Get the parent folder.
						folderName = os.path.split(folderName)[0]

						# If the folder name above no longer contains BDMV,
						# set folderName which will end the while loop.
						if not re.search(r"(\\|\/)BDMV$", folderName):
							folderName = os.path.split(folderName)[1]

					# Append the name to the largest file's dict.
					largestFile["name"]        = folderName + ".mkv"
					largestFile["name_no_ext"] = folderName

					# Finally, append the file.
					files.append(largestFile)

	# No files found at all - stop the script.
	if not files:
		print("No media files detected.")

	# Iterate through each media file and get file data JSON from mkvmerge.exe
	else:
		currentFile = 0
		totalFiles  = len(files)

		for file in files:
			currentFile += 1

			# File data in JSON format, as returned by mkvmerge command line.
			fileInfo = json.loads(subprocess.check_output('"{}" "{}" -i -F json'.format(mkvmergePath, file["path"]), shell = True))

			# Tracks which match language codes specified in langToKeep.
			tracksToKeep = {}

			# Tracks which will be removed. This dict is only used to show a summary in the shell.
			tracksToRemove = {}

			# Tracks with no language set (defaults to "und", i.e. undefined).
			undTracks = {}

			# Check if the file has a title property.
			try:
				title = fileInfo["container"]["properties"]["title"]
			except:
				title = None

			# Output filename and title, if possible.
			currentFileStr = "({}/{})".format(currentFile, totalFiles)

			if title:
				print_sep("{} {} | {}".format(currentFileStr, file["name"], title), "=")
			else:
				print_sep("{} {}".format(currentFileStr, file["name"]), "=")

			# Iterate through each track and sort into dictionaries defined above.
			for track in fileInfo["tracks"]:
				info = {}

				# Not every track has a language property,
				# so manually set to und if necessary.
				try:
					lang = track["properties"]["language"]
				except:
					lang = "und"

				# Create a dict of the track ID/codec/language.
				info["id"]    = track["id"]
				info["codec"] = track["codec"]
				info["lang"]  = lang

				# If possible, also add the track's name.
				try:
					info["name"] = track["properties"]["track_name"]
				except:
					pass

				# If the language is in langToKeep or und, append to tracksToKeep.
				if lang == "und" or lang in langToKeep:
					try:
						tracksToKeep[track["type"]].append(info)
					except:
						tracksToKeep[track["type"]] = [info]

				# Otherwise, append to tracksToRemove.
				else:
					try:
						tracksToRemove[track["type"]].append(info)
					except:
						tracksToRemove[track["type"]] = [info]

				# Also add undefined tracks to undTracks to alert the user.
				if track["type"] != "video" and lang == "und":
					try:
						undTracks[track["type"]].append(info)
					except:
						undTracks[track["type"]] = [info]

			# Ensure that the file will still have video/audio.
			if "video" not in tracksToKeep or "audio" not in tracksToKeep:
				print('No video or audio tracks matching language codes "{}"; skipping file.'.format(", ".join(langToKeep)))

			# Finally, begin rebuilding the file.
			else:
				# Show a warning if there are und tracks present.
				if undTracks:
					print("WARNING: the following tracks have an undefined language and will not be modified:")
					print()
					printTracksSummary(undTracks)

				# Show summary of tracks that will be removed.
				if tracksToRemove:
					print_sep("Removing the following tracks:")
					printTracksSummary(tracksToRemove)

				# Show summary of tracks being kept.
				if tracksToKeep:
					print_sep("Keeping the following tracks:")
					printTracksSummary(tracksToKeep)

				# Start to construct the shell argument.
				trackIdsArg = ""

				for mediaType in tracksToKeep:
					if mediaType == "audio" or mediaType == "subtitles":
						trackIds = []

						for track in tracksToKeep[mediaType]:
							trackIds.append(str(track["id"]))

						trackIdsArg += " -{} {}".format(mediaType[0], ",".join(trackIds))

				# If there's a cover file present, add the --attach-file parameter.
				if cover:
					trackIdsArg += " --attachment-mime-type {} --attach-file {}".format(cover["mimetype"], cover["filename"])

				# Create output folder.
				if not os.path.exists(outputPath):
					os.makedirs(outputPath)

				outputFilePath = os.path.join(outputPath, "{}.mkv".format(file["name_no_ext"]))

				# Format the final shell command.
				muxArguments = '"{}" -o "{}" --title "" --track-name -1:"" {} --compression -1:none -M "{}"'.format(
					mkvmergePath,
					cygwinPathToWinPath(outputFilePath),
					trackIdsArg.strip(),
					file["path"]
				)

				print_sep("Running mkvmerge with command:")
				print(muxArguments)
				print()

				# Execute the command.
				mkvOutput = subprocess.check_output(muxArguments, shell = True).decode()

				print(mkvOutput)

				# If the new file has been written, calculate the filesize reduction.
				if os.path.isfile(outputFilePath):
					oldSize     = file["size"]
					newSize     = os.path.getsize(outputFilePath)
					difference  = oldSize - newSize
					diffPercent = round(difference / oldSize * 100, 2)

					# Filesize may increase if no tracks are removed but an attachment is added.
					diffVerb = "reduced" if newSize < oldSize else "increased"

					print("File {} from {} to {} (difference of {} / {}%).".format(
						diffVerb,
						readableFileSize(oldSize),
						readableFileSize(newSize),
						readableFileSize(difference),
						diffPercent
					))

					# Update the total amount of data removed this session.
					totalDataRemoved += difference

			print()
			print()

		# Rename files using FileBot.
		if os.path.exists(outputPath):

			# Get settings for the current media type.
			if bFilmMode:
				settings = filebotSettings["film"]
			else:
				settings = filebotSettings["tv"]

			# Construct the command.
			filebotCommand = '"{}" -rename "{}" --db {} --format "{}" -non-strict'.format(
				filebotPath,
				cygwinPathToWinPath(outputPath),
				settings["db"],
				settings["format"]
			)

			try:
				# Run the command.
				print("\nRenaming files using {}...\n".format(settings["db"]))

				filebotOutput = subprocess.check_output(filebotCommand, shell = True).decode()
				renamedFiles  = getRenamedFiles(filebotOutput)

				if (renamedFiles):
					print("\n".join(["{old}   ->   {new}".format(old = file[0], new = file[1]) for file in renamedFiles]))
				else:
					print(filebotOutput)

				# Save output to log file.
				logPath = os.path.join(outputPath, "filebot_log.txt")

				with open(logPath, "a") as f:
					f.write("{}\n\n\n".format(filebotOutput.strip()))

				# Create a folder for each file if remuxing films
				if bFilmMode:
					for file in renamedFiles:
						filmName   = os.path.splitext(file[1])[0]
						filePath   = os.path.join(outputPath, file[1])
						filmFolder = os.path.join(outputPath, filmName)
						newPath    = os.path.join(filmFolder, file[1])

						if not os.path.exists(filmFolder):
							os.makedirs(filmFolder)

						os.rename(filePath, newPath)

			except:
				print("\nUnable to rename files.\n")

		# Output total data removed this session.
		if totalDataRemoved:
			print()
			print_sep("Total data removed: {}".format(readableFileSize(totalDataRemoved)))

		# Finished.
		print()
		print("Finished at {}.".format(time.strftime("%H:%M:%S")))

# size.py by cbwar
# https://gist.github.com/cbwar/d2dfbc19b140bd599daccbe0fe925597
def readableFileSize(num, suffix = "B"):
	for unit in ["", "k", "M", "G", "T", "P", "E", "Z"]:
		if abs(num) < 1024:
			return "%3.1f%s%s" % (num, unit, suffix)
		num /= 1024

	return "%.1f%s%s" % (num, "Yi", suffix)

# Convert a cygwin path to a Windows path.
# e.g. /cygdrive/d/MyMediaFolder/MyFile.mkv -> D:\MyMediaFolder\MyFile.mkv
def cygwinPathToWinPath(path):

	# Get rid of cygdrive root and insert colon after drive letter.
	if path.find("/cygdrive/") == 0:
		path = path.replace("/cygdrive/", "")
		path = path[0].upper() + ":" + path[1:]

	# Change slashes.
	path = path.replace("/", "\\")

	return path

# Print a single-line summary for a group of tracks.
def printTracksSummary(tracks):
	for mediaType in tracks:
		print(mediaType.capitalize() + ":")

		for track in tracks[mediaType]:
			summary = "ID: {} | Codec: {} | Language: {}".format(track["id"], track["codec"], track["lang"])

			try:
				summary += " | Name: " + track["name"]
			except:
				pass

			print(summary)

		print()

# Print reduced version of Filebot output.
def getRenamedFiles(shellOutput):
	renamedFiles = []

	for line in shellOutput.split("\n"):
		line = line.strip()

		if line != "" and line.find("[MOVE]") == 0:
			filePair = line.split("] to [")
			fileFrom = filePair[0][len("[MOVE] From ["):]
			fileTo   = filePair[1][:-1]
			fnFrom   = fileFrom.split("\\")[-1]
			fnTo     = fileTo.split("\\")[-1]

			renamedFiles.append((fnFrom, fnTo))

	return renamedFiles

# Add rows of characters to act as separators in shell output.
def print_sep(string, char = "-"):
	minStrLen = 25

	if len(string) < minStrLen:
		amt = minStrLen
	else:
		amt = len(string)

	s = "".join([char for x in range(0, amt)])
	print("\n".join((s, string, s)))


# Pretty print JSON/dictionaries.
def pprint(dictionary):
	print(json.dumps(dictionary, indent=4))


# Run the script.
if __name__ == "__main__":
	main()
