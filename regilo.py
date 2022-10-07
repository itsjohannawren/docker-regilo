#!/usr/bin/env bash
"""" &>/dev/null

__DIR__="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd -P 2>/dev/null)"
if [ -z "${__DIR__}" ]; then
	echo "Error: Failed to determine directory containing this script" 1>&2
	exit 1
fi

while [ "${__DIR__}" != "/" ]; do
	if [ -f "${__DIR__}/pyvenv.cfg" ] && [ -f "${__DIR__}/bin/activate" ] && [ -h "${__DIR__}/bin/python" ]; then
		exec "${__DIR__}/bin/python" "${0}" "${@}"
	fi
	__DIR__="$(dirname "${DIR}")"
done

exec "python3" "${0}" "${@}"
# """
# ==============================================================================

import asyncio
import datetime
import grp
import hashlib
import json
import os
import pwd
import re
import selectors
import shlex
import signal
import subprocess
import sys
import textwrap
import threading
import time

from croniter import croniter
from icecream import ic

# ==============================================================================

CONFIG_JSON = "/etc/regilo.json"
STARTUP_STATE_PATH = "/var/startup"
INDENT_STRING = "   "

# ==============================================================================

def sha256Hex (data:(str | bytes)) -> str:
	_hash = hashlib.sha256 ()
	_hash.update (data if isinstance (data, bytes) else bytes (data, "utf8"))
	return _hash.hexdigest ().lower ()

def generateKey (*args):
	key = []

	_args = args
	if len (args) == 1 and isinstance (args [0], dict):
		_args = []
		for dict_key in sorted (args [0].keys ()):
			_args.append (dict_key)
			_args.append (args [0][dict_key])

	for arg in _args:
		if isinstance (arg, bytes):
			key.append (str (arg, "ascii"))

		elif isinstance (arg, dict):
			_list = []
			for dict_key, dict_value in arg.items ():
				_list.append ([dict_key, dict_value])
			_list.sort (key = lambda entry: entry [0])
			key.append (_list)

		else:
			key.append (arg)

	key = json.dumps (key, separators = (",", ":"))

	return sha256Hex (key)

# ==============================================================================

def ansiColorParse (data:str, foreground = True) -> str:
	vga_map = {
		"black": 30,
		"red": 31,
		"green": 32,
		"yellow": 33,
		"blue": 34,
		"magenta": 35,
		"cyan": 36,
		"white": 37
	}

	if data.lower () in vga_map:
		if foreground == True:
			return str (vga_map [data.lower ()])
		else:
			return str (vga_map [data.lower ()] + 10)

	if re.search (r"^(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9][0-9]|[0-9])$", data) is not None:
		return "5;" + data

	components = re.search (r"(?i)^#?(?P<red>[0-9a-f]{2})(?P<green>[0-9a-f]{2})(?P<blue>[0-9a-f]{2})$", data)
	if components is not None:
		return "2;%i;%i;%i" % (
			int (components ["red"], base = 16),
			int (components ["green"], base = 16),
			int (components ["blue"], base = 16)
		)

	return None

def ansiColor (
	reset:bool = False,
	bright:bool = False,
	faint:bool = False,
	italic:bool = False,
	underline:bool = False,
	blink:bool = False,
	strikeout:bool = False,
	double_underline:bool = False,
	framed:bool = False,
	encircled:bool = False,
	overlined:bool = False,

	foreground:str = None,
	background:str = None,
) -> str:
	codes = []

	if reset == True:
		codes.append ("0")
	if bright == True:
		codes.append ("1")
	if faint == True:
		codes.append ("2")
	if italic == True:
		codes.append ("3")
	if underline == True:
		codes.append ("4")
	if blink == True:
		codes.append ("5")
	if strikeout == True:
		codes.append ("9")
	if double_underline == True:
		codes.append ("21")
	if framed == True:
		codes.append ("51")
	if encircled == True:
		codes.append ("52")
	if overlined == True:
		codes.append ("53")

	if foreground is not None:
		fg = ansiColorParse (foreground)
		if fg is not None:
			codes.append (fg)

	if background is not None:
		bg = ansiColorParse (background, foreground = False)
		if bg is not None:
			codes.append (bg)

	return "\x1b[" + ";".join (codes) + "m"

