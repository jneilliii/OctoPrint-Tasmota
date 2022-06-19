# coding=utf-8
from __future__ import absolute_import

import octoprint.plugin
from octoprint.access.permissions import Permissions, ADMIN_GROUP
from octoprint.util import RepeatedTimer
from octoprint.events import Events
from flask_babel import gettext
import time
import logging
import os
import requests
import threading
import sqlite3
import flask
from octoprint.util.version import is_octoprint_compatible
from uptime import uptime
from datetime import datetime, timedelta

try:
	from octoprint.util import ResettableTimer
except ImportError:
	class ResettableTimer(threading.Thread):
		def __init__(self, interval, function, args=None, kwargs=None, on_reset=None, on_cancelled=None):
			threading.Thread.__init__(self)
			self._event = threading.Event()
			self._mutex = threading.Lock()
			self.is_reset = True

			if args is None:
				args = []
			if kwargs is None:
				kwargs = {}

			self.interval = interval
			self.function = function
			self.args = args
			self.kwargs = kwargs
			self.on_cancelled = on_cancelled
			self.on_reset = on_reset

		def run(self):
			while self.is_reset:
				with self._mutex:
					self.is_reset = False
				self._event.wait(self.interval)

			if not self._event.isSet():
				self.function(*self.args, **self.kwargs)
			with self._mutex:
				self._event.set()

		def cancel(self):
			with self._mutex:
				self._event.set()

			if callable(self.on_cancelled):
				self.on_cancelled()

		def reset(self, interval=None):
			with self._mutex:
				if interval:
					self.interval = interval

				self.is_reset = True
				self._event.set()
				self._event.clear()

			if callable(self.on_reset):
				self.on_reset()


