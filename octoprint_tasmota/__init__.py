# coding=utf-8
from __future__ import absolute_import

import octoprint.plugin
from octoprint.server import user_permission
import socket
import json
import time
import logging
import os
import re
import urllib2

class tasmotaPlugin(octoprint.plugin.SettingsPlugin,
                            octoprint.plugin.AssetPlugin,
                            octoprint.plugin.TemplatePlugin,
							octoprint.plugin.SimpleApiPlugin,
							octoprint.plugin.StartupPlugin):
							
	def __init__(self):
		self._logger = logging.getLogger("octoprint.plugins.tasmota")
		self._tasmota_logger = logging.getLogger("octoprint.plugins.tasmota.debug")
							
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
	
	def on_after_startup(self):
		self._logger.info("Tasmota loaded!")
	
	##~~ SettingsPlugin mixin
	
	def get_settings_defaults(self):
		return dict(
			debug_logging = False,
			arrSmartplugs = [{'ip':'','displayWarning':True,'idx':1,'warnPrinting':False,'gcodeEnabled':False,'gcodeOnDelay':0,'gcodeOffDelay':0,'autoConnect':True,'autoConnectDelay':10.0,'autoDisconnect':True,'autoDisconnectDelay':0,'sysCmdOn':False,'sysRunCmdOn':'','sysCmdOnDelay':0,'sysCmdOff':False,'sysRunCmdOff':'','sysCmdOffDelay':0,'currentState':'unknown','btnColor':'#808080','username':'','password':''}],
		)
		
	def on_settings_save(self, data):	
		old_debug_logging = self._settings.get_boolean(["debug_logging"])

		octoprint.plugin.SettingsPlugin.on_settings_save(self, data)

		new_debug_logging = self._settings.get_boolean(["debug_logging"])
		if old_debug_logging != new_debug_logging:
			if new_debug_logging:
				self._tasmota_logger.setLevel(logging.DEBUG)
			else:
				self._tasmota_logger.setLevel(logging.INFO)
				
	def get_settings_version(self):
		return 2
		
	def on_settings_migrate(self, target, current=None):
		if current is None or current < self.get_settings_version():
			# Reset plug settings to defaults.
			self._logger.debug("Resetting arrSmartplugs for tasmota settings.")
			self._settings.set(['arrSmartplugs'], self.get_settings_defaults()["arrSmartplugs"])
		
	##~~ AssetPlugin mixin

	def get_assets(self):
		return dict(
			js=["js/tasmota.js"]
		)
		
	##~~ TemplatePlugin mixin
	
	def get_template_configs(self):
		return [
			dict(type="navbar", custom_bindings=True),
			dict(type="settings", custom_bindings=True)
		]
		
	##~~ SimpleApiPlugin mixin
	
	def turn_on(self, plugip, plugidx, **kwargs):
		self._tasmota_logger.debug("Turning on %s index %s." % (plugip, plugidx))
		try:
			if "username" in kwargs:
				webresponse = urllib2.urlopen("http://" + plugip + "/cm?user=" + kwargs["username"] + "&password=" + kwargs["password"] + "&cmnd=Power" + str(plugidx) + "%20on").read()
			else:
				webresponse = urllib2.urlopen("http://" + plugip + "/cm?cmnd=Power" + str(plugidx) + "%20on").read()
			response = json.loads(webresponse.split()[2])
			chk = response["POWER"]
		except:			
			self._tasmota_logger.error('Invalid ip or unknown error connecting to %s.' % plugip, exc_info=True)
			response = "Unknown error turning on %s index %s." % (plugip, plugidx)
			chk = "UNKNOWN"
			
		self._tasmota_logger.debug("Response: %s" % response)
		
		if chk == "ON":
			self._plugin_manager.send_plugin_message(self._identifier, dict(currentState="on",ip=plugip,idx=plugidx))
		elif chk == "OFF":
			self._plugin_manager.send_plugin_message(self._identifier, dict(currentState="off",ip=plugip,idx=plugidx))
		else:
			self._tasmota_logger.debug(response)
			self._plugin_manager.send_plugin_message(self._identifier, dict(currentState="unknown",ip=plugip,idx=plugidx))
	
	def turn_off(self, plugip, plugidx):
		self._tasmota_logger.debug("Turning off %s index %s." % (plugip, plugidx))
		try:
			webresponse = urllib2.urlopen("http://" + plugip + "/cm?cmnd=Power" + str(plugidx) + "%20off").read()
			response = json.loads(webresponse.split()[2])
			chk = response["POWER"]
		except:
			self._tasmota_logger.error('Invalid ip or unknown error connecting to %s.' % plugip, exc_info=True)
			response = "Unknown error turning off %s index %s." % (plugip, plugidx)
			chk = "UNKNOWN"
			
		self._tasmota_logger.debug("Response: %s" % response)
		
		if chk == "ON":
			self._plugin_manager.send_plugin_message(self._identifier, dict(currentState="on",ip=plugip,idx=plugidx))
		elif chk == "OFF":
			self._plugin_manager.send_plugin_message(self._identifier, dict(currentState="off",ip=plugip,idx=plugidx))
		else:
			self._tasmota_logger.debug(response)
			self._plugin_manager.send_plugin_message(self._identifier, dict(currentState="unknown",ip=plugip,idx=plugidx))
		
	def check_status(self, plugip, plugidx, username="admin", password=""):
		self._tasmota_logger.debug("Checking status of %s index %s." % (plugip, plugidx))
		if plugip != "":
			try:
				webresponse = urllib2.urlopen("http://" + plugip + "/cm?user=" + username + "&password=" + password + "cmnd=Power" + str(plugidx)).read()
				self._tasmota_logger.debug("%s index %s response: %s" % (plugip, plugidx, webresponse))
				response = json.loads(webresponse.split()[2])
				chk = response["POWER"]
			except:
				self._tasmota_logger.error('Invalid ip or unknown error connecting to %s.' % plugip, exc_info=True)
				response = "unknown error with %s." % plugip
				chk = "UNKNOWN"
				
			self._tasmota_logger.debug("%s index %s is %s" % (plugip, plugidx, chk))
			
			if chk == "ON":
				self._plugin_manager.send_plugin_message(self._identifier, dict(currentState="on",ip=plugip,idx=plugidx))
			elif chk == "OFF":
				self._plugin_manager.send_plugin_message(self._identifier, dict(currentState="off",ip=plugip,idx=plugidx))
			else:
				self._tasmota_logger.debug(response)
				self._plugin_manager.send_plugin_message(self._identifier, dict(currentState="unknown",ip=plugip,idx=plugidx))		
	
	def get_api_commands(self):
		return dict(turnOn=["ip","idx"],turnOff=["ip","idx"],checkStatus=["ip","idx"],connectPrinter=[],disconnectPrinter=[],sysCommand=["cmd"])

	def on_api_command(self, command, data):
		self._tasmota_logger.debug(data)
		if not user_permission.can():
			from flask import make_response
			return make_response("Insufficient rights", 403)
        
		if command == 'turnOn':
			if "username" in data and data["username"] != "":
				self._tasmota_logger.debug("Using authentication for %s." % "{ip}".format(**data))
				self.turn_on("{ip}".format(**data),"{idx}".format(**data),username="{username}".format(**data),password="{password}".format(**data))
			else:
				self.turn_on("{ip}".format(**data),"{idx}".format(**data))
		elif command == 'turnOff':
			self.turn_off("{ip}".format(**data),"{idx}".format(**data))
		elif command == 'checkStatus':
			if "username" in data and data["username"] != "":
				self._tasmota_logger.debug("Using authentication for %s." % "{ip}".format(**data))
				self.check_status("{ip}".format(**data),"{idx}".format(**data),username="{username}".format(**data),password="{password}".format(**data))
			else:
				self.check_status("{ip}".format(**data),"{idx}".format(**data))
		elif command == 'connectPrinter':
			self._tasmota_logger.debug("Connecting printer.")
			self._printer.connect()
		elif command == 'disconnectPrinter':
			self._tasmota_logger.debug("Disconnecting printer.")
			self._printer.disconnect()
		elif command == 'sysCommand':
			self._tasmota_logger.debug("Running system command %s." % "{cmd}".format(**data))
			os.system("{cmd}".format(**data))
			
	##~~ Gcode processing hook
	
	def processGCODE(self, comm_instance, phase, cmd, cmd_type, gcode, *args, **kwargs):
		if gcode:
			if cmd.count(" ") >= 2:
				plugip = cmd.split()[1]
				plugidx = cmd.split()[2]
				if cmd.startswith("M80"):
					self._plugin_manager.send_plugin_message(self._identifier, dict(currentState="unknown",gcodeon=True,ip=plugip,idx=plugidx))
					self._tasmota_logger.debug("Received M80 command, attempting power on.")
					return
				elif cmd.startswith("M81"):
					self._plugin_manager.send_plugin_message(self._identifier, dict(currentState="unknown",gcodeoff=True,ip=plugip,idx=plugidx))
					self._tasmota_logger.debug("Received M81 command, attempting power off.")
					return
				else:
					return
			

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

def __plugin_load__():
	global __plugin_implementation__
	__plugin_implementation__ = tasmotaPlugin()

	global __plugin_hooks__
	__plugin_hooks__ = {
		"octoprint.comm.protocol.gcode.queuing": __plugin_implementation__.processGCODE,
		"octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
	}