# ==============================================================================

INDENT = 0

def indent ():
	INDENT = INDENT + 1

def outdent ():
	INDENT = INDENT - 1
	if INDENT < 0:
		INDENT = 0

def wrapOutput (string:str, color:bool = True):
	lines = string.split ("\n")
	for line in lines:
		if color == True:
			print ("%s%7s%s | %s%s%s" % (ansiColor (reset = True), "", ansiColor (bright = True, foreground = "white"), ansiColor (reset = True), INDENT_STRING * INDENT, line))
		else:
			print ("%7s | %s%s" % ("", INDENT_STRING * INDENT, line))

def message (prefix:str, string:str, prefix_ansi:str = None, color:bool = True):
	_prefix = prefix [0:7]
	first = True
	lines = string.split ("\n")
	for line in lines:
		if first == True:
			first = False
			if color == True and prefix_ansi is not None:
				print ("%s%7s%s | %s%s%s" % (prefix_ansi, _prefix, ansiColor (reset = True, bright = True, foreground = "white"), INDENT_STRING * INDENT, line, ansiColor (reset = True)))
			else:
				print ("%7s | %s%s" % (_prefix, INDENT_STRING * INDENT, line))
		else:
			print ("%7s | %s%s" % ("", INDENT_STRING * INDENT, line))

def debug (string:str, color:bool = True):
	message ("Debug", string, ansiColor (reset = True, bright = True, foreground = "cyan"), color)

def info (string:str, color:bool = True):
	message ("Info", string, ansiColor (reset = True, bright = True, foreground = "white"), color)

def notice (string:str, color:bool = True):
	message ("Notice", string, ansiColor (reset = True, bright = True, foreground = "green"), color)

def warning (string:str, color:bool = True):
	message ("Warning", string, ansiColor (reset = True, bright = True, foreground = "yellow"), color)

def error (string:str, color:bool = True):
	message ("Error", string, ansiColor (reset = True, bright = True, foreground = "red"), color)

def fatal (string:str, color:bool = True):
	message ("Fatal", string, ansiColor (reset = True, bright = True, blink = True, foreground = "red"), color)
	os._exit (1)

def separator (character:str = "-", width:int = 80, color:bool = True, pad:bool = True):
	if pad == True:
		print ("")

	if color == True:
		print ("%s%s%s" % (ansiColor (reset = True, bright = True, foreground = "black"), character * width, ansiColor (reset = True)))
	else:
		print (character * width)

	if pad == True:
		print ("")

# ==============================================================================

