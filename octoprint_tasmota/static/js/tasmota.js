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
		self.refreshVisible = ko.observable(true);
		self.automaticShutdownEnabled = ko.observable(false);
		self.filteredSmartplugs = ko.computed(function(){
			return ko.utils.arrayFilter(self.arrSmartplugs(), function(item) {
						return item.automaticShutdownEnabled() == true;
					});
		});

		self.show_sidebar = ko.computed(function(){
			return self.filteredSmartplugs().length > 0;
		});

		self.toggleShutdownTitle = ko.pureComputed(function() {
			return self.automaticShutdownEnabled() ? 'Disable Automatic Power Off' : 'Enable Automatic Power Off';
		})

		// Hack to remove automatically added Cancel button
		// See https://github.com/sciactive/pnotify/issues/141
		PNotify.prototype.options.confirm.buttons = [];
		self.timeoutPopupText = gettext('Powering off in ');
		self.timeoutPopupOptions = {
			title: gettext('Automatic Power Off'),
			type: 'notice',
			icon: true,
			hide: false,
			confirm: {
				confirm: true,
				buttons: [{
					text: 'Cancel Power Off',
					addClass: 'btn-block btn-danger',
					promptTrigger: true,
					click: function(notice, value){
						notice.remove();
						notice.get().trigger("pnotify.cancel", [notice, value]);
					}
				}]
			},
			buttons: {
				closer: false,
				sticker: false,
			},
			history: {
				history: false
			}
		};

		self.onAutomaticShutdownEvent = function() {
			if (self.automaticShutdownEnabled()) {
				$.ajax({
					url: API_BASEURL + "plugin/tasmota",
					type: "POST",
					dataType: "json",
					data: JSON.stringify({
						command: "enableAutomaticShutdown"
					}),
					contentType: "application/json; charset=UTF-8"
				})
			} else {
				$.ajax({
					url: API_BASEURL + "plugin/tasmota",
					type: "POST",
					dataType: "json",
					data: JSON.stringify({
						command: "disableAutomaticShutdown"
					}),
					contentType: "application/json; charset=UTF-8"
				})
			}
		}

		self.automaticShutdownEnabled.subscribe(self.onAutomaticShutdownEvent, self);

		self.onToggleAutomaticShutdown = function(data) {
			if (self.automaticShutdownEnabled()) {
				self.automaticShutdownEnabled(false);
			} else {
				self.automaticShutdownEnabled(true);
			}
		}

		self.abortShutdown = function(abortShutdownValue) {
			self.timeoutPopup.remove();
			self.timeoutPopup = undefined;
			$.ajax({
				url: API_BASEURL + "plugin/tasmota",
				type: "POST",
				dataType: "json",
				data: JSON.stringify({
					command: "abortAutomaticShutdown"
				}),
				contentType: "application/json; charset=UTF-8"
			})
		}

		self.graph_start_date = ko.observable(moment().subtract(1, 'days').format('YYYY-MM-DDTHH:mm'));
		self.graph_end_date = ko.observable(moment().format('YYYY-MM-DDTHH:mm'));

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

		self.plotEnergyData = function(){
			$.ajax({
			url: API_BASEURL + "plugin/tasmota",
			type: "POST",
			dataType: "json",
			data: JSON.stringify({
				command: "getEnergyData",
				start_date: self.graph_start_date(),
				end_date: self.graph_end_date()
			}),
			contentType: "application/json; charset=UTF-8"
			}).done(function(data){					
					console.log(data);
					//update plotly graph here.
					var energy_labels = [0,0,'Current','Power','Total'];
					var sensor_labels = [0,0,'Temperature','Humidity'];
					var traces = [];
					for(var i=0;i<data.energy_data.length;i++){
						for(var j=2;j<data.energy_data[i].length;j++){
							var trace = {mode: 'lines'};
							trace['name'] = data.energy_data[i][0] + ' ' + energy_labels[j];
							trace['x'] = data.energy_data[i][1].split(',');
							trace['y'] = data.energy_data[i][j].split(',');
							traces.push(trace);
						}
					}
					for(var i=0;i<data.sensor_data.length;i++){
						for(var j=2;j<data.sensor_data[i].length;j++){
							var trace = {mode: 'lines'};
							trace['name'] = data.sensor_data[i][0] + ' ' + sensor_labels[j];
							trace['x'] = data.sensor_data[i][1].split(',');
							trace['y'] = data.sensor_data[i][j].split(',');
							traces.push(trace);
						}
					}

					var layout = {
						autosize: true,
						showlegend: false,
						/* legend: {"orientation": "h"}, */
						xaxis: { type:"date", /* tickformat:"%H:%M:%S", */ automargin: true, title: {standoff: 0},linecolor: 'black', linewidth: 2, mirror: true},
						yaxis: { type:"linear", automargin: true, title: {standoff: 0},linecolor: 'black', linewidth: 2, mirror: true },
						margin: {l:35,r:30,b:0,t:20,pad:5}
					}

					var options = {
						showLink: false,
						sendData: false,
						displaylogo: false,
						displayModeBar: false,
						editable: false,
						showTips: false
					}

					Plotly.react('tasmota_graph', traces, layout, options);
				});
		}

		self.legend_visible = ko.observable(false);
		
		self.toggle_legend = function(){
			self.legend_visible(self.legend_visible() ? false : true);
			Plotly.relayout('tasmota_graph',{showlegend: self.legend_visible()});
		}

		self.onTabChange = function(current, previous) {
			if (current === "#tab_plugin_tasmota") {
				self.plotEnergyData();
			}
		}

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
							   'thermal_runaway':ko.observable(false),
							  'automaticShutdownEnabled':ko.observable(false)});
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

			if(data.hasOwnProperty("automaticShutdownEnabled")) {
				self.automaticShutdownEnabled(data.automaticShutdownEnabled);

				if (data.type == "timeout") {
					if ((data.timeout_value != null) && (data.timeout_value > 0)) {
						self.timeoutPopupOptions.text = self.timeoutPopupText + data.timeout_value;
						if (typeof self.timeoutPopup != "undefined") {
							self.timeoutPopup.update(self.timeoutPopupOptions);
						} else {
							self.timeoutPopup = new PNotify(self.timeoutPopupOptions);
							self.timeoutPopup.get().on('pnotify.cancel', function() {self.abortShutdown(true);});
						}
					} else {
						if (typeof self.timeoutPopup != "undefined") {
							self.timeoutPopup.remove();
							self.timeoutPopup = undefined;
						}
					}
				}
				return;
			} else {
				console.log(data);
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
			}
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
			self.sendTurnOn(data);
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
				self.sendTurnOff(data);
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

		self.checkSetOption26 = function(data, evt) {
			evt.currentTarget.blur();
			$.ajax({
				url: API_BASEURL + "plugin/tasmota",
				type: "POST",
				dataType: "json",
				data: JSON.stringify({
					command: "checkSetOption26",
					ip: data.ip(),
					username: data.username(),
					password: data.password()
				}),
				contentType: "application/json; charset=UTF-8"
			}).done(function(response){
				if(response["SetOption26"] == "OFF"){
					var test = confirm("SetOption26 needs to be updated to ON for proper operation. Would you like to set that option now?");
					if (test) {
						$.ajax({
							url: API_BASEURL + "plugin/tasmota",
							type: "POST",
							dataType: "json",
							data: JSON.stringify({
								command: "setSetOption26",
								ip: data.ip(),
								username: data.username(),
								password: data.password()
							}),
							contentType: "application/json; charset=UTF-8"
						}).done(function(response){
							if(response["SetOption26"] == "ON"){
								alert("SetOption26 updated to ON for proper operation.");
								self.checkStatuses();
							}
						});
					}
				} else {
					alert("Tasmota device responded and is configured properly.");
				}
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
					idx: data.idx()
				}),
				contentType: "application/json; charset=UTF-8"
			}).done(function(){
				self.settings.saveData();
				});
		}; 

		self.checkStatuses = function() {
			ko.utils.arrayForEach(self.settings.settings.plugins.tasmota.arrSmartplugs(),function(item){
				if(item.ip() !== "") {
					if(self.settings.settings.plugins.tasmota.debug_logging()){
						console.log("checking " + item.ip() + " index " + item.idx());
					}
					self.checkStatus(item);
				}
			});

			// Moved to server side python
/* 			if (self.settings.settings.plugins.tasmota.polling_enabled() && parseInt(self.settings.settings.plugins.tasmota.polling_interval(),10) > 0) {
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
			}; */
		};
	}

	// view model class, parameters for constructor, container to bind to
	OCTOPRINT_VIEWMODELS.push([
		tasmotaViewModel,
		["settingsViewModel","loginStateViewModel"],
		["#navbar_plugin_tasmota","#settings_plugin_tasmota","#tab_plugin_tasmota","#sidebar_plugin_tasmota_wrapper"]
	]);
});
