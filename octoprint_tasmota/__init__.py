# coding=utf-8
from __future__ import absolute_import

import octoprint.plugin
from octoprint.server import user_permission
from octoprint.util import RepeatedTimer
from octoprint.events import eventManager, Events
import socket
import time
import logging
import os
import re
import requests
import threading
import sqlite3
from datetime import datetime, timedelta

class tasmotaPlugin(octoprint.plugin.SettingsPlugin,
							octoprint.plugin.AssetPlugin,
							octoprint.plugin.TemplatePlugin,
							octoprint.plugin.SimpleApiPlugin,
							octoprint.plugin.StartupPlugin,
							octoprint.plugin.EventHandlerPlugin):

	def __init__(self):
		self._logger = logging.getLogger("octoprint.plugins.tasmota")
		self._tasmota_logger = logging.getLogger("octoprint.plugins.tasmota.debug")
		self.thermal_runaway_triggered = False
		self.poll_status = None
		self.abortTimeout = 0
		self._automatic_shutdown_enabled = False
		self._timeout_value = None
		self._abort_timer = None
		self._wait_for_timelapse_timer = None

	##~~ StartupPlugin mixin

	def on_startup(self, host, port):
		# setup customized logger
		from octoprint.logging.handlers import CleaningTimedRotatingFileHandler
		tasmota_logging_handler = CleaningTimedRotatingFileHandler(self._settings.get_plugin_logfile_path(postfix="debug"), when="D", backupCount=3)
		tasmota_logging_handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s"))
		tasmota_logging_handler.setLevel(logging.DEBUG)

		self._tasmota_logger.addHandler(tasmota_logging_handler)
		self._tasmota_logger.setLevel(logging.DEBUG if self._settings.get_boolean(["debug_logging"]) else logging.INFO)
		self._tasmota_logger.propagate = False

		self.energy_db_path = os.path.join(self.get_plugin_data_folder(),"energy_data.db")
		if not os.path.exists(self.energy_db_path):
			db = sqlite3.connect(self.energy_db_path)
			cursor = db.cursor()
			cursor.execute('''CREATE TABLE energy_data(id INTEGER PRIMARY KEY, ip TEXT, idx TEXT, timestamp TEXT, current REAL, power REAL, total REAL, voltage REAL)''')
			db.commit()
			db.close()

		self.sensor_db_path = os.path.join(self.get_plugin_data_folder(),"sensor_data.db")
		if not os.path.exists(self.sensor_db_path):
			db = sqlite3.connect(self.sensor_db_path)
			cursor = db.cursor()
			cursor.execute('''CREATE TABLE sensor_data(id INTEGER PRIMARY KEY, ip TEXT, idx TEXT, timestamp TEXT, temperature REAL, humidity REAL)''')
			db.commit()
			db.close()

		self.abortTimeout = self._settings.get_int(["abortTimeout"])
		self._tasmota_logger.debug("abortTimeout: %s" % self.abortTimeout)

		self.automatic_power_off = self._settings.get_boolean(["automatic_power_off"])
		self._tasmota_logger.debug("automatic_power_off: %s" % self.automatic_power_off)

		if self.automatic_power_off:
			self._automatic_shutdown_enabled = True

	def on_after_startup(self):
		self._logger.info("Tasmota loaded!")
		if self._settings.get(["polling_enabled"]):
			self.poll_status = RepeatedTimer(int(self._settings.get(["polling_interval"]))*60, self.check_statuses)
			self.poll_status.start()

	##~~ SettingsPlugin mixin

	def get_settings_defaults(self):
		return dict(
			debug_logging = False,
			polling_enabled = False,
			polling_interval = 0,
			thermal_runaway_monitoring = False,
			thermal_runaway_max_bed = 120,
			thermal_runaway_max_extruder = 300,
			arrSmartplugs = [],
			abortTimeout = 30,
			automatic_power_off = False
		)

	def on_settings_save(self, data):
		old_debug_logging = self._settings.get_boolean(["debug_logging"])
		old_polling_value = self._settings.get_boolean(["polling_enabled"])
		old_polling_timer = self._settings.get(["polling_interval"])
		old_automatic_power_off = self._settings.get_boolean(["automatic_power_off"])

		octoprint.plugin.SettingsPlugin.on_settings_save(self, data)

		self.abortTimeout = self._settings.get_int(["abortTimeout"])
		self._automatic_shutdown_enabled = self._settings.get_boolean(["automatic_power_off"])

		if self._automatic_shutdown_enabled != old_automatic_power_off:
			self._plugin_manager.send_plugin_message(self._identifier, dict(automaticShutdownEnabled=self._automatic_shutdown_enabled, type="timeout", timeout_value=self._timeout_value))

		new_debug_logging = self._settings.get_boolean(["debug_logging"])
		new_polling_value = self._settings.get_boolean(["polling_enabled"])
		new_polling_timer = self._settings.get(["polling_interval"])

		if old_debug_logging != new_debug_logging:
			if new_debug_logging:
				self._tasmota_logger.setLevel(logging.DEBUG)
			else:
				self._tasmota_logger.setLevel(logging.INFO)

		if old_polling_value != new_polling_value or old_polling_timer != new_polling_timer:
			if self.poll_status:
				self.poll_status.cancel()
				
			if new_polling_value:
				self.poll_status = RepeatedTimer(int(self._settings.get(["polling_interval"]))*60, self.check_statuses)
				self.poll_status.start()

	def get_settings_version(self):
		return 7

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
			self._settings.set(["arrSmartplugs"],arrSmartplugs_new)

	##~~ AssetPlugin mixin

	def get_assets(self):
		return dict(
			js=["js/jquery-ui.min.js","js/knockout-sortable.js","js/fontawesome-iconpicker.js","js/ko.iconpicker.js","js/plotly-latest.min.js","js/knockout-bootstrap.min.js","js/tasmota.js"],
			css=["css/font-awesome.min.css","css/font-awesome-v4-shims.min.css","css/fontawesome-iconpicker.css","css/tasmota.css"]
		)

	##~~ TemplatePlugin mixin

	def get_template_configs(self):
		return [
			dict(type="navbar", custom_bindings=True),
			dict(type="settings", custom_bindings=True),
			dict(type="tab", custom_bindings=True),
			dict(type="sidebar", icon="plug", custom_bindings=True, data_bind="visible: show_sidebar", template="tasmota_sidebar.jinja2", template_header="tasmota_sidebar_header.jinja2", styles=["display: none"])
		]

	##~~ EventHandlerPlugin mixin

	def on_event(self, event, payload):
		if event == Events.CLIENT_OPENED:
			self._plugin_manager.send_plugin_message(self._identifier, dict(automaticShutdownEnabled=self._automatic_shutdown_enabled, type="timeout", timeout_value=self._timeout_value))
			return
		if event == Events.PRINT_FAILED and not self._printer.is_closed_or_error():
			#Cancelled job
			return
		if event == Events.PRINT_STARTED and self._automatic_shutdown_enabled:
			if self._abort_timer is not None:
				self._abort_timer.cancel()
				self._abort_timer = None
			self._timeout_value = None
			self._tasmota_logger.debug("Power off aborted because starting new print.")
			self._plugin_manager.send_plugin_message(self._identifier, dict(automaticShutdownEnabled=self._automatic_shutdown_enabled, type="timeout", timeout_value=self._timeout_value))
		if event in [Events.PRINT_DONE, Events.PRINT_FAILED] and self._automatic_shutdown_enabled:
			self._timer_start()
			return

	##~~ SimpleApiPlugin mixin

	def turn_on(self, plugip, plugidx):
		self._tasmota_logger.debug("Turning on %s index %s." % (plugip, plugidx))
		plug = self.plug_search(self._settings.get(["arrSmartplugs"]),"ip",plugip,"idx",plugidx)
		try:
			if plug["use_backlog"] and int(plug["backlog_on_delay"]) > 0:
				webresponse = requests.get("http://" + plug["ip"] + "/cm?user=" + plug["username"] + "&password=" + requests.utils.quote(plug["password"]) + "&cmnd=backlog%20delay%20" + str(int(plug["backlog_on_delay"])*10) + "%3BPower" + str(plug["idx"]) + "%20on%3B")
				response = dict()
				response["POWER%s" % plug["idx"]] = "ON"
			else:
				webresponse = requests.get("http://" + plug["ip"] + "/cm?user=" + plug["username"] + "&password=" + requests.utils.quote(plug["password"]) + "&cmnd=Power" + str(plug["idx"]) + "%20on")
				response = webresponse.json()
			chk = response["POWER%s" % plug["idx"]]
		except:
			self._tasmota_logger.error('Invalid ip or unknown error connecting to %s.' % plug["ip"], exc_info=True)
			response = "Unknown error turning on %s index %s." % (plugip, plugidx)
			chk = "UNKNOWN"

		self._tasmota_logger.debug("Response: %s" % response)

		if chk.upper() == "ON":
			if plug["autoConnect"] and self._printer.is_closed_or_error():
				c = threading.Timer(int(plug["autoConnectDelay"]),self._printer.connect)
				c.start()
			if plug["sysCmdOn"]:
				t = threading.Timer(int(plug["sysCmdOnDelay"]),os.system,args=[plug["sysRunCmdOn"]])
				t.start()
			self._plugin_manager.send_plugin_message(self._identifier, dict(currentState="on",ip=plugip,idx=plugidx))
		elif chk.upper() == "OFF":
			self._plugin_manager.send_plugin_message(self._identifier, dict(currentState="off",ip=plugip,idx=plugidx))
		else:
			self._tasmota_logger.debug(response)
			self._plugin_manager.send_plugin_message(self._identifier, dict(currentState="unknown",ip=plugip,idx=plugidx))

	def turn_off(self, plugip, plugidx):
		plug = self.plug_search(self._settings.get(["arrSmartplugs"]),"ip",plugip,"idx",plugidx)
		self._tasmota_logger.debug("Turning off %s " % plug)
		try:
			if plug["use_backlog"] and int(plug["backlog_off_delay"]) > 0:
				self._tasmota_logger.debug("Using backlog commands with a delay value of %s" % str(int(plug["backlog_off_delay"])*10))
				backlog_url = "http://" + plug["ip"] + "/cm?user=" + plug["username"] + "&password=" + requests.utils.quote(plug["password"]) + "&cmnd=backlog%20delay%20" + str(int(plug["backlog_off_delay"])*10) + "%3BPower" + str(plug["idx"]) + "%20off%3B"
				self._tasmota_logger.debug("Sending command %s" % backlog_url)
				webresponse = requests.get(backlog_url)
				response = dict()
				response["POWER%s" % plug["idx"]] = "OFF"

			if plug["sysCmdOff"]:
				self._tasmota_logger.debug("Running system command: %s in %s" % (plug["sysRunCmdOff"],plug["sysCmdOffDelay"]))
				t = threading.Timer(int(plug["sysCmdOffDelay"]),os.system,args=[plug["sysRunCmdOff"]])
				t.start()

			if plug["autoDisconnect"]:
				self._tasmota_logger.debug("Disconnnecting from printer")
				self._printer.disconnect()
				time.sleep(int(plug["autoDisconnectDelay"]))

			if not plug["use_backlog"]:
				self._tasmota_logger.debug("Not using backlog commands")
				webresponse = requests.get("http://" + plug["ip"] + "/cm?user=" + plug["username"] + "&password=" + requests.utils.quote(plug["password"]) + "&cmnd=Power" + str(plug["idx"]) + "%20off")
				response = webresponse.json()
			chk = response["POWER%s" % plug["idx"]]
		except:
			self._tasmota_logger.error('Invalid ip or unknown error connecting to %s.' % plug["ip"], exc_info=True)
			response = "Unknown error turning off %s index %s." % (plugip, plugidx)
			chk = "UNKNOWN"

		self._tasmota_logger.debug("Response: %s" % response)
		if chk.upper() == "ON":
			self._plugin_manager.send_plugin_message(self._identifier, dict(currentState="on",ip=plugip,idx=plugidx))
		elif chk.upper() == "OFF":
			self._plugin_manager.send_plugin_message(self._identifier, dict(currentState="off",ip=plugip,idx=plugidx))
		else:
			self._tasmota_logger.debug(response)
			self._plugin_manager.send_plugin_message(self._identifier, dict(currentState="unknown",ip=plugip,idx=plugidx))

	def check_statuses(self):
		for plug in self._settings.get(["arrSmartplugs"]):
			self.check_status(plug["ip"], plug["idx"])

	def check_status(self, plugip, plugidx):
		self._tasmota_logger.debug("Checking status of %s index %s." % (plugip, plugidx))
		if plugip != "":
			try:
				plug = self.plug_search(self._settings.get(["arrSmartplugs"]),"ip",plugip,"idx",plugidx)
				self._tasmota_logger.debug(plug)
				webresponse = requests.get("http://" + plugip + "/cm?user=" + plug["username"] + "&password=" + requests.utils.quote(plug["password"]) + "&cmnd=Status%200")
				response = webresponse.json()
				self._tasmota_logger.debug("%s index %s response: %s" % (plugip, plugidx, response))
				#chk = response["POWER%s" % plugidx]
				chk = self.lookup(response,*["StatusSTS","POWER" + plugidx])
				if chk is None:
					chk = "UNKNOWN"
				energy_data = self.lookup(response,*["StatusSNS","ENERGY"])
				if energy_data is not None:
					today = datetime.today()
					c = self.lookup(response,*["StatusSNS","ENERGY","Current"])
					p = self.lookup(response,*["StatusSNS","ENERGY","Power"])
					t = self.lookup(response,*["StatusSNS","ENERGY","Total"])
					v = self.lookup(response,*["StatusSNS","ENERGY","Voltage"])
					self._tasmota_logger.debug("Energy Data: %s" % energy_data)
					db = sqlite3.connect(self.energy_db_path)
					cursor = db.cursor()
					cursor.execute('''INSERT INTO energy_data(ip, idx, timestamp, current, power, total, voltage) VALUES(?,?,?,?,?,?,?)''', [plugip,plugidx,today.isoformat(' '),c,p,t,v])
					db.commit()
					db.close()
				if plug["sensor_identifier"] != "":
					sensor_data = self.lookup(response,*["StatusSNS",plug["sensor_identifier"]])
					if sensor_data is not None:
						today = datetime.today()
						t = self.lookup(response,*["StatusSNS",plug["sensor_identifier"],"Temperature"])
						h = self.lookup(response,*["StatusSNS",plug["sensor_identifier"],"Humidity"])
						self._tasmota_logger.debug("Sensor Data: %s" % sensor_data)
						db = sqlite3.connect(self.sensor_db_path)
						cursor = db.cursor()
						cursor.execute('''INSERT INTO sensor_data(ip, idx, timestamp, temperature, humidity) VALUES(?,?,?,?,?)''', [plugip,plugidx,today.isoformat(' '),t,h])
						db.commit()
						db.close()
				else:
					sensor_data = None
			except:
				self._tasmota_logger.error('Invalid ip or unknown error connecting to %s.' % plugip, exc_info=True)
				response = "unknown error with %s." % plugip
				chk = "UNKNOWN"

			self._tasmota_logger.debug("%s index %s is %s" % (plugip, plugidx, chk))
			if chk.upper() == "ON":
				self._plugin_manager.send_plugin_message(self._identifier, dict(currentState="on",ip=plugip,idx=plugidx,energy_data=energy_data,sensor_data=sensor_data))
			elif chk.upper() == "OFF":
				self._plugin_manager.send_plugin_message(self._identifier, dict(currentState="off",ip=plugip,idx=plugidx,energy_data=energy_data,sensor_data=sensor_data))
			else:
				self._tasmota_logger.debug(response)
				self._plugin_manager.send_plugin_message(self._identifier, dict(currentState="unknown",ip=plugip,idx=plugidx))

	def checkSetOption26(self, plugip, username, password):
		webresponse = requests.get("http://" + plugip + "/cm?user=" + username + "&password=" + requests.utils.quote(password) + "&cmnd=SetOption26")
		response = webresponse.json()
		self._tasmota_logger.debug(response)
		return response

	def setSetOption26(self, plugip, username, password):
		webresponse = requests.get("http://" + plugip + "/cm?user=" + username + "&password=" + requests.utils.quote(password) + "&cmnd=SetOption26%20ON")
		response = webresponse.json()
		self._tasmota_logger.debug(response)
		return response

	def get_api_commands(self):
		return dict(turnOn=["ip","idx"],
					turnOff=["ip","idx"],
					checkStatus=["ip","idx"],
					getEnergyData=[],
					checkSetOption26=["ip","username","password"],
					setSetOption26=["ip","username","password"],
					enableAutomaticShutdown=[],
					disableAutomaticShutdown=[],
					abortAutomaticShutdown=[])

	def on_api_command(self, command, data):
		self._tasmota_logger.debug(data)
		if not user_permission.can():
			from flask import make_response
			return make_response("Insufficient rights", 403)

		if command == 'turnOn':
			self.turn_on("{ip}".format(**data),"{idx}".format(**data))
		elif command == 'turnOff':
			self.turn_off("{ip}".format(**data),"{idx}".format(**data))
		elif command == 'checkStatus':
			self.check_status("{ip}".format(**data),"{idx}".format(**data))
		elif command == 'checkSetOption26':
			response = self.checkSetOption26("{ip}".format(**data),"{username}".format(**data),"{password}".format(**data))
			import flask
			return flask.jsonify(response)
		elif command == 'setSetOption26':
			response = self.setSetOption26("{ip}".format(**data),"{username}".format(**data),"{password}".format(**data))
			import flask
			return flask.jsonify(response)
		elif command == 'enableAutomaticShutdown':
			self._automatic_shutdown_enabled = True
		elif command == 'disableAutomaticShutdown':
			self._automatic_shutdown_enabled = False
		elif command == 'abortAutomaticShutdown':
			if self._abort_timer is not None:
				self._abort_timer.cancel()
				self._abort_timer = None
			self._timeout_value = None
			self._tasmota_logger.debug("Power off aborted.")
		elif command == 'getEnergyData':
			self._logger.info(data);
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
			energy_cursor.execute('''SELECT ip || ':' || idx AS ip, group_concat(timestamp) as timestamp, group_concat(current) as current, group_concat(power) as power, group_concat(total) as total FROM energy_data WHERE timestamp BETWEEN ? AND ? GROUP BY ip, idx''', [start_date, end_date])
			response["energy_data"] = energy_cursor.fetchall()
			energy_db.close()

			sensor_db = sqlite3.connect(self.sensor_db_path)
			sensor_cursor = sensor_db.cursor()
			sensor_cursor.execute('''SELECT ip || ':' || idx AS ip, group_concat(timestamp) as timestamp, group_concat(temperature) as temperature, group_concat(humidity) as humidity FROM sensor_data WHERE timestamp BETWEEN ? AND ? GROUP BY ip, idx''', [start_date, end_date])
			response["sensor_data"] = sensor_cursor.fetchall()
			sensor_db.close()

			import flask
			return flask.jsonify(response)

		if command == "enableAutomaticShutdown" or command == "disableAutomaticShutdown":
			self._tasmota_logger.debug("Automatic power off setting changed: %s" % self._automatic_shutdown_enabled)
			self._settings.set_boolean(["automatic_power_off"], self._automatic_shutdown_enabled)
			self._settings.save()
			eventManager().fire(Events.SETTINGS_UPDATED)
		if command == "enableAutomaticShutdown" or command == "disableAutomaticShutdown" or command == "abortAutomaticShutdown":
			self._plugin_manager.send_plugin_message(self._identifier, dict(automaticShutdownEnabled=self._automatic_shutdown_enabled, type="timeout", timeout_value=self._timeout_value))

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

	def processGCODE(self, comm_instance, phase, cmd, cmd_type, gcode, *args, **kwargs):
		if gcode in ["M80","M81"] and cmd.count(" ") >= 2:
			plugip = cmd.split()[1]
			plugidx = cmd.split()[2]
			for plug in self._settings.get(["arrSmartplugs"]):
				if plug["ip"].upper() == plugip.upper() and plug["idx"] == plugidx and plug["gcodeEnabled"]:
					if cmd.startswith("M80"):
						self._tasmota_logger.debug("Received M80 command, attempting power on of %s index %s." % (plugip,plugidx))
						t = threading.Timer(int(plug["gcodeOnDelay"]),self.gcode_on, [plug])
						t.start()
						return
					elif cmd.startswith("M81"):
						self._tasmota_logger.debug("Received M81 command, attempting power off of %s index %s." % (plugip,plugidx))
						t = threading.Timer(int(plug["gcodeOffDelay"]),self.gcode_off, [plug])
						t.start()
						return
					else:
						return
			return

	##~~ Temperatures received hook

	def check_temps(self, parsed_temps):
		for k, v in parsed_temps.items():
			if k == "B" and v[0] > int(self._settings.get(["thermal_runaway_max_bed"])):
				self._tasmota_logger.debug("Max bed temp reached, shutting off plugs.")
				self.thermal_runaway_triggered = True
			if k.startswith("T") and v[0] > int(self._settings.get(["thermal_runaway_max_extruder"])):
				self._tasmota_logger.debug("Extruder max temp reached, shutting off plugs.")
				self.thermal_runaway_triggered = True
			if self.thermal_runaway_triggered == True:
				for plug in self._settings.get(['arrSmartplugs']):
					if plug["thermal_runaway"] == True:
						self.turn_off(plug["ip"],plug["idx"])

	def monitor_temperatures(self, comm, parsed_temps):
		if self._settings.get(["thermal_runaway_monitoring"]) and self.thermal_runaway_triggered == False:
			# Run inside it's own thread to prevent communication blocking
			t = threading.Timer(0,self.check_temps,[parsed_temps])
			t.start()
		return parsed_temps

	##~~ Automatic Power Off

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
		self._plugin_manager.send_plugin_message(self._identifier, dict(automaticShutdownEnabled=self._automatic_shutdown_enabled, type="timeout", timeout_value=self._timeout_value))
		if self._timeout_value <= 0:
			if self._abort_timer is not None:
				self._abort_timer.cancel()
				self._abort_timer = None
			self._shutdown_system()

	def _shutdown_system(self):
		self._tasmota_logger.debug("Automatically shutting down enabled plugs.")
		for plug in self._settings.get(['arrSmartplugs']):
			if plug.get("automaticShutdownEnabled", False):
				response = self.turn_off("{ip}".format(**plug),"{idx}".format(**plug))

	##~~ Utility functions

	def lookup(self, dic, key, *keys):
		if keys:
			return self.lookup(dic.get(key, {}), *keys)
		return dic.get(key)

	def plug_search(self, list, key1, value1, key2, value2): 
		for item in list: 
			if item[key1] == value1 and item[key2] == value2: 
				return item


	##~~ Softwareupdate hook

	def get_update_information(self):
		# Define the configuration for your plugin to use with the Software Update
		# Plugin here. See https://github.com/foosel/OctoPrint/wiki/Plugin:-Software-Update
		# for details.
		return dict(
			tasmota=dict(
				displayName="OctoPrint-Tasmota",
				displayVersion=self._plugin_version,

				# version check: github repository
				type="github_release",
				user="jneilliii",
				repo="OctoPrint-Tasmota",
				current=self._plugin_version,

				# update method: pip
				pip="https://github.com/jneilliii/OctoPrint-Tasmota/archive/{target_version}.zip"
			)
		)


# If you want your plugin to be registered within OctoPrint under a different name than what you defined in setup.py
# ("OctoPrint-PluginSkeleton"), you may define that here. Same goes for the other metadata derived from setup.py that
# can be overwritten via __plugin_xyz__ control properties. See the documentation for that.
__plugin_name__ = "Tasmota"
__plugin_pythoncompat__ = ">=2.7,<4"

def __plugin_load__():
	global __plugin_implementation__
	__plugin_implementation__ = tasmotaPlugin()

	global __plugin_hooks__
	__plugin_hooks__ = {
		"octoprint.comm.protocol.gcode.queuing": __plugin_implementation__.processGCODE,
		"octoprint.comm.protocol.temperatures.received": __plugin_implementation__.monitor_temperatures,
		"octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
	}