class tasmotaPlugin(octoprint.plugin.SettingsPlugin,
					octoprint.plugin.AssetPlugin,
					octoprint.plugin.TemplatePlugin,
					octoprint.plugin.SimpleApiPlugin,
					octoprint.plugin.StartupPlugin,
					octoprint.plugin.ProgressPlugin,
					octoprint.plugin.EventHandlerPlugin):

	def __init__(self):
		self.print_job_power = 0.0
		self._logger = logging.getLogger("octoprint.plugins.tasmota")
		self._tasmota_logger = logging.getLogger("octoprint.plugins.tasmota.debug")
		self.thermal_runaway_triggered = False
		self.poll_status = None
		self.abortTimeout = 0
		self._timeout_value = None
		self._abort_timer = None
		self._countdown_active = False
		self._waitForHeaters = False
		self._waitForTimelapse = False
		self._timelapse_active = False
		self._skipIdleTimer = False
		self.powerOffWhenIdle = False
		self._idleTimer = None
		self._autostart_file = None
		self.print_job_started = False
		self._storage_interface = None

	##~~ StartupPlugin mixin

	def on_startup(self, host, port):
		# setup customized logger
		from octoprint.logging.handlers import CleaningTimedRotatingFileHandler
		tasmota_logging_handler = CleaningTimedRotatingFileHandler(
			self._settings.get_plugin_logfile_path(postfix="debug"), when="D", backupCount=3)
		tasmota_logging_handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s"))
		tasmota_logging_handler.setLevel(logging.DEBUG)

		self._tasmota_logger.addHandler(tasmota_logging_handler)
		self._tasmota_logger.setLevel(logging.DEBUG if self._settings.get_boolean(["debug_logging"]) else logging.INFO)
		self._tasmota_logger.propagate = False

		self.energy_db_path = os.path.join(self.get_plugin_data_folder(), "energy_data.db")
		if not os.path.exists(self.energy_db_path):
			db = sqlite3.connect(self.energy_db_path)
			cursor = db.cursor()
			cursor.execute(
				'''CREATE TABLE energy_data(id INTEGER PRIMARY KEY, ip TEXT, idx TEXT, timestamp TEXT, current REAL, power REAL, total REAL, voltage REAL)''')
			db.commit()
			db.close()

		self.sensor_db_path = os.path.join(self.get_plugin_data_folder(), "sensor_data.db")
		if not os.path.exists(self.sensor_db_path):
			db = sqlite3.connect(self.sensor_db_path)
			cursor = db.cursor()
			cursor.execute(
				'''CREATE TABLE sensor_data(id INTEGER PRIMARY KEY, ip TEXT, idx TEXT, timestamp TEXT, temperature REAL, humidity REAL)''')
			db.commit()
			db.close()

		self.abortTimeout = self._settings.get_int(["abortTimeout"])
		self._tasmota_logger.debug("abortTimeout: %s" % self.abortTimeout)

		self.powerOffWhenIdle = self._settings.get_boolean(["powerOffWhenIdle"])
		self._tasmota_logger.debug("powerOffWhenIdle: %s" % self.powerOffWhenIdle)

		self.idleTimeout = self._settings.get_int(["idleTimeout"])
		self._tasmota_logger.debug("idleTimeout: %s" % self.idleTimeout)
		self.idleIgnoreCommands = self._settings.get(["idleIgnoreCommands"])
		self._idleIgnoreCommandsArray = self.idleIgnoreCommands.split(',')
		self._tasmota_logger.debug("idleIgnoreCommands: %s" % self.idleIgnoreCommands)
		self.idleTimeoutWaitTemp = self._settings.get_int(["idleTimeoutWaitTemp"])
		self._tasmota_logger.debug("idleTimeoutWaitTemp: %s" % self.idleTimeoutWaitTemp)

		self._start_idle_timer()

	def on_after_startup(self):
		self._logger.info("Tasmota loaded!")
		if self._settings.get_boolean(["polling_enabled"]) and self._settings.get_int(["polling_interval"]) > 0:
			self.poll_status = RepeatedTimer(float(self._settings.get_float(["polling_interval"])) * 60,
											 self.check_statuses)
			self.poll_status.start()

	##~~ SettingsPlugin mixin

	def get_settings_defaults(self):
		return {
			"debug_logging": False,
			"polling_enabled": False,
			"polling_interval": 5,
			"thermal_runaway_monitoring": False,
			"thermal_runaway_max_bed": 120,
			"thermal_runaway_max_extruder": 300,
			"event_on_error_monitoring": False,
			"event_on_disconnect_monitoring": False,
			"event_on_connecting_monitoring": False,
			"arrSmartplugs": [],
			"abortTimeout": 30,
			"powerOffWhenIdle": False,
			"idleTimeout": 30,
			"idleIgnoreCommands": 'M105',
			"idleTimeoutWaitTemp": 50,
			"idleWaitForTimelapse": True,
			"event_on_upload_monitoring": False,
			"event_on_upload_monitoring_always": False,
			"event_on_upload_monitoring_start_print": False,
			"cost_rate": 0,
			"request_timeout": 3
		}

	def on_settings_save(self, data):
		old_debug_logging = self._settings.get_boolean(["debug_logging"])
		old_polling_value = self._settings.get_boolean(["pollingEnabled"])
		old_polling_timer = self._settings.get(["pollingInterval"])
		old_powerOffWhenIdle = self._settings.get_boolean(["powerOffWhenIdle"])
		old_idleTimeout = self._settings.get_int(["idleTimeout"])
		old_idleIgnoreCommands = self._settings.get(["idleIgnoreCommands"])
		old_idleTimeoutWaitTemp = self._settings.get_int(["idleTimeoutWaitTemp"])

		octoprint.plugin.SettingsPlugin.on_settings_save(self, data)

		self.abortTimeout = self._settings.get_int(["abortTimeout"])
		self.powerOffWhenIdle = self._settings.get_boolean(["powerOffWhenIdle"])

		self.idleTimeout = self._settings.get_int(["idleTimeout"])
		self.idleIgnoreCommands = self._settings.get(["idleIgnoreCommands"])
		self._idleIgnoreCommandsArray = self.idleIgnoreCommands.split(',')
		self.idleTimeoutWaitTemp = self._settings.get_int(["idleTimeoutWaitTemp"])

		if self.powerOffWhenIdle != old_powerOffWhenIdle:
			self._plugin_manager.send_plugin_message(self._identifier,
													 {'powerOffWhenIdle': self.powerOffWhenIdle, 'type': "timeout",
													  'timeout_value': self._timeout_value})

		if self.powerOffWhenIdle == True:
			self._tasmota_logger.debug("Settings saved, Automatic Power Off Enabled, starting idle timer...")
			self._start_idle_timer()
		else:
			self._tasmota_logger.debug("Settings saved, Automatic Power Off Disabled, stopping idle timer...")
			self._stop_idle_timer()

		new_debug_logging = self._settings.get_boolean(["debug_logging"])
		new_polling_value = self._settings.get_boolean(["pollingEnabled"])
		new_polling_timer = self._settings.get(["pollingInterval"])

		if old_debug_logging != new_debug_logging:
			if new_debug_logging:
				self._tasmota_logger.setLevel(logging.DEBUG)
			else:
				self._tasmota_logger.setLevel(logging.INFO)

		if (new_polling_value and not old_polling_value) or old_polling_timer != new_polling_timer:
			if self.poll_status:
				self.poll_status.cancel()

			if new_polling_value:
				self.poll_status = RepeatedTimer(self._settings.get_float(["pollingInterval"]) * 60, self.check_statuses)
				self.poll_status.start()

	def get_settings_version(self):
		return 12

	def on_settings_migrate(self, target, current=None):
		if current is None or current < 6:
			# Reset plug settings to defaults.
			self._logger.debug("Resetting arrSmartplugs for tasmota settings.")
			self._settings.set(['arrSmartplugs'], self.get_settings_defaults()["arrSmartplugs"])
		if current == 6:
			# Add new fields
			arrSmartplugs_new = []
			for plug in self._settings.get(['arrSmartplugs']):
				plug["automaticShutdownEnabled"] = False
				arrSmartplugs_new.append(plug)
			self._settings.set(["arrSmartplugs"], arrSmartplugs_new)
		if current == 7 or current == 6:
			# Add new fields
			arrSmartplugs_new = []
			for plug in self._settings.get(['arrSmartplugs']):
				plug["event_on_error"] = False
				plug["event_on_disconnect"] = False
				arrSmartplugs_new.append(plug)
			self._settings.set(["arrSmartplugs"], arrSmartplugs_new)
		if current < 9:
			# Add new fields
			arrSmartplugs_new = []
			for plug in self._settings.get(['arrSmartplugs']):
				plug["event_on_upload"] = False
				arrSmartplugs_new.append(plug)
			self._settings.set(["arrSmartplugs"], arrSmartplugs_new)
		if current < 10:
			# Add new fields
			arrSmartplugs_new = []
			for plug in self._settings.get(['arrSmartplugs']):
				plug["event_on_connecting"] = False
				arrSmartplugs_new.append(plug)
			self._settings.set(["arrSmartplugs"], arrSmartplugs_new)
		if current < 11:
			# Add new fields
			arrSmartplugs_new = []
			for plug in self._settings.get(['arrSmartplugs']):
				plug["is_led"] = False
				plug["brightness"] = 50
				arrSmartplugs_new.append(plug)
			self._settings.set(["arrSmartplugs"], arrSmartplugs_new)
		if current < 12:
			# Add new fields
			arrSmartplugs_new = []
			for plug in self._settings.get(['arrSmartplugs']):
				plug["is_sensor_only"] = False
				arrSmartplugs_new.append(plug)
			self._settings.set(["arrSmartplugs"], arrSmartplugs_new)

	##~~ AssetPlugin mixin

	def get_assets(self):
		css = ["css/fontawesome-iconpicker.css",
			   "css/tasmota.css",
			   ]

		if not is_octoprint_compatible(">=1.5.0"):
			css += [
				"css/font-awesome.min.css",
				"css/font-awesome-v4-shims.min.css",
			]

		return {'js': ["js/jquery-ui.min.js", "js/knockout-sortable.1.2.0.js", "js/fontawesome-iconpicker.js",
					   "js/ko.iconpicker.js", "js/plotly-latest.min.js", "js/knockout-bootstrap.min.js",
					   "js/ko.observableDictionary.js", "js/tasmota.js"],
				'css': css}

	##~~ TemplatePlugin mixin

	def get_template_configs(self):
		return [
			{'type': "navbar", 'custom_bindings': True},
			{'type': "settings", 'custom_bindings': True},
			{'type': "tab", 'custom_bindings': True},
			{'type': "sidebar", 'icon': "plug", 'custom_bindings': True, 'data_bind': "visible: show_sidebar",
			 'template': "tasmota_sidebar.jinja2", 'template_header': "tasmota_sidebar_header.jinja2"}
		]

	##~~ ProgressPlugin mixin

	def on_print_progress(self, storage, path, progress):
		if self.powerOffWhenIdle == True and not (self._skipIdleTimer == True):
			self._tasmota_logger.debug("Resetting idle timer during print progress (%s)..." % progress)
			self._waitForHeaters = False
			self._reset_idle_timer()

	##~~ EventHandlerPlugin mixin

	def on_event(self, event, payload):
		# Error Event
		if event == Events.ERROR and self._settings.get_boolean(["event_on_error_monitoring"]):
			self._tasmota_logger.debug("powering off due to %s event." % event)
			for plug in self._settings.get(['arrSmartplugs']):
				if plug["event_on_error"] == True:
					self._tasmota_logger.debug("powering off %s:%s due to %s event." % (plug["ip"], plug["idx"], event))
					self.turn_off(plug["ip"], plug["idx"])

		if event == Events.CONNECTING and self._settings.get_boolean(
				["event_on_connecting_monitoring"]) and self._printer.is_closed_or_error:
			self._tasmota_logger.debug("powering on due to %s event." % event)
			for plug in self._settings.get(['arrSmartplugs']):
				if plug["event_on_connecting"] == True:
					self._tasmota_logger.debug("powering on %s:%s due to %s event." % (plug["ip"], plug["idx"], event))
					self.turn_on(plug["ip"], plug["idx"])

		# Disconnected Event
		if event == Events.DISCONNECTED and self._settings.get_boolean(["event_on_disconnect_monitoring"]):
			self._tasmota_logger.debug("powering off due to %s event." % event)
			for plug in self._settings.get(['arrSmartplugs']):
				if plug["event_on_disconnect"] == True:
					self._tasmota_logger.debug("powering off %s:%s due to %s event." % (plug["ip"], plug["idx"], event))
					self.turn_off(plug["ip"], plug["idx"])

		# Client Opened Event
		if event == Events.CLIENT_OPENED:
			self._plugin_manager.send_plugin_message(self._identifier,
													 {'powerOffWhenIdle': self.powerOffWhenIdle, 'type': "timeout",
													  'timeout_value': self._timeout_value})
			return

		# Printer Connected Event
		if event == Events.CONNECTED:
			if self.thermal_runaway_triggered:
				self._plugin_manager.send_plugin_message(self._identifier,
														 {'thermal_runaway': True, 'type': "connection"})
				self._tasmota_logger.debug("thermal runaway event triggered prior to last connection.")
				self.thermal_runaway_triggered = False
			if self._autostart_file:
				self._tasmota_logger.debug("printer connected starting print of %s" % self._autostart_file)
				self._printer.select_file(self._autostart_file, False, printAfterSelect=True)
				self._autostart_file = None

		# File Uploaded Event
		if event == Events.UPLOAD and self._settings.get_boolean(["event_on_upload_monitoring"]):
			if payload.get("print", False) or self._settings.get_boolean(
					["event_on_upload_monitoring_always"]):  # implemented in OctoPrint version 1.4.1
				self._tasmota_logger.debug("File uploaded: %s. Turning enabled plugs on." % payload.get("name", ""))
				self._tasmota_logger.debug("Clearing autostart.")
				self._autostart_file = None
				self._tasmota_logger.debug(payload)
				for plug in self._settings.get(['arrSmartplugs']):
					self._tasmota_logger.debug(plug)
					if plug["event_on_upload"] is True:
						self._tasmota_logger.debug("powering on %s due to %s event." % (plug["ip"], event))
						self.turn_on(plug["ip"], plug["idx"])
						response = self.check_status(plug["ip"], plug["idx"])
						if response["currentState"] == "on":
							self._tasmota_logger.debug(
								"power on successful for %s attempting connection in %s seconds" % (
									plug["ip"], plug.get("autoConnectDelay", "0")))
							if payload.get("path", False) and payload.get("target") == "local" and (
									payload.get("print", False) or self._settings.get_boolean(
								["event_on_upload_monitoring_start_print"])):
								if self._printer.is_ready():
									self._printer.select_file(payload.get("path"), False, printAfterSelect=True)
								else:
									self._autostart_file = payload.get("path")

		# Print Started Event
		if event == Events.PRINT_STARTED and self._settings.getFloat(["cost_rate"]) > 0:
			self.print_job_started = True
			self._tasmota_logger.debug(payload.get("path", None))
			if self.thermal_runaway_triggered:
				self._plugin_manager.send_plugin_message(self._identifier,
														 {'thermal_runaway': True, 'type': "connection"})
				self._tasmota_logger.debug("thermal runaway event triggered prior to last connection.")
				self.thermal_runaway_triggered = False
			for plug in self._settings.get(["arrSmartplugs"]):
				status = self.check_status(plug["ip"], plug["idx"])
				self.print_job_power -= float(self.deep_get(status, ["energy_data", "Total"], default=0))
				self._tasmota_logger.debug(self.print_job_power)

		if event == Events.PRINT_STARTED:
			self._autostart_file = None

		if event == Events.PRINT_STARTED and self.powerOffWhenIdle:
			if self._abort_timer is not None:
				self._abort_timer.cancel()
				self._abort_timer = None
				self._tasmota_logger.debug("Power off aborted because starting new print.")
			if self._idleTimer is not None:
				self._reset_idle_timer()
			self._timeout_value = None
			self._plugin_manager.send_plugin_message(self._identifier,
													 {'powerOffWhenIdle': self.powerOffWhenIdle, 'type': "timeout",
													  'timeout_value': self._timeout_value})

		# Print Cancelled/Done Events
		if event == Events.PRINT_DONE and self.print_job_started:
			self._tasmota_logger.debug(payload)

			for plug in self._settings.get(["arrSmartplugs"]):
				status = self.check_status(plug["ip"], plug["idx"])
				self.print_job_power += float(self.deep_get(status, ["energy_data", "Total"], default=0))
				self._tasmota_logger.debug(self.print_job_power)

			hours = (payload.get("time", 0) / 60) / 60
			self._tasmota_logger.debug("hours: %s" % hours)
			power_used = self.print_job_power * hours
			self._tasmota_logger.debug("power used: %s" % power_used)
			power_cost = power_used * self._settings.getFloat(["cost_rate"])
			self._tasmota_logger.debug("power total cost: %s" % power_cost)

			self._storage_interface = self._file_manager._storage(payload.get("origin", "local"))
			self._storage_interface.set_additional_metadata(payload.get("path"), "statistics", {
				'lastPowerCost': {'_default': float('{:.4f}'.format(power_cost))}}, merge=True)

			self._autostart_file = None
			self.print_job_power = 0.0
			self.print_job_started = False

		if event == Events.PRINT_CANCELLED:
			self._autostart_file = None
			self.print_job_power = 0.0
			self.print_job_started = False

		# Timelapse events
		if self.powerOffWhenIdle == True and event == Events.MOVIE_RENDERING:
			self._tasmota_logger.debug("Timelapse generation started: %s" % payload.get("movie_basename", ""))
			self._timelapse_active = True
		if self._timelapse_active and event == Events.MOVIE_DONE or event == Events.MOVIE_FAILED:
			self._tasmota_logger.debug("Timelapse generation finished: %s. Return Code: %s" % (
				payload.get("movie_basename", ""), payload.get("returncode", "completed")))
			self._timelapse_active = False

	##~~ SimpleApiPlugin mixin

	def turn_on(self, plugip, plugidx):
		self._tasmota_logger.debug("Turning on %s index %s." % (plugip, plugidx))
		plug = self.plug_search(self._settings.get(["arrSmartplugs"]), "ip", plugip, "idx", plugidx)
		try:
			if plug["use_backlog"] and int(plug["backlog_on_delay"]) > 0:
				backlog_command = "backlog delay {};Power{} on;".format(int(plug["backlog_on_delay"]) * 10, plug["idx"])
				requests.get("http://{}/cm".format(plugip),
							 params={"user": plug["username"], "password": plug["password"], "cmnd": backlog_command},
							 timeout=self._settings.get_int(["request_timeout"]))
				response = {}
				response["POWER%s" % plug["idx"]] = "ON"
			else:
				webresponse = requests.get("http://{}/cm".format(plugip),
										   params={"user": plug["username"], "password": plug["password"],
												   "cmnd": "Power{} on".format(plug["idx"])},
										   timeout=self._settings.get_int(["request_timeout"]))
				response = webresponse.json()
			chk = response["POWER%s" % plug["idx"]]
		except:
			self._tasmota_logger.error('Invalid ip or unknown error connecting to %s.' % plug["ip"], exc_info=True)
			response = "Unknown error turning on %s index %s." % (plugip, plugidx)
			chk = "UNKNOWN"

		self._tasmota_logger.debug("Response: %s" % response)

		if chk.upper() in ["ON", "1"]:
			if plug["autoConnect"] and self._printer.is_closed_or_error():
				self._logger.info(self._settings.global_get(['serial']))
				c = threading.Timer(int(plug["autoConnectDelay"]), self._printer.connect,
									kwargs={'port': self._settings.global_get(['serial', 'port']),
											'baudrate': self._settings.global_get(['serial', 'baudrate'])})
				c.daemon = True
				c.start()
			if plug["sysCmdOn"]:
				t = threading.Timer(int(plug["sysCmdOnDelay"]), os.system, args=[plug["sysRunCmdOn"]])
				t.daemon = True
				t.start()
			if self.powerOffWhenIdle == True and plug["automaticShutdownEnabled"] == True:
				self._tasmota_logger.debug(
					"Resetting idle timer since plug %s:%s was just turned on." % (plugip, plugidx))
				self._waitForHeaters = False
				self._reset_idle_timer()
			self._plugin_manager.send_plugin_message(self._identifier,
													 {'currentState': "on", 'ip': plugip, 'idx': plugidx})

	def turn_off(self, plugip, plugidx):
		plug = self.plug_search(self._settings.get(["arrSmartplugs"]), "ip", plugip, "idx", plugidx)
		self._tasmota_logger.debug("Turning off %s " % plug)
		try:
			if plug["use_backlog"] and int(plug["backlog_off_delay"]) > 0:
				self._tasmota_logger.debug(
					"Using backlog commands with a delay value of %s" % str(int(plug["backlog_off_delay"]) * 10))
				backlog_command = "backlog delay {};Power{} off;".format(int(plug["backlog_off_delay"]) * 10,
																		 plug["idx"])
				requests.get("http://{}/cm".format(plugip),
							 params={"user": plug["username"], "password": plug["password"], "cmnd": backlog_command},
							 timeout=self._settings.get_int(["request_timeout"]))
				response = {}
				response["POWER%s" % plug["idx"]] = "OFF"
			if plug["sysCmdOff"]:
				self._tasmota_logger.debug(
					"Running system command: %s in %s" % (plug["sysRunCmdOff"], plug["sysCmdOffDelay"]))
				t = threading.Timer(int(plug["sysCmdOffDelay"]), os.system, args=[plug["sysRunCmdOff"]])
				t.daemon = True
				t.start()
			if plug["autoDisconnect"] and self._printer.is_operational():
				self._tasmota_logger.debug("Disconnnecting from printer")
				self._printer.disconnect()
				time.sleep(int(plug["autoDisconnectDelay"]))
			if not plug["use_backlog"]:
				self._tasmota_logger.debug("Not using backlog commands")
				webresponse = requests.get("http://{}/cm".format(plugip),
										   params={"user": plug["username"], "password": plug["password"],
												   "cmnd": "Power{} off".format(plug["idx"])},
										   timeout=self._settings.get_int(["request_timeout"]))
				response = webresponse.json()
			chk = response["POWER%s" % plug["idx"]]
			if chk.upper() in ["OFF", "0"]:
				self._plugin_manager.send_plugin_message(self._identifier,
														 {'currentState': "off", 'ip': plugip, 'idx': plugidx})
		except:
			self._tasmota_logger.error('Invalid ip or unknown error connecting to %s.' % plug["ip"], exc_info=True)
			response = "Unknown error turning off %s index %s." % (plugip, plugidx)

		self._tasmota_logger.debug(response)

	def check_statuses(self):
		for plug in self._settings.get(["arrSmartplugs"]):
			self._plugin_manager.send_plugin_message(self._identifier, self.check_status(plug["ip"], plug["idx"]))

	def check_status(self, plugip, plugidx):
		self._tasmota_logger.debug("Checking status of %s index %s." % (plugip, plugidx))
		if plugip != "":
			try:
				plug = self.plug_search(self._settings.get(["arrSmartplugs"]), "ip", plugip, "idx", plugidx)
				self._tasmota_logger.debug(plug)
				webresponse = requests.get("http://{}/cm".format(plugip),
										   params={"user": plug["username"], "password": plug["password"],
												   "cmnd": "Status 0"},
										   timeout=self._settings.get_int(["request_timeout"]))
				self._tasmota_logger.debug("check status code: {}".format(webresponse.status_code))
				self._tasmota_logger.debug("check status text: {}".format(webresponse.text))
				response = webresponse.json()
				self._tasmota_logger.debug("%s index %s response: %s" % (plugip, plugidx, response))
				# chk = response["POWER%s" % plugidx]
				chk = self.lookup(response, *["StatusSTS", "POWER" + plugidx])
				if chk is None:
					chk = "UNKNOWN"
				energy_data = self.lookup(response, *["StatusSNS", "ENERGY"])
				if energy_data is not None:
					today = datetime.today()
					c = self.lookup(response, *["StatusSNS", "ENERGY", "Current"])
					if isinstance(c, list):
						c = c[int(plugidx) - 1]
					p = self.lookup(response, *["StatusSNS", "ENERGY", "Power"])
					if isinstance(p, list):
						p = p[int(plugidx) - 1]
					t = self.lookup(response, *["StatusSNS", "ENERGY", "Total"])
					if isinstance(t, list):
						t = t[int(plugidx) - 1]
					v = self.lookup(response, *["StatusSNS", "ENERGY", "Voltage"])
					if isinstance(v, list):
						v = v[int(plugidx) - 1]
					self._tasmota_logger.debug("Energy Data: %s" % energy_data)
					self._logger.debug("Inserting data: {} : {}".format(
						["ip", "idx", "timestamp", "current", "power", "total", "voltage"],
						[plugip, plugidx, today.isoformat(' '), c, p, t, v]))
					db = sqlite3.connect(self.energy_db_path)
					cursor = db.cursor()
					cursor.execute(
						'''INSERT INTO energy_data(ip, idx, timestamp, current, power, total, voltage) VALUES(?,?,?,?,?,?,?)''',
						[plugip, plugidx, today.isoformat(' '), c, p, t, v])
					db.commit()
					db.close()
				if plug["sensor_identifier"] != "":
					sensor_data = self.lookup(response, *["StatusSNS", plug["sensor_identifier"]])
					if sensor_data is not None:
						today = datetime.today()
						t = self.lookup(response, *["StatusSNS", plug["sensor_identifier"], "Temperature"])
						h = self.lookup(response, *["StatusSNS", plug["sensor_identifier"], "Humidity"])
						self._tasmota_logger.debug("Sensor Data: %s" % sensor_data)
						db = sqlite3.connect(self.sensor_db_path)
						cursor = db.cursor()
						cursor.execute(
							'''INSERT INTO sensor_data(ip, idx, timestamp, temperature, humidity) VALUES(?,?,?,?,?)''',
							[plugip, plugidx, today.isoformat(' '), t, h])
						db.commit()
						db.close()
				else:
					sensor_data = None
			except:
				self._tasmota_logger.error('Invalid ip or unknown error connecting to %s.' % plugip, exc_info=True)
				response = "unknown error with %s." % plugip
				chk = "UNKNOWN"
				energy_data = None
				sensor_data = None

			self._tasmota_logger.debug("%s index %s is %s" % (plugip, plugidx, chk))
			if chk.upper() in ["ON", "1"]:
				response = {"currentState": "on", "ip": plugip, "idx": plugidx, "energy_data": energy_data,
							"sensor_data": sensor_data}
				if self._settings.get_boolean(["powerOffWhenIdle"]) and plug[
					"automaticShutdownEnabled"] and self._abort_timer is None and (
						self._idleTimer is None or not self._idleTimer.is_alive()):
					self._tasmota_logger.debug(
						"Starting idle timer since ON state was detected for %s:%s" % (plugip, plugidx))
					self._reset_idle_timer()
			elif chk.upper() in ["OFF", "0"]:
				response = {"currentState": "off", "ip": plugip, "idx": plugidx, "energy_data": energy_data,
							"sensor_data": sensor_data}
			else:
				self._tasmota_logger.debug(response)
				response = {"currentState": "unknown", "ip": plugip, "idx": plugidx, "energy_data": energy_data,
							"sensor_data": sensor_data}

			self._plugin_manager.send_plugin_message(self._identifier, response)
			return response

	def checkSetOption26(self, plugip, username, password):
		webresponse = requests.get("http://{}/cm".format(plugip),
								   params={"user": username, "password": password, "cmnd": "SetOption26"},
								   timeout=self._settings.get_int(["request_timeout"]))
		response = webresponse.json()
		self._tasmota_logger.debug(response)
		return response

	def setSetOption26(self, plugip, username, password):
		webresponse = requests.get("http://{}/cm".format(plugip),
								   params={"user": username, "password": password, "cmnd": "SetOption26 ON"},
								   timeout=self._settings.get_int(["request_timeout"]))
		response = webresponse.json()
		self._tasmota_logger.debug(response)
		return response

	def get_api_commands(self):
		return {'turnOn': ["ip", "idx"], 'turnOff': ["ip", "idx"], 'checkStatus': ["ip", "idx"], 'getEnergyData': [],
				'checkSetOption26': ["ip", "username", "password"], 'setSetOption26': ["ip", "username", "password"],
				'enableAutomaticShutdown': [], 'disableAutomaticShutdown': [], 'abortAutomaticShutdown': []}

	def on_api_command(self, command, data):
		self._tasmota_logger.debug(data)
		if not Permissions.PLUGIN_TASMOTA_CONTROL.can():
			return flask.make_response("Insufficient rights", 403)

		if command == 'turnOn':
			self.turn_on("{ip}".format(**data), "{idx}".format(**data))
		# return flask.jsonify(self.check_status("{ip}".format(**data), "{idx}".format(**data)))
		elif command == 'turnOff':
			self.turn_off("{ip}".format(**data), "{idx}".format(**data))
		# return flask.jsonify(self.check_status("{ip}".format(**data), "{idx}".format(**data)))

		elif command == 'checkStatus':
			return flask.jsonify(self.check_status("{ip}".format(**data), "{idx}".format(**data)))
		elif command == 'checkSetOption26':
			response = self.checkSetOption26("{ip}".format(**data), "{username}".format(**data),
											 "{password}".format(**data))
			return flask.jsonify(response)
		elif command == 'setSetOption26':
			response = self.setSetOption26("{ip}".format(**data), "{username}".format(**data),
										   "{password}".format(**data))
			return flask.jsonify(response)
		elif command == 'enableAutomaticShutdown':
			self.powerOffWhenIdle = True
		elif command == 'disableAutomaticShutdown':
			self.powerOffWhenIdle = False
		elif command == 'abortAutomaticShutdown':
			if self._abort_timer is not None:
				self._abort_timer.cancel()
				self._abort_timer = None
			self._timeout_value = None
			for plug in self._settings.get(["arrSmartplugs"]):
				if plug["use_backlog"] and int(plug["backlog_off_delay"]) > 0:
					webresponse = requests.get("http://{}/cm".format(plug["ip"]),
											   params={"user": plug["username"], "password": plug["password"],
													   "cmnd": "backlog"},
											   timeout=self._settings.get_int(["request_timeout"]))
					self._tasmota_logger.debug("Cleared countdown rules for %s" % plug["ip"])
					self._tasmota_logger.debug(webresponse)
			self._tasmota_logger.debug("Power off aborted.")
			self._tasmota_logger.debug("Restarting idle timer.")
			self._reset_idle_timer()
		elif command == 'getEnergyData':
			self._logger.info(data)
			response = {}
			if "start_date" in data and data["start_date"] != "":
				start_date = data["start_date"]
			else:
				start_date = datetime.date.today() - timedelta(days=1)
			if "end_date" in data and data["end_date"] != "":
				end_date = data["end_date"]
			else:
				end_date = datetime.date.today() + timedelta(days=1)
			energy_db = sqlite3.connect(self.energy_db_path)
			energy_cursor = energy_db.cursor()
			energy_cursor.execute(
				'''SELECT ip || ':' || idx AS ip, group_concat(timestamp) as timestamp, group_concat(current) as current, group_concat(power) as power, group_concat(total) as total FROM energy_data WHERE timestamp BETWEEN ? AND ? GROUP BY ip, idx''',
				[start_date, end_date])
			response["energy_data"] = energy_cursor.fetchall()
			energy_db.close()

			sensor_db = sqlite3.connect(self.sensor_db_path)
			sensor_cursor = sensor_db.cursor()
			sensor_cursor.execute(
				'''SELECT ip || ':' || idx AS ip, group_concat(timestamp) as timestamp, group_concat(temperature) as temperature, group_concat(humidity) as humidity FROM sensor_data WHERE timestamp BETWEEN ? AND ? GROUP BY ip, idx''',
				[start_date, end_date])
			response["sensor_data"] = sensor_cursor.fetchall()
			sensor_db.close()

			return flask.jsonify(response)
		if command == "enableAutomaticShutdown" or command == "disableAutomaticShutdown":
			self._tasmota_logger.debug("Automatic power off setting changed: %s" % self.powerOffWhenIdle)
			self._settings.set_boolean(["powerOffWhenIdle"], self.powerOffWhenIdle)
			self._settings.save()
		# eventManager().fire(Events.SETTINGS_UPDATED)
		if command == "enableAutomaticShutdown" or command == "disableAutomaticShutdown" or command == "abortAutomaticShutdown":
			self._plugin_manager.send_plugin_message(self._identifier,
													 {'powerOffWhenIdle': self.powerOffWhenIdle, 'type': "timeout",
													  'timeout_value': self._timeout_value})

	##~~ Gcode processing hook

	def gcode_off(self, plug):
		self._tasmota_logger.debug("Sending gcode off")
		if plug["warnPrinting"] and self._printer.is_printing():
			self._tasmota_logger.info("Not powering off %s because printer is printing." % plug["label"])
		else:
			self._tasmota_logger.debug("Sending turn off for %s index %s" % (plug["ip"], plug["idx"]))
			self.turn_off(plug["ip"], plug["idx"])

	def gcode_on(self, plug):
		self.turn_on(plug["ip"], plug["idx"])

	def gcode_led(self, plugip, led_data):
		self._tasmota_logger.debug("Received LED Command for {} with parameters {}".format(plugip, led_data))
		for plug in self._settings.get(["arrSmartplugs"]):
			if plug["is_led"]:
				if led_data["LEDBrightness"] == -1:
					led_data["LEDBrightness"] = plug["brightness"]
				try:
					requests.get("http://{}/cm".format(plugip),
								 params={"user": plug["username"], "password": plug["password"],
										 "cmnd": "backlog dimmer {}; color2 {},{},{}; white {}; power{} on".format(
											 led_data["LEDBrightness"], led_data["LEDRed"], led_data["LEDGreen"],
											 led_data["LEDBlue"], led_data["LEDWhite"], plug["idx"])},
								 timeout=self._settings.get_int(["request_timeout"]))
					self._plugin_manager.send_plugin_message(self._identifier,
															 {'currentState': "on", 'ip': plug["ip"],
															  'idx': plug["idx"], 'color': led_data})
				except Exception as e:
					self._logger.debug("Error: {}".format(e))

	def process_echo(self, comm, line, *args, **kwargs):
		if not line.startswith("TASMOTA_M150"):
			return line

		plugip = None
		workleds = {'LEDRed': 0, 'LEDBlue': 0, 'LEDGreen': 0, 'LEDWhite': 0, 'LEDBrightness': -1}
		workval = line.upper().split()
		for i in workval:
			firstchar = str(i[0].upper())
			leddata = str(i[1:].strip())
			if not leddata.isdigit() and firstchar not in ["I", "T"]:
				self._tasmota_logger.debug(leddata)
				return line

			if firstchar == 'T':
				continue
			elif firstchar == "I":
				plugip = leddata
			elif firstchar == 'R':
				workleds['LEDRed'] = int(leddata)
			elif firstchar == 'G' or firstchar == 'U':
				workleds['LEDGreen'] = int(leddata)
			elif firstchar == 'B':
				workleds['LEDBlue'] = int(leddata)
			elif firstchar == "W":
				workleds['LEDWhite'] = int(float(leddata) / 255 * 100)
			elif firstchar == "P":
				workleds['LEDBrightness'] = int(float(leddata) / 255 * 100)
			else:
				self._tasmota_logger.debug(leddata)

		if plugip is not None:
			t = threading.Timer(0, self.gcode_led, [plugip, workleds])
			t.daemon = True
			t.start()

	def processGCODE(self, comm_instance, phase, cmd, cmd_type, gcode, *args, **kwargs):
		if gcode:
			if gcode in ["M80", "M81"] and cmd.count(" ") >= 2:
				plugip = cmd.split()[1]
				plugidx = cmd.split()[2]
				for plug in self._settings.get(["arrSmartplugs"]):
					if plug["ip"].upper() == plugip.upper() and plug["idx"] == plugidx and plug["gcodeEnabled"]:
						if cmd.startswith("M80"):
							self._tasmota_logger.debug(
								"Received M80 command, attempting power on of %s index %s." % (plugip, plugidx))
							t = threading.Timer(int(plug["gcodeOnDelay"]), self.gcode_on, [plug])
							t.daemon = True
							t.start()
							return
						elif cmd.startswith("M81"):
							self._tasmota_logger.debug(
								"Received M81 command, attempting power off of %s index %s." % (plugip, plugidx))
							t = threading.Timer(int(plug["gcodeOffDelay"]), self.gcode_off, [plug])
							t.daemon = True
							t.start()
							return
						else:
							return
			elif gcode == "M150":
				self.process_echo(comm_instance, "TASMOTA_{}".format(cmd), *args, **kwargs)
			elif self.powerOffWhenIdle and not (gcode in self._idleIgnoreCommandsArray):
				self._waitForHeaters = False
				self._reset_idle_timer()
			return

	def processAtCommand(self, comm_instance, phase, command, parameters, tags=None, *args, **kwargs):
		if command == 'TASMOTAIDLEON':
			self.powerOffWhenIdle = True
			self._reset_idle_timer()
		elif command == 'TASMOTAIDLEOFF':
			self.powerOffWhenIdle = False
			self._stop_idle_timer()
			if self._abort_timer is not None:
				self._abort_timer.cancel()
				self._abort_timer = None
			self._timeout_value = None
		elif command == 'TASMOTAON':
			plugip, plugidx = parameters.split(" ")
			self._tasmota_logger.debug("Received TASMOTAON command, attempting power on of %s:%s." % (plugip, plugidx))
			plug = self.plug_search(self._settings.get(["arrSmartplugs"]), "ip", plugip, "idx", plugidx)
			self._tasmota_logger.debug(plug)
			if plug and plug["gcodeEnabled"]:
				t = threading.Timer(int(plug["gcodeOnDelay"]), self.gcode_on, [plug])
				t.daemon = True
				t.start()
			return None
		elif command == 'TASMOTAOFF':
			plugip, plugidx = parameters.split(" ")
			self._tasmota_logger.debug("Received TASMOTAOFF command, attempting power off of %s:%s." % (plugip, plugidx))
			plug = self.plug_search(self._settings.get(["arrSmartplugs"]), "ip", plugip, "idx", plugidx)
			self._tasmota_logger.debug(plug)
			if plug and plug["gcodeEnabled"]:
				t = threading.Timer(int(plug["gcodeOffDelay"]), self.gcode_off, [plug])
				t.daemon = True
				t.start()
			return None

		if command in ["TASMOTAIDLEON", "TASMOTAIDLEOFF"]:
			self._plugin_manager.send_plugin_message(self._identifier,
													 dict(powerOffWhenIdle=self.powerOffWhenIdle, type="timeout",
														  timeout_value=self._timeout_value))

	##~~ Temperatures received hook

	def check_temps(self, parsed_temps):
		process_items = parsed_temps.items()
		try:
			for k, v in process_items:
				if k == "B" and v[0] > int(self._settings.get(["thermal_runaway_max_bed"])):
					self._tasmota_logger.debug("Max bed temp reached, shutting off plugs.")
					self._plugin_manager.send_plugin_message(self._identifier, {'thermal_runaway': True, 'type': "bed"})
					self.thermal_runaway_triggered = True
				if k.startswith("T") and v[0] > int(self._settings.get(["thermal_runaway_max_extruder"])):
					self._tasmota_logger.debug("Extruder max temp reached, shutting off plugs.")
					self._plugin_manager.send_plugin_message(self._identifier,
															 {'thermal_runaway': True, 'type': "extruder"})
					self.thermal_runaway_triggered = True
				if self.thermal_runaway_triggered == True:
					for plug in self._settings.get(['arrSmartplugs']):
						if plug["thermal_runaway"] == True:
							self.turn_off(plug["ip"], plug["idx"])
		except BaseException as e:
			self._logger.debug(e)

	def monitor_temperatures(self, comm, parsed_temps):
		if self._settings.get(["thermal_runaway_monitoring"]) and self.thermal_runaway_triggered == False:
			# Run inside it's own thread to prevent communication blocking
			t = threading.Timer(0, self.check_temps, [parsed_temps])
			t.daemon = True
			t.start()
		return parsed_temps

	##~~ Idle Timeout

	def _start_idle_timer(self):
		self._stop_idle_timer()

		if self.powerOffWhenIdle:
			self._idleTimer = ResettableTimer(self.idleTimeout * 60, self._idle_poweroff)
			self._idleTimer.daemon = True
			self._idleTimer.start()

	def _stop_idle_timer(self):
		if self._idleTimer:
			self._idleTimer.cancel()
			self._idleTimer = None

	def _reset_idle_timer(self):
		try:
			if self._idleTimer.is_alive():
				self._idleTimer.reset()
			else:
				raise Exception()
		except:
			self._start_idle_timer()

	def _idle_poweroff(self):
		if not self.powerOffWhenIdle:
			return

		if self._waitForHeaters:
			return

		if self._waitForTimelapse:
			return

		if self._printer.is_printing() or self._printer.is_paused():
			return

		if (uptime() / 60) <= (self._settings.get_int(["idleTimeout"])):
			self._tasmota_logger.debug("Just booted so wait for time sync.")
			self._tasmota_logger.debug(
				"uptime: {}, comparison: {}".format((uptime() / 60), (self._settings.get_int(["idleTimeout"]))))
			self._reset_idle_timer()
			return

		self._tasmota_logger.debug(
			"Idle timeout reached after %s minute(s). Turning heaters off prior to powering off plugs." % self.idleTimeout)
		if self._wait_for_heaters():
			self._tasmota_logger.debug("Heaters below temperature.")
			if self._wait_for_timelapse():
				self._timer_start()
		else:
			self._tasmota_logger.debug("Aborted power off due to activity.")
			self._reset_idle_timer()

	##~~ Timelapse Monitoring

	def _wait_for_timelapse(self):
		self._waitForTimelapse = True
		self._tasmota_logger.debug("Checking timelapse status before shutting off power...")

		while True:
			if not self._waitForTimelapse:
				return False

			if not self._timelapse_active or not self._settings.get_boolean(["idleWaitForTimelapse"]):
				self._waitForTimelapse = False
				return True

			self._tasmota_logger.debug("Waiting for timelapse before shutting off power...")
			time.sleep(5)

	##~~ Temperature Cooldown

	def _wait_for_heaters(self):
		self._waitForHeaters = True
		heaters = self._printer.get_current_temperatures()

		for heater, entry in heaters.items():
			target = entry.get("target")
			if target is None:
				# heater doesn't exist in fw
				continue

			try:
				temp = float(target)
			except ValueError:
				# not a float for some reason, skip it
				continue

			if temp != 0:
				self._tasmota_logger.debug("Turning off heater: %s" % heater)
				self._skipIdleTimer = True
				self._printer.set_temperature(heater, 0)
				self._skipIdleTimer = False
			else:
				self._tasmota_logger.debug("Heater %s already off." % heater)

		while True:
			if not self._waitForHeaters:
				return False

			heaters = self._printer.get_current_temperatures()

			highest_temp = 0
			heaters_above_waittemp = []
			for heater, entry in heaters.items():
				if not heater.startswith("tool"):
					continue

				actual = entry.get("actual")
				if actual is None:
					# heater doesn't exist in fw
					continue

				try:
					temp = float(actual)
				except ValueError:
					# not a float for some reason, skip it
					continue

				self._tasmota_logger.debug("Heater %s = %sC" % (heater, temp))
				if temp > self.idleTimeoutWaitTemp:
					heaters_above_waittemp.append(heater)

				if temp > highest_temp:
					highest_temp = temp

			if highest_temp <= self.idleTimeoutWaitTemp:
				self._waitForHeaters = False
				return True

			self._tasmota_logger.debug(
				"Waiting for heaters(%s) before shutting power off..." % ', '.join(heaters_above_waittemp))
			time.sleep(5)

	##~~ Abort Power Off Timer

	def _timer_start(self):
		if self._abort_timer is not None:
			return

		self._tasmota_logger.debug("Starting abort power off timer.")

		self._timeout_value = self.abortTimeout
		self._abort_timer = RepeatedTimer(1, self._timer_task)
		self._abort_timer.start()

	def _timer_task(self):
		if self._timeout_value is None:
			return

		self._timeout_value -= 1
		self._plugin_manager.send_plugin_message(self._identifier,
												 {'powerOffWhenIdle': self.powerOffWhenIdle, 'type': "timeout",
												  'timeout_value': self._timeout_value})
		if self._timeout_value <= 0:
			if self._abort_timer is not None:
				self._abort_timer.cancel()
				self._abort_timer = None
			self._shutdown_system()

	def _shutdown_system(self):
		self._tasmota_logger.debug("Automatically powering off enabled plugs.")
		for plug in self._settings.get(['arrSmartplugs']):
			if plug.get("automaticShutdownEnabled", False):
				self.turn_off("{ip}".format(**plug), "{idx}".format(**plug))

	##~~ Utility functions

	def lookup(self, dic, key, *keys):
		if keys:
			return self.lookup(dic.get(key, {}), *keys)
		return dic.get(key)

	def plug_search(self, list, key1, value1, key2, value2):
		for item in list:
			if item[key1] == value1 and item[key2] == value2:
				return item

	def deep_get(self, d, keys, default=None):
		"""
		Example:
			d = {'meta': {'status': 'OK', 'status_code': 200}}
			deep_get(d, ['meta', 'status_code'])		  # => 200
			deep_get(d, ['garbage', 'status_code'])	   # => None
			deep_get(d, ['meta', 'garbage'], default='-') # => '-'
		"""
		assert type(keys) is list
		if d is None:
			return default
		if not keys:
			return d
		return self.deep_get(d.get(keys[0]), keys[1:], default)

	##~~ Access Permissions Hook

	def get_additional_permissions(self, *args, **kwargs):
		return [
			{'key': "CONTROL", 'name': "Control Devices",
			 'description': gettext("Allows control of configured devices."), 'roles': ["admin"], 'dangerous': True,
			 'default_groups': [ADMIN_GROUP]}
		]

	##~~ Softwareupdate hook

	def get_update_information(self):
		return {'tasmota': {'displayName': "Tasmota", 'displayVersion': self._plugin_version, 'type': "github_release",
							'user': "jneilliii", 'repo': "OctoPrint-Tasmota", 'current': self._plugin_version,
							'stable_branch': {'name': "Stable", 'branch': "master", 'comittish': ["master"]},
							'prerelease_branches': [
								{'name': "Release Candidate", 'branch': "rc", 'comittish': ["rc", "master"]}
							], 'pip': "https://github.com/jneilliii/OctoPrint-Tasmota/archive/{target_version}.zip"}}


__plugin_name__ = "Tasmota"
__plugin_pythoncompat__ = ">=2.7,<4"


def __plugin_load__():
	global __plugin_implementation__
	__plugin_implementation__ = tasmotaPlugin()

	global __plugin_hooks__
	__plugin_hooks__ = {
		"octoprint.comm.protocol.gcode.queuing": __plugin_implementation__.processGCODE,
		"octoprint.comm.protocol.gcode.received": __plugin_implementation__.process_echo,
		"octoprint.comm.protocol.atcommand.sending": __plugin_implementation__.processAtCommand,
		"octoprint.comm.protocol.temperatures.received": __plugin_implementation__.monitor_temperatures,
		"octoprint.access.permissions": __plugin_implementation__.get_additional_permissions,
		"octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
	}
