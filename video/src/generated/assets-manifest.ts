import living_room from './assets/edu/v1/environments/room.svg';
import thermometer from './assets/edu/v1/devices/thermometer.svg';
import radiator from './assets/edu/v1/devices/radiator.svg';
import controlel_core from './assets/edu/v1/devices/controlel_core.svg';
import packet from './assets/edu/v1/effects/packet.svg';
import timer from './assets/edu/v1/icons/timer.svg';

export const assets = {
  "living_room": { file: living_room, type: "environment", format: "svg", supported_states: [] },
  "thermometer": { file: thermometer, type: "device", format: "svg", supported_states: ["normal","stale","offline","recovered"] },
  "radiator": { file: radiator, type: "device", format: "svg", supported_states: ["idle","heating_low","heating_high","blocked"] },
  "controlel_core": { file: controlel_core, type: "device", format: "svg", supported_states: ["normal","evaluating","waiting","protection","error"] },
  "packet": { file: packet, type: "effect", format: "svg", supported_states: [] },
  "timer": { file: timer, type: "icon", format: "svg", supported_states: [] },
};