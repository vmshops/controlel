import React from 'react';
import {AbsoluteFill, useCurrentFrame, interpolate} from 'remotion';
import {COLORS} from '../theme';
import BackgroundPattern from '../components/BackgroundPattern';
import RoomIllustration from '../components/RoomIllustration';
import Thermometer from '../components/Thermometer';
import Radiator from '../components/Radiator';
import ControlNode from '../components/ControlNode';
import Packet from '../components/Packet';
import StatusBadge from '../components/StatusBadge';

export const SensorScene: React.FC<{def:any, fps:number}> = ({def, fps=30}) => {
  const frame = useCurrentFrame();
  const t = frame / fps;
  const minutes = def.last_update_from_minutes + (def.last_update_to_minutes - def.last_update_from_minutes) * Math.min(1, t / (def.duration || 10));
  const showWarning = t > (def.duration || 8);
  const pulse = !showWarning && (Math.floor(frame/8)%2===0);

  // packet animation along simple path
  const packetX = interpolate(frame, [0, fps*2, fps*4], [520, 360, 220], {extrapolateRight:'clamp'});

  return (
    <BackgroundPattern>
      <AbsoluteFill style={{display:'flex', alignItems:'center', justifyContent:'center'}}>
        <div style={{display:'flex', flexDirection:'row', alignItems:'center', gap:40}}>
          <RoomIllustration>
            <g transform="translate(10,40)">
              <Thermometer x={0} y={10} value={def.start_value ?? 21.4} warning={showWarning} pulse={pulse} />
              <Radiator x={150} y={110} active={!showWarning} />
            </g>
            <g transform="translate(0,0)">
              <ControlNode x={70} y={-30} state={showWarning? 'waiting' : 'normal'} />
              <g transform={`translate(${packetX},140)`}>
                {!showWarning && <Packet color='#00f0ff' />}
              </g>
            </g>
          </RoomIllustration>

          <div style={{width:520}}>
            <div style={{background:COLORS.panel, padding:28, borderRadius:14}}>
              <div style={{fontSize:56, color:COLORS.primary}}>{(def.start_value || 21.4).toFixed(1)} °C</div>
              <div style={{fontSize:20, color:COLORS.muted, marginTop:8}}>Last update: {Math.max(0, Math.round(minutes))} min ago</div>
              <div style={{marginTop:18}}>
                <StatusBadge text={showWarning? 'No new reading' : 'Reading fresh'} tone={showWarning? 'warn' : 'normal'} />
              </div>
              <p style={{marginTop:18, color:COLORS.muted}}>The thermometer's displayed value still looks normal, but the data freshness is decreasing.</p>
            </div>
          </div>
        </div>
      </AbsoluteFill>
    </BackgroundPattern>
  );
};

export default SensorScene;
