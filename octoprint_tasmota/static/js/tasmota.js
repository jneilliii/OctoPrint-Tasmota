/*
 * View model for OctoPrint-Tasmota
 *
 * Author: jneilliii
 * License: AGPLv3
 */
$(function() {
    function tasmotaViewModel(parameters) {
        var self = this;

        self.settings = parameters[0];
		self.loginState = parameters[1];

		self.arrSmartplugs = ko.observableArray();
		self.isPrinting = ko.observable(false);
		
		self.onBeforeBinding = function() {		
			self.arrSmartplugs(self.settings.settings.plugins.tasmota.arrSmartplugs());
        }
		
		self.onAfterBinding = function() {
			self.checkStatuses();
		}

        self.onEventSettingsUpdated = function(payload) {
			self.settings.requestData();
			self.arrSmartplugs(self.settings.settings.plugins.tasmota.arrSmartplugs());
		}
		
		self.onEventPrinterStateChanged = function(payload) {
			if (payload.state_id == "PRINTING" || payload.state_id == "PAUSED"){
				self.isPrinting(true);
			} else {
				self.isPrinting(false);
			}
		}
		
		self.addPlug = function() {
			self.settings.settings.plugins.tasmota.arrSmartplugs.push({'ip':ko.observable(''),
									'idx':ko.observable(1),
									'displayWarning':ko.observable(true),
									'warnPrinting':ko.observable(false),
									'gcodeEnabled':ko.observable(false),
									'gcodeOnDelay':ko.observable(0),
									'gcodeOffDelay':ko.observable(0),
									'autoConnect':ko.observable(true),
									'autoConnectDelay':ko.observable(10.0),
									'autoDisconnect':ko.observable(true),
									'autoDisconnectDelay':ko.observable(0),
									'sysCmdOn':ko.observable(false),
									'sysRunCmdOn':ko.observable(''),
									'sysCmdOnDelay':ko.observable(0),
									'sysCmdOff':ko.observable(false),
									'sysRunCmdOff':ko.observable(''),
									'sysCmdOffDelay':ko.observable(0),
									'currentState':ko.observable('unknown'),
									'btnColor':ko.observable('#808080'),
									'username':ko.observable('admin'),
									'password':ko.observable('')});
		}
		
		self.removePlug = function(row) {
			self.settings.settings.plugins.tasmota.arrSmartplugs.remove(row);
		}
		
		self.onDataUpdaterPluginMessage = function(plugin, data) {
            if (plugin != "tasmota") {
                return;
            }
			
			plug = ko.utils.arrayFirst(self.settings.settings.plugins.tasmota.arrSmartplugs(),function(item){
				return ((item.ip().toUpperCase() == data.ip.toUpperCase()) && (item.idx() == data.idx));
				}) || {'ip':data.ip,'idx':data.idx,'currentState':'unknown','btnColor':'#808080','gcodeEnabled':false};
            
            if(self.settings.settings.plugins.tasmota.debug_logging()){
				console.log(self.settings.settings.plugins.tasmota.arrSmartplugs());
			    console.log('msg received:'+JSON.stringify(data));
                console.log('plug data:'+ko.toJSON(plug));
			}
			
			if (data.gcodeon && plug.gcodeEnabled) {
				setTimeout(function(){self.turnOn(plug)},plug.gcodeOnDelay()*1000);
				return false;
			}
			
			if (data.gcodeoff && plug.gcodeEnabled) {
				setTimeout(function(){self.turnOff(plug)},plug.gcodeOffDelay()*1000);
				return false;
			}
			
			if (plug.currentState != data.currentState) {                
				plug.currentState(data.currentState)
				switch(data.currentState) {
					case "on":
						plug.btnColor("#00FF00");
						break;
					case "off":
						plug.btnColor("#FF0000");
						break;
					default:
						plug.btnColor("#808080");
						new PNotify({
							title: 'Tasmota Error',
							text: 'Status ' + plug.currentState() + ' for ' + plug.ip() + '. Double check IP Address\\Hostname in Tasmota Settings.',
							type: 'error',
							hide: true
							});
				}                
                self.settings.saveData();
			}
        };
		
		self.toggleRelay = function(data) {
			switch(data.currentState()){
				case "on":
					self.turnOff(data);
					break;
				case "off":
					self.turnOn(data);
					break;
				default:
					self.checkStatus(data);
			}
		}
		
		self.turnOn = function(data) {
			if(data.sysCmdOn()){
				setTimeout(function(){self.sysCommand(data.sysRunCmdOn())},data.sysCmdOnDelay()*1000);
			}
			if(data.autoConnect()){
				self.sendTurnOn(data);
				setTimeout(function(){self.connectPrinter()},data.autoConnectDelay()*1000);
			} else {
				self.sendTurnOn(data);
			}
		}
		
		self.sendTurnOn = function(data) {
            $.ajax({
                url: API_BASEURL + "plugin/tasmota",
                type: "POST",
                dataType: "json",
                data: JSON.stringify({
                    command: "turnOn",
					ip: data.ip(),
					idx: data.idx(),
					username: data.username(),
					password: data.password()
                }),
                contentType: "application/json; charset=UTF-8"
            });
        };

    	self.turnOff = function(data) {
			var dlg_id = "#tasmota_poweroff_confirmation_dialog_" + data.ip().replace( /(:|\.|[|])/g, "\\$1") + "_" + data.idx();
			if((data.displayWarning() || (self.isPrinting() && data.warnPrinting())) && !$(dlg_id).is(':visible')){
				$(dlg_id).modal("show");
			} else {
				$(dlg_id).modal("hide");
				if(data.sysCmdOff()){
					setTimeout(function(){self.sysCommand(data.sysRunCmdOff())},data.sysCmdOffDelay()*1000);
				}
				if(data.autoDisconnect()){
					self.disconnectPrinter();
					setTimeout(function(){self.sendTurnOff(data);},data.autoDisconnectDelay()*1000);
				} else {
					self.sendTurnOff(data);
				}
			}
        }; 
		
		self.sendTurnOff = function(data) {
			$.ajax({
			url: API_BASEURL + "plugin/tasmota",
			type: "POST",
			dataType: "json",
			data: JSON.stringify({
				command: "turnOff",
					ip: data.ip(),
					idx: data.idx(),
					username: data.username(),
					password: data.password()
			}),
			contentType: "application/json; charset=UTF-8"
			});		
		}
		
		self.checkStatus = function(data) {
            $.ajax({
                url: API_BASEURL + "plugin/tasmota",
                type: "POST",
                dataType: "json",
                data: JSON.stringify({
                    command: "checkStatus",
					ip: data.ip(),
					idx: data.idx(),
					username: data.username(),
					password: data.password()
                }),
                contentType: "application/json; charset=UTF-8"
            }).done(function(){
				self.settings.saveData();
				});
        }; 
		
		self.disconnectPrinter = function() {
            $.ajax({
                url: API_BASEURL + "plugin/tasmota",
                type: "POST",
                dataType: "json",
                data: JSON.stringify({
                    command: "disconnectPrinter"
                }),
                contentType: "application/json; charset=UTF-8"
            });			
		}
		
		self.connectPrinter = function() {
            $.ajax({
                url: API_BASEURL + "plugin/tasmota",
                type: "POST",
                dataType: "json",
                data: JSON.stringify({
                    command: "connectPrinter"
                }),
                contentType: "application/json; charset=UTF-8"
            });			
		}
		
		self.sysCommand = function(sysCmd) {
            $.ajax({
                url: API_BASEURL + "plugin/tasmota",
                type: "POST",
                dataType: "json",
                data: JSON.stringify({
                    command: "sysCommand",
					cmd: sysCmd
                }),
                contentType: "application/json; charset=UTF-8"
            });			
		}
		
		self.checkStatuses = function() {
			ko.utils.arrayForEach(self.settings.settings.plugins.tasmota.arrSmartplugs(),function(item){
				if(item.ip() !== "") {
					if(self.settings.settings.plugins.tasmota.debug_logging()){
						console.log("checking " + item.ip() + " index " + item.idx());
					}
					self.checkStatus(item);
				}
			});
        };
    }

    // view model class, parameters for constructor, container to bind to
    OCTOPRINT_VIEWMODELS.push([
        tasmotaViewModel,

        // e.g. loginStateViewModel, settingsViewModel, ...
        ["settingsViewModel","loginStateViewModel"],

        // "#navbar_plugin_tasmota","#settings_plugin_tasmota"
        ["#navbar_plugin_tasmota","#settings_plugin_tasmota"]
    ]);
});