def banner_print (
	title:str,
	subtitle:str = None,
	description:str = None,
	urls:dict = None,
	repositories:dict = None,
	authors: list[dict] = None,
	contributors: list[dict] = None,

	color:bool = True
):
	banner = """
%%%%s                        ____            ____
        _      ______ _/ / /____  _____/ __/___ ___
       | | /| / / __ `/ / __/ _ \\/ ___/ /_/ __ `__ \\
       | |/ |/ / /_/ / / /_/  __/ /  / __/ / / / / /
       |__/|__/\\__,_/_/\\__/\\___/_(_)/_/ /_/ /_/ /_/
%%%%s   _______________________________________________  _____    ___
  /                                              / /    /   /  /
 /%%%%s  %%s%%%%s%%-%is  %%%%s/ /    /   /  /
/______________________________________________/ /____/   /__/%%%%s"""
	banner_space = 42
	banner_indent = 4

	padding = banner_space - len (title)
	if padding <= 1:
		subtitle = None
	if padding < 0:
		title = title [0:banner_space]

	if subtitle is not None and padding - len (subtitle) - 1 < 0:
		subtitle = subtitle [0:padding -1]

	banner = banner % (padding,)
	banner = banner % (
		title,
		" " + subtitle if subtitle is not None else ""
	)

	if color == True:
		print (banner % (
			ansiColor (reset = True, bright = True, foreground = "white"),
			ansiColor (reset = True, foreground = "magenta"),
			ansiColor (reset = True, bright = True, italic = True, foreground = "white"),
			ansiColor (reset = True, italic = True),
			ansiColor (reset = True, foreground = "magenta"),
			ansiColor (reset = True)
		))
	else:
		print (banner % ("", "", "", "", "", ""))

	if description is not None and len (description) > 0:
		print ("")
		print (textwrap.indent (textwrap.fill (description, width = 76), "    "))

	if urls is not None and len (urls) > 0:
		print ("")
		for url in urls.values ():
			print (" " * banner_indent + url)

	if repositories is not None and len (repositories) > 0:
		print ("")
		for repository in repositories.values ():
			print (" " * banner_indent + repository)

	if authors is not None and len (authors) > 0:
		print ("")
		print (" " * banner_indent + "Author(s):")
		for author in authors:
			print (" " * banner_indent * 2 + "%s <%s>" % (author ["name"], author ["email"]))

	if contributors is not None and len (contributors) > 0:
		print ("")
		print (" " * banner_indent + "Contributor(s):")
		for contributor in contributors:
			print (" " * banner_indent * 2 + "%s <%s>" % (contributor ["name"], contributor ["email"]))

# ==============================================================================

def hostProcess (
	path:str,
	args:list[str] = [],
	workdir:str = None,
	user:str = None,
	group:str = None,
	environment:dict = None,
	output:bool = True
) -> object:
	try:
		process = subprocess.Popen (
			[path] + args,
			stdout = subprocess.DEVNULL if not output else subprocess.PIPE,
			stderr = subprocess.STDOUT,
			close_fds = True,
			cwd = workdir,
			env = environment,
			user = user,
			group = group
		)
	except OSError as err:
		raise err
	except ValueError as err:
		raise err

	return process

def hostProcessPipe (service_name:str, service:dict):
	while True:
		line = service ["process"].stdout.readline ()
		line = str (line, "utf8")

		if line != "":
			while line [len (line) - 1:] == "\n":
				line = line [0:-1]
			message (service_name, line)
		else:
			return

# ==============================================================================

def execProcess (
	path:str,
	args:list[str] = [],
	workdir:str = None,
	user:str = None,
	group:str = None,
	environment:dict = None,
	output:bool = True
) -> int:
	try:
		process = subprocess.Popen (
			[path] + args,
			stdout = subprocess.DEVNULL if not output else subprocess.PIPE,
			stderr = subprocess.STDOUT,
			close_fds = True,
			cwd = workdir,
			env = environment,
			user = user,
			group = group
		)
	except OSError as err:
		raise err
	except ValueError as err:
		raise err

	while True:
		if (retcode := process.poll ()) is not None:
			return retcode
		line = process.stdout.readline ()
		line = str (line, "utf8")

		if line != "":
			while line [len (line) - 1:] == "\n":
				line = line [0:-1]
			wrapOutput (line)

	while True:
		if (retcode := process.poll ()) is not None:
			return retcode
		time.sleep (0.05)

# ------------------------------------------------------------------------------

def runTask (
	path:str,
	args:list[str] = [],
	workdir:str = None,
	user:str = None,
	group:str = None,
	environment:dict = None,
	output:bool = True
) -> object:
	try:
		process = subprocess.Popen (
			[path] + args,
			stdout = subprocess.DEVNULL if not output else subprocess.PIPE,
			stderr = subprocess.STDOUT,
			close_fds = True,
			cwd = workdir,
			env = environment,
			user = user,
			group = group
		)
	except OSError as err:
		raise err
	except ValueError as err:
		raise err

	return process

def runTaskPipe (periodic_name:str, periodic:dict):
	while True:
		line = periodic ["process"].stdout.readline ()
		line = str (line, "utf8")

		if line != "":
			while line [len (line) - 1:] == "\n":
				line = line [0:-1]
			message (periodic_name, line)
		else:
			return

