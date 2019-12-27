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
		self.gcodeOnString = function(data){return 'M80 '+data.ip()+' '+data.idx();};
		self.gcodeOffString = function(data){return 'M81 '+data.ip()+' '+data.idx();};
		self.selectedPlug = ko.observable();
		self.processing = ko.observableArray([]);
		self.get_color = function(data){
							console.log(data);
							switch(data.currentState()) {
								case "on":
									return data.on_color();
									break;
								case "off":
									return data.off_color();
									break;
								default:
									return data.unknown_color();
							}
						};

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

		self.onTabChange = function(current, previous) {
			if (current === "#tab_plugin_tasmota") {
				$.ajax({
				url: API_BASEURL + "plugin/tasmota",
				type: "POST",
				dataType: "json",
				data: JSON.stringify({
					command: "getEnergyData"
				}),
				contentType: "application/json; charset=UTF-8"
				}).done(function(data){
						//update plotly graph here.
/* 						var energy_trace_total = data['energy_data'].map(function(item){return item;});
						var energy_trace_current = data['energy_data'].map(function(item){return item;});
						var energy_trace_power = data['energy_data'].map(function(item){return item;});
						var layout_energy = {title:'Tasmota Energy Data',
									grid: {rows: 2, columns: 1, pattern: 'independent'},
									xaxis: {
										showticklabels: false,
										anchor: 'x'
									},
									yaxis: {
										title: 'Total (kWh)',
										hoverformat: '.3f kWh',
										tickangle: 45,
										tickfont: {
											size: 10
										},
										tickformat: '.2f',
										anchor: 'y'
									},
									xaxis2: {
										anchor: 'y2'
									},
									yaxis2: {
										title: 'Current (Amp)',
										hoverformat: '.3f',
										anchor: 'x2',
										tickangle: 45,
										tickfont: {
											size: 10
										},
										tickformat: '.2f'
									},
									xaxis3: {
										overlaying: 'x2',
										anchor: 'y3',
										showticklabels: false
									},
									yaxis3: {
										overlaying: 'y2',
										side: 'right',
										title: 'Power (W)',
										hoverformat: '.3f',
										anchor: 'x3',
										tickangle: -45,
										tickfont: {
											size: 10
										},
										tickformat: '.2f'
									}
								};

						var energy_plot_data = [energy_trace_total,energy_trace_current,energy_trace_power]
						var sensor_plot_data = []
						Plotly.react('tasmota_energy_graph',energy_plot_data,layout_energy);
						Plotly.react('tasmota_sensor_graph',sensor_plot_data,layout_energy); */
						var remapped_energy_data = data.energy_data.map(function(item, idx, arr){
															var new_item = {};
															new_item['name'] = item[0];
															new_item['x'] = item[1].split(',').slice(-100);
															new_item['y'] = item[2].split(',').slice(-100);
															new_item['y2'] = item[3].split(',').slice(-100);
															new_item['y3'] = item[4].split(',').slice(-100); 
															new_item['mode'] = 'lines';
															return new_item;
														});
						Plotly.react('tasmota_energy_graph', remapped_energy_data);
						console.log(remapped_energy_data);
						
					});
				}
			};

		self.addPlug = function() {
			self.selectedPlug({'ip':ko.observable(''),
							   'idx':ko.observable('1'),
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
							   'username':ko.observable('admin'),
							   'password':ko.observable(''),
							   'icon':ko.observable('icon-bolt'),
							   'label':ko.observable(''),
							   'label_extended':ko.observable(''),
							   'on_color':ko.observable('#00FF00'),
							   'off_color':ko.observable('#FF0000'),
							   'sensor_identifier':ko.observable(''),
							   'unknown_color':ko.observable('#808080'),
							   'use_backlog':ko.observable(false),
							   'backlog_on_delay':ko.observable(0),
							   'backlog_off_delay':ko.observable(0),
							   'thermal_runaway':ko.observable(false)});
			self.settings.settings.plugins.tasmota.arrSmartplugs.push(self.selectedPlug());
			$("#TasmotaEditor").modal("show");
		}

		self.editPlug = function(data) {
			self.selectedPlug(data);
			$("#TasmotaEditor").modal("show");
		}

		self.removePlug = function(row) {
			self.settings.settings.plugins.tasmota.arrSmartplugs.remove(row);
		}

		self.cancelClick = function(data) {
			self.processing.remove(data.ip());
		}

		self.onDataUpdaterPluginMessage = function(plugin, data) {
			if (plugin != "tasmota") {
				return;
			}
			console.log('msg received:'+JSON.stringify(data));

			plug = ko.utils.arrayFirst(self.settings.settings.plugins.tasmota.arrSmartplugs(),function(item){
				return ((item.ip().toUpperCase() == data.ip.toUpperCase()) && (item.idx() == data.idx));
				}) || {'ip':data.ip,'idx':data.idx,'currentState':'unknown','gcodeEnabled':false};
			
			if(self.settings.settings.plugins.tasmota.debug_logging()){
				console.log(self.settings.settings.plugins.tasmota.arrSmartplugs());
				console.log('msg received:'+JSON.stringify(data));
				console.log('plug data:'+ko.toJSON(plug));
			}

			var tooltip = plug.label();
			if(data.sensor_data) {
				for(k in data.sensor_data) {
					tooltip += '<br>' + k + ': ' + data.sensor_data[k]
				}
			}
			if(data.energy_data) {
				for(k in data.energy_data) {
					tooltip += '<br>' + k + ': ' + data.energy_data[k]
				}
			}
			plug.label_extended = ko.observable(tooltip);

			if (plug.currentState != data.currentState) {
				plug.currentState(data.currentState)
				switch(data.currentState) {
					case "on":
						break;
					case "off":
						break;
					default:
						new PNotify({
							title: 'Tasmota Error',
							text: 'Status ' + plug.currentState() + ' for ' + plug.ip() + '. Double check IP Address\\Hostname in Tasmota Settings.',
							type: 'error',
							hide: true
							});
				}				
				self.settings.saveData();
			}
			self.processing.remove(data.ip);
		};

		self.toggleRelay = function(data) {
			self.processing.push(data.ip());
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
					password: data.password(),
					backlog_delay: data.backlog_on_delay()
				}),
				contentType: "application/json; charset=UTF-8"
			});
		};

		self.turnOff = function(data) {
			if((data.displayWarning() || (self.isPrinting() && data.warnPrinting())) && !$("#TasmotaWarning").is(':visible')){
				self.selectedPlug(data);
				$("#TasmotaWarning").modal("show");
			} else {
				$("#TasmotaWarning").modal("hide");
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
					password: data.password(),
					backlog_delay: data.backlog_off_delay()
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
			if (self.settings.settings.plugins.tasmota.polling_enabled() && parseInt(self.settings.settings.plugins.tasmota.polling_interval(),10) > 0) {
				if(self.settings.settings.plugins.tasmota.debug_logging()){
					console.log('Polling enabled, checking status again in ' + (parseInt(self.settings.settings.plugins.tasmota.polling_interval(),10) * 60000) + '.');
				}
				if(typeof self.polling_timer !== "undefined") {
					if(self.settings.settings.plugins.tasmota.debug_logging()){
						console.log('Clearing polling timer.');
					}
					clearTimeout(self.polling_timer);
				}
				self.polling_timer = setTimeout(function() {self.checkStatuses();}, (parseInt(self.settings.settings.plugins.tasmota.polling_interval(),10) * 60000));
			};
		};
	}

	// view model class, parameters for constructor, container to bind to
	OCTOPRINT_VIEWMODELS.push([
		tasmotaViewModel,
		["settingsViewModel","loginStateViewModel"],
		["#navbar_plugin_tasmota","#settings_plugin_tasmota"]
	]);
});
