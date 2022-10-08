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
		self.filesViewModel = parameters[2];

		self.arrSmartplugs = ko.observableArray();
		self.arrSmartplugsTooltips = ko.observableDictionary({});
		self.arrSmartplugsStates = ko.observableDictionary({});
		self.arrSmartplugsLEDColors = ko.observableDictionary({});
		self.isPrinting = ko.observable(false);
		self.gcodeOnString = function(data){return 'M80 '+data.ip()+' '+data.idx();};
		self.gcodeOffString = function(data){return 'M81 '+data.ip()+' '+data.idx();};
		self.selectedPlug = ko.observable();
		self.processing = ko.observableArray([]);
		self.get_color = function(data){
							switch(self.arrSmartplugsStates.get(data.ip()+'_'+data.idx())()) {
								case "on":
									return self.arrSmartplugsLEDColors.get(data.ip()+'_'+data.idx())() ? self.arrSmartplugsLEDColors.get(data.ip()+'_'+data.idx())() : data.on_color();
								case "off":
									return self.arrSmartplugsLEDColors.get(data.ip()+'_'+data.idx())() ? data.unknown_color() : data.off_color();
								default:
									return data.unknown_color();
							}
						};
		self.refreshVisible = ko.observable(true);
		self.automaticShutdownEnabled = ko.observable(false);
		self.filteredSmartplugs = ko.pureComputed(function(){
			return ko.utils.arrayFilter(self.arrSmartplugs(), function(item) {
						return item.automaticShutdownEnabled() == true;
					});
		});

		self.show_sidebar = ko.pureComputed(function(){
			return self.filteredSmartplugs().length > 0;
		});

		self.toggleShutdownTitle = ko.pureComputed(function() {
			return self.automaticShutdownEnabled() ? 'Disable Automatic Power Off' : 'Enable Automatic Power Off';
		});

        self.filesViewModel.getAdditionalData = function(data) {
			var output = "";
			if (data["gcodeAnalysis"]) {
				if (data["gcodeAnalysis"]["dimensions"]) {
					var dimensions = data["gcodeAnalysis"]["dimensions"];
					output += gettext("Model size") + ": " + _.sprintf("%(width).2fmm &times; %(depth).2fmm &times; %(height).2fmm", dimensions);
					output += "<br>";
				}
				if (data["gcodeAnalysis"]["filament"] && typeof(data["gcodeAnalysis"]["filament"]) === "object") {
					var filament = data["gcodeAnalysis"]["filament"];
					if (_.keys(filament).length === 1) {
						output += gettext("Filament") + ": " + formatFilament(data["gcodeAnalysis"]["filament"]["tool" + 0]) + "<br>";
					} else if (_.keys(filament).length > 1) {
						_.each(filament, function(f, k) {
							if (!_.startsWith(k, "tool") || !f || !f.hasOwnProperty("length") || f["length"] <= 0) return;
							output += gettext("Filament") + " (" + gettext("Tool") + " " + k.substr("tool".length)
								+ "): " + formatFilament(f) + "<br>";
						});
					}
				}
				output += gettext("Estimated print time") + ": " + (self.settings.appearance_fuzzyTimes() ? formatFuzzyPrintTime(data["gcodeAnalysis"]["estimatedPrintTime"]) : formatDuration(data["gcodeAnalysis"]["estimatedPrintTime"])) + "<br>";
			}
			if (data["prints"] && data["prints"]["last"]) {
				output += gettext("Last printed") + ": " + formatTimeAgo(data["prints"]["last"]["date"]) + "<br>";
				if (data["prints"]["last"]["printTime"]) {
					output += gettext("Last print time") + ": " + formatDuration(data["prints"]["last"]["printTime"]) + "<br>";
				}
			}
			if (data["statistics"] && data["statistics"]["lastPowerCost"]) {
				output += gettext("Last power cost") + ": " + data["statistics"]["lastPowerCost"]["_default"] + "<br>";
			}
			return output;
		};

		// Hack to remove automatically added Cancel button
		// See https://github.com/sciactive/pnotify/issues/141
		PNotify.prototype.options.confirm.buttons = [];
		self.timeoutPopupText = '';
		self.timeoutPopupOptions = {
			title: '',
			type: 'notice',
			icon: false,
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
				});
			} else {
				$.ajax({
					url: API_BASEURL + "plugin/tasmota",
					type: "POST",
					dataType: "json",
					data: JSON.stringify({
						command: "disableAutomaticShutdown"
					}),
					contentType: "application/json; charset=UTF-8"
				});
			}
		};

		self.automaticShutdownEnabled.subscribe(self.onAutomaticShutdownEvent, self);

		self.onToggleAutomaticShutdown = function(data) {
			if (self.automaticShutdownEnabled()) {
				self.automaticShutdownEnabled(false);
			} else {
				self.automaticShutdownEnabled(true);
			}
		};

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
			});
		};

		self.graph_start_date = ko.observable(moment().subtract(1, 'days').format('YYYY-MM-DDTHH:mm'));
		self.graph_end_date = ko.observable(moment().format('YYYY-MM-DDTHH:mm'));

		self.onBeforeBinding = function() {
			self.arrSmartplugs(self.settings.settings.plugins.tasmota.arrSmartplugs());
            if($('html').attr('id') === 'touch') {
                // $('#sidebar_plugin_tasmota_wrapper > div.accordion-heading > div').appendTo('#sidebar_plugin_tasmota');

            }
		};

		self.onAllBound = function() {
			self.checkStatuses();
		};

		self.onEventSettingsUpdated = function(payload) {
			self.settings.requestData();
			self.arrSmartplugs(self.settings.settings.plugins.tasmota.arrSmartplugs());
		};

		self.onEventPrinterStateChanged = function(payload) {
			if (payload.state_id == "PRINTING" || payload.state_id == "PAUSED"){
				self.isPrinting(true);
			} else {
				self.isPrinting(false);
			}
		};

		self.plotEnergyData = function(){
			$.ajax({
			url: API_BASEURL + "plugin/tasmota",
			type: "POST",
			dataType: "json",
			data: JSON.stringify({
				command: "getEnergyData",
				start_date: self.graph_start_date().replace('T', ' '),
				end_date: self.graph_end_date().replace('T', ' ')
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
							var trace_cost = {x:[],y:[],mode:'lines',name:data.energy_data[i][0] + ' Cost'};
							trace['name'] = data.energy_data[i][0] + ' ' + energy_labels[j];
							trace['x'] = data.energy_data[i][1].split(',');
							trace['y'] = data.energy_data[i][j].split(',');
							traces.push(trace);
							if(j == 4){
							    trace_cost['x'] = data.energy_data[i][1].split(',');
							    var trace_cost_y = data.energy_data[i][j].split(',');
							    for(var k=0;k<trace_cost_y.length;k++){
							        trace_cost['y'].push((parseFloat(trace_cost_y[k]) * parseFloat(self.settings.settings.plugins.tasmota.cost_rate())));
                                }
							    traces.push(trace_cost);
                            }
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

                    var background_color = ($('.tab-content').css('background-color') == 'rgba(0, 0, 0, 0)') ? '#FFFFFF' : $('.tab-content').css('background-color');
                    var foreground_color = ($('.tab-content').css('color') == 'rgba(0, 0, 0, 0)') ? '#FFFFFF' : $('#tabs_content').css('color');

					var layout = {
						autosize: true,
						showlegend: false,
						/* legend: {"orientation": "h"}, */
						xaxis: { type:"date", /* tickformat:"%H:%M:%S", */ automargin: true, title: {standoff: 0},linecolor: 'black', linewidth: 2, mirror: true},
						yaxis: { type:"linear", automargin: true, title: {standoff: 0},linecolor: 'black', linewidth: 2, mirror: true },
						margin: {l:35,r:30,b:0,t:20,pad:5},
                        plot_bgcolor: background_color,
                        paper_bgcolor: background_color,
                        font: {color: foreground_color}
					};

					var options = {
						showLink: false,
						sendData: false,
						displaylogo: false,
						displayModeBar: false,
						editable: false,
						showTips: false
					};

					Plotly.react('tasmota_graph', traces, layout, options);
				});
		};

		self.legend_visible = ko.observable(false);

		self.toggle_legend = function(){
			self.legend_visible(self.legend_visible() ? false : true);
			Plotly.relayout('tasmota_graph',{showlegend: self.legend_visible()});
		};

		self.onTabChange = function(current, previous) {
			if (current === "#tab_plugin_tasmota") {
				self.plotEnergyData();
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
							   'thermal_runaway':ko.observable(false),
							   'automaticShutdownEnabled':ko.observable(false),
							   'event_on_error':ko.observable(false),
							   'event_on_disconnect':ko.observable(false),
							   'event_on_upload':ko.observable(false),
							   'event_on_connecting':ko.observable(false),
							   'is_led':ko.observable(false),
							   'is_sensor_only': ko.observable(false),
                               'brightness':ko.observable(50)});
			self.settings.settings.plugins.tasmota.arrSmartplugs.push(self.selectedPlug());
			$("#TasmotaEditor").modal("show");
		};

		self.editPlug = function(data) {
			self.selectedPlug(data);
			$("#TasmotaEditor").modal("show");
		};

		self.removePlug = function(row) {
			self.settings.settings.plugins.tasmota.arrSmartplugs.remove(row);
		};

		self.cancelClick = function(data) {
			self.processing.remove(data.ip());
		};

		self.onDataUpdaterPluginMessage = function(plugin, data) {
			if (plugin != "tasmota" || !data) {
				return;
			}

			if(data.hasOwnProperty("thermal_runaway")){
			    let message = "Thermal runaway was triggered "
                switch (data.type){
                    case "connection":
                        message += "previously.";
                        break
                    case "bed":
                        message += "from the bed.";
                        break
                    case "extruder":
                        message += "from the extruder.";
                        break
                    default:
                        message = "Unknown thermal_runaway type.";
			    }

			    if (self.thermal_runaway_notice !== undefined) {
                    self.thermal_runaway_notice.update({text: message});
                    self.thermal_runaway_notice.open();
                } else {
                    self.thermal_runaway_notice = new PNotify({
                        title: "Tasmota Error",
                        type: "error",
                        text: message,
                        hide: false
                    });
                }
			    return;
            }

			if(data.hasOwnProperty("powerOffWhenIdle")) {
				self.settings.settings.plugins.tasmota.powerOffWhenIdle(data.powerOffWhenIdle);

				if (data.type == "timeout") {
					if ((data.timeout_value != null) && (data.timeout_value > 0) && (typeof(ko.utils.arrayFirst(self.arrSmartplugsStates.items(), function(item){return item.value() == 'on'})) !== 'undefined')) {
						var progress_percent = Math.floor((data.timeout_value/self.settings.settings.plugins.tasmota.abortTimeout())*100)
						var progress_class = (progress_percent<25)?'progress-danger':(progress_percent>75)?'progress-success':'progress-warning';
						self.timeoutPopupOptions.text = '<div class="progress progress-tasmota '+progress_class+'"><div class="bar">'+gettext('Powering Off in ')+' '+data.timeout_value+' '+gettext('secs')+'</div><div class="progress-text" style="clip-path: inset(0 0 0 '+progress_percent+'%);-webkit-clip-path: inset(0 0 0 '+progress_percent+'%);">'+gettext('Powering Off in ')+' '+data.timeout_value+' '+gettext('secs')+'</div></div>';
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
			} else {
				plug = ko.utils.arrayFirst(self.settings.settings.plugins.tasmota.arrSmartplugs(),function(item){
					return ((item.ip().toUpperCase() == data.ip.toUpperCase()) && (item.idx() == data.idx));
					}) || {'ip':data.ip,'idx':data.idx,'currentState':'unknown','gcodeEnabled':false};

				if(self.settings.settings.plugins.tasmota.debug_logging()){
					console.log(self.settings.settings.plugins.tasmota.arrSmartplugs());
					console.log('msg received:'+JSON.stringify(data));
					console.log('plug data:'+ko.toJSON(plug));
				}


				var tooltip = '';
				if (data.sensor_data || data.energy_data) {
					tooltip += '<table style="width: 100%"><thead></thead><tbody>';
					if(data.sensor_data) {
						for(let k in data.sensor_data) {
							tooltip += '<tr><td>' + k + ':</td><td>' + data.sensor_data[k] + '</td></tr>';
						}
					}
					if(data.energy_data) {
						for(let k in data.energy_data) {
							tooltip += '<tr><td>' + k + ':</td><td>' + data.energy_data[k] + '</td></tr>';
						}
					}
					tooltip += '</tbody></table>';
					$(('#tasmota_button_link_'+data.ip+'_'+data.idx).replace(/[.:]/g,'_')).removeClass('hide_popover_content');
				} else {
					$(('#tasmota_button_link_'+data.ip+'_'+data.idx).replace(/[.:]/g,'_')).addClass('hide_popover_content');
				}
                try {
                    self.arrSmartplugsTooltips.set(data.ip+'_'+data.idx, tooltip);
                } catch (error) {
				    self.processing.remove(data.ip);
				    console.log('tooltip', error);
                }
				try {
                    self.arrSmartplugsStates.set(data.ip + '_' + data.idx, data.currentState);
                } catch (error) {
				    self.processing.remove(data.ip);
				    console.log('currentState', error);
                }
				if (["on", "off"].indexOf(data.currentState) === -1) {
                    new PNotify({
                        title: 'Tasmota Error',
                        text: 'Status ' + plug.currentState() + ' for ' + plug.ip() + '. Double check IP Address\\Hostname in Tasmota Settings.',
                        type: 'error',
                        hide: true
                        });
				}
				if(data.color){
				    var color = (data.color.LEDBrightness > 0) ? 'RGB(' + data.color.LEDRed + ',' + data.color.LEDGreen + ',' + data.color.LEDBlue + ')' : plug["unknown_color"];
				    self.arrSmartplugsLEDColors.set(data.ip + '_' + data.idx, color);
                }
				self.processing.remove(data.ip);
			}
		};

		self.toggleRelay = function(data) {
            if(data.is_sensor_only()){
                return
            }
			self.processing.push(data.ip());
			switch(self.arrSmartplugsStates.get(data.ip()+'_'+data.idx())()){
				case "on":
					self.turnOff(data);
					break;
				case "off":
					self.turnOn(data);
					break;
				default:
					self.checkStatus(data);
			}
		};

		self.turnOn = function(data) {
			self.sendTurnOn(data);
		};

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
			}).done(function(data){
			    console.log('on', data);
			    self.onDataUpdaterPluginMessage('tasmota', data);
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
			}).done(function(data){
			    console.log('off', data);
			    self.onDataUpdaterPluginMessage('tasmota', data);
            });
		};

		self.checkSetOption26 = function(data, evt) {
			evt.currentTarget.blur();
			$.ajax({
				url: API_BASEURL + "plugin/tasmota",
				type: "POST",
				dataType: "json",
				data: JSON.stringify({
					command: "checkSetOption26",
					ip: data.ip(),
                    idx: data.idx(),
					username: data.username(),
					password: data.password()
				}),
				contentType: "application/json; charset=UTF-8"
			}).done(function(response){
				if(response["SetOption26"] == "OFF" && data.idx() !== '') {
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
		};

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
		};
	}

	// view model class, parameters for constructor, container to bind to
	OCTOPRINT_VIEWMODELS.push([
		tasmotaViewModel,
		["settingsViewModel","loginStateViewModel","filesViewModel"],
		["#navbar_plugin_tasmota","#settings_plugin_tasmota","#tab_plugin_tasmota","#sidebar_plugin_tasmota_wrapper"]
	]);
});