# ------------------------------------------------------------------------------

def fillTemplate (task:dict, environment:dict = {}):
	def getReplacement (match:object) -> str:
		key = match.group (1).upper ()

		default = None
		for default_key, default_value in environment.items ():
			if key == default_key.upper ():
				default = default_value
				break

		if os.getenv (key) is None and default is None:
			raise KeyError ("Referenced environment variable has no value or default: %s" % (key,))
		elif os.getenv (key) is None and default is not None:
			return default
		elif os.getenv (key) is not None:
			return os.getenv (key)

	wrapOutput ("read %s" % (task ["source"],))
	with open (task ["source"], "r") as file:
		content = file.read ()
	wrapOutput ("   Read")

	content = re.sub (r"(?i)%%([a-z_]+)%%", getReplacement, content)

	wrapOutput ("write %s" % (task ["target"]["path"]))
	with open (task ["target"]["path"], "w") as file:
		file.write (content)
	wrapOutput ("   Written")

	if task ["target"]["owner"] is not None and task ["target"]["group"] is not None:
		wrapOutput ("chown %s:%s %s" % (task ["target"]["owner"], task ["target"]["group"], task ["target"]["path"]))
		uid = pwd.getpwnam (task ["target"]["owner"]).pw_uid
		gid = grp.getgrnam (task ["target"]["group"]).gr_gid
		os.chown (task ["target"]["path"], uid, gid)
		wrapOutput ("   Ownership set")

	if task ["target"]["permissions"] is not None:
		wrapOutput ("chmod %s %s" % (task ["target"]["permissions"], task ["target"]["path"]))
		_permissions = int (task ["target"]["permissions"], 8)
		os.chmod (task ["target"]["path"], _permissions)
		wrapOutput ("   Permissions set")

# ------------------------------------------------------------------------------

def ensureTree (tree:dict, path:str = ""):
	for entry_name, entry in tree.items ():
		wrapOutput ("mkdir %s%s " % (path, entry_name))
		try:
			os.mkdir ("%s%s" % (path, entry_name), mode = 0o0755)
			wrapOutput ("   Created")
		except FileExistsError as err:
			wrapOutput ("   Exists")

		if entry.get ("owner") is not None and entry.get ("group") is not None:
			wrapOutput ("chown %s:%s %s%s" % (entry ["owner"], entry ["group"], path, entry_name))
			uid = pwd.getpwnam (entry ["owner"]).pw_uid
			gid = grp.getgrnam (entry ["group"]).gr_gid
			os.chown ("%s%s" % (path, entry_name), uid, gid)
			wrapOutput ("   Ownership set")

		if entry.get ("permissions") is not None:
			wrapOutput ("chmod %s %s%s" % (entry ["permissions"], path, entry_name))
			_permissions = int (entry ["permissions"], 8)
			os.chmod ("%s%s" % (path, entry_name), _permissions)
			wrapOutput ("Permissions set")

		if entry.get ("tree") is not None and isinstance (entry ["tree"], dict):
			ensureTree (entry ["tree"], "%s%s/" % (path, entry_name))

# ==============================================================================

CONFIG = {}
SERVICES = {}
SERVICE_ORDER = []
PERIODICS = {}

# ==============================================================================

def serviceStart (service_name:str, service:dict):
	_service = {
		"process": hostProcess (
			path = service ["path"],
			args = service ["args"],
			workdir = service ["workdir"],
			user = service ["user"],
			group = service ["group"],
			#environment = service ["environment"],
			output = service ["output"]
		),
		"thread": None
	}
	_service ["thread"] = threading.Thread (
		target = hostProcessPipe,
		args = (
			service_name,
			_service
		)
	)
	_service ["thread"].start ()
	SERVICES [service_name] = _service

def serviceStop (service_name:str):
	_service = SERVICES [service_name]

	if _service ["process"].poll () is None:
		_service ["process"].send_signal (signal.SIGINT)
		time.sleep (1)
		if _service ["process"].poll () is None:
			_service ["process"].send_signal (signal.SIGINT)
			time.sleep (1)
			if _service ["process"].poll () is None:
				_service ["process"].send_signal (signal.SIGTERM)
				time.sleep (2)
				if _service ["process"].poll () is None:
					_service ["process"].send_signal (signal.SIGKILL)
					time.sleep (2)

	_service ["process"].wait ()
	_service ["thread"].join ()

	_service ["thread"] = None
	_service ["process"] = None

# ------------------------------------------------------------------------------

def periodicStart (periodic_name:str, periodic:dict):
	_periodic = {
		"process": runTask (
			path = periodic ["path"],
			args = periodic ["args"],
			workdir = periodic ["workdir"],
			user = periodic ["user"],
			group = periodic ["group"],
			#environment = periodic ["environment"],
			output = periodic ["output"]
		),
		"thread": None
	}
	_periodic ["thread"] = threading.Thread (
		target = runTaskPipe,
		args = (
			periodic_name,
			_periodic
		)
	)
	_periodic ["thread"].start ()

	PERIODICS [
		periodic_name +
		(str (time.time ()) if periodic ["allow-multiple"] else "")
	] = _periodic

def periodicStop (periodic_id:str):
	_periodic = PERIODICS [periodic_id]

	if _periodic ["process"].poll () is None:
		_periodic ["process"].send_signal (signal.SIGINT)
		time.sleep (1)
		if _periodic ["process"].poll () is None:
			_periodic ["process"].send_signal (signal.SIGINT)
			time.sleep (1)
			if _periodic ["process"].poll () is None:
				_periodic ["process"].send_signal (signal.SIGTERM)
				time.sleep (2)
				if _periodic ["process"].poll () is None:
					_periodic ["process"].send_signal (signal.SIGKILL)
					time.sleep (2)

	_periodic ["process"].wait ()
	_periodic ["thread"].join ()

	del (PERIODICS [periodic_id])

# ==============================================================================

def signalStop ():
	notice ("Shutting down")

	for service_name in reversed (SERVICE_ORDER):
		service = SERVICES [service_name]

		if service ["process"] is not None:
			notice ("Stopping service: %s" % (service_name))
			serviceStop (service_name)
			notice ("Service stopped: %s" % (service_name))

	for periodic_id, _periodic in PERIODICS.items ():
		if _periodic ["process"] is not None:
			notice ("Stopping periodic task: %s" % (periodic_id))
			periodicStop (periodic_id)
			notice ("Periodic task stopped: %s" % (periodic_id))

	os._exit (0)

def signalHandler (signal_number:int, frame):
	if signal_number in (signal.SIGINT, signal.SIGTERM, signal.SIGPIPE):
		signalStop ()

# ==============================================================================

def main ():
	signal.signal (signal.SIGINT, signalHandler)
	signal.signal (signal.SIGTERM, signalHandler)
	signal.signal (signal.SIGPIPE, signalHandler)

	try:
		with open (CONFIG_JSON, "r") as file:
			CONFIG = json.load (file)

		banner_print (
			title = CONFIG ["title"],
			subtitle = CONFIG ["subtitle"],
			description = CONFIG ["description"],
			repositories = CONFIG ["repositories"],
			authors = CONFIG ["authors"],
			contributors = CONFIG ["contributors"],
		)

		separator ()

		info ("Writing /env")
		with open ("env", "w") as file:
			for key, value in CONFIG ["environment"].items ():
				if key not in os.environ:
					file.write ("%s=\"%s\"\n" % (key, shlex.quote (value)))
			for key, value in os.environ.items ():
				if key in CONFIG ["environment"]:
					file.write ("%s=\"%s\"\n" % (key, shlex.quote (value)))
		wrapOutput ("   written")

		info ("Ensuring needed directory structure")
		ensureTree ({
			"var": {
				"tree": {
					"startup": {}
				}
			}
		})

		for _, task in enumerate (CONFIG ["startup"]):
			if task ["type"] == "exec":
				task_key = generateKey (task)

				if task ["every-start"] == False and os.path.exists ("%s/%s" % (STARTUP_STATE_PATH, task_key,)):
					notice ("Skipping startup task: %s" % (task ["description"],))
					continue

				notice ("Running startup task: %s" % (task ["description"],))
				retcode = execProcess (
					path = task ["path"],
					args = task ["args"],
					workdir = task ["workdir"],
					user = task ["user"],
					group = task ["group"],
					environment = None,
					output = task ["output"]
				)
				if retcode != 0:
					fatal ("Startup task %s failed with exit code %i" % (task ["description"], retcode))

				with open ("%s/%s" % (STARTUP_STATE_PATH, task_key,), "w") as file:
					file.write ("")

			elif task ["type"] == "template":
				task_key = generateKey (task)

				if task ["every-start"] == False and os.path.exists ("%s/%s" % (STARTUP_STATE_PATH, task_key,)):
					notice ("Skipping template: %s" % (task ["target"]["path"],))
					continue

				notice ("Filling in template: %s" % (task ["target"]["path"],))
				fillTemplate (task, CONFIG ["environment"])

				with open ("%s/%s" % (STARTUP_STATE_PATH, task_key,), "w") as file:
					file.write ("")

			elif task ["type"] == "tree":
				notice ("Creating directory tree: %s" % (task ["description"],))
				ensureTree (task ["tree"])

			else:
				fatal ("Unknown startup task type: %s" % (task ["type"]))

		separator ()

		while True:
			started = 0
			for service_name, service in CONFIG ["services"].items ():
				if (service.get ("needs") is None or len (service ["needs"]) == 0) and service_name not in SERVICES:
					# Start service
					started += 1
					notice ("Starting service: %s (%s)" % (service ["description"], service_name))
					SERVICE_ORDER.append (service_name)
					serviceStart (service_name, service)
					notice ("Service started: %s" % (service_name))

				elif service.get ("needs") is not None and len (service ["needs"]) > 0 and service_name not in SERVICES:
					for needs in service ["needs"]:
						if needs not in SERVICES:
							break
					else:
						# Start service
						started += 1
						notice ("Starting service: %s (%s)" % (service ["description"], service_name))
						SERVICE_ORDER.append (service_name)
						serviceStart (service_name, service)
						notice ("Service started: %s" % (service_name))

			if started == 0:
				break

		last_minute = int (time.time () / 60)
		while True:
			for service_name, _service in SERVICES.items ():
				service = CONFIG ["services"][service_name]

				if (retcode := _service ["process"].poll ()) is not None:
					warning ("Service unexpectedly stopped: %s" % (service_name))
					notice ("Stopping service: %s" % (service_name))
					serviceStop (service_name)
					notice ("Service stopped: %s" % (service_name))
					notice ("Starting service: %s (%s)" % (service ["description"], service_name))
					serviceStart (service_name, service)
					notice ("Service started: %s" % (service_name))

			periodic_keys = list (PERIODICS.keys ())
			for periodic_id in periodic_keys:
				_periodic = PERIODICS [periodic_id]

				if (retcode := _periodic ["process"].poll ()) is not None:
					notice ("Periodic task ended: %s" % (periodic_id))
					periodicStop (periodic_id)
					notice ("Periodic task tidied: %s" % (periodic_id))

			current_minute = int (time.time () / 60)
			if last_minute == current_minute:
				continue

			last_minute = current_minute
			for periodic_name, periodic in CONFIG ["periodic"].items ():
				if "timing" not in periodic or periodic ["timing"] == "":
					continue

				if croniter.match (periodic ["timing"], datetime.datetime.now ()) == True:
					if periodic_name in PERIODICS:
						warning ("Periodic still running: %s" % (periodic_name))
						continue

					notice ("Starting periodic: %s (%s)" % (periodic ["description"], periodic_name))
					periodicStart (periodic_name, periodic)
					notice ("Periodic started: %s" % (periodic_name))

			time.sleep (0.2)

	except Exception as err:
		error ("%s: %s" % (err.__class__.__name__, str (err)))
		raise err

# ==============================================================================

if __name__ == "__main__":
	main ()
