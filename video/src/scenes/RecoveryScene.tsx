import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import {COLORS} from '../theme';
import BackgroundPattern from '../components/BackgroundPattern';
import Packet from '../components/Packet';
import ControlNode from '../components/ControlNode';
import StatusBadge from '../components/StatusBadge';

export const RecoveryScene: React.FC<{text:string[]}> = ({text}) => {
  const frame = useCurrentFrame();
  const pulse = Math.abs(Math.sin(frame/6)) * 0.15 + 0.95;
  return (
    <BackgroundPattern>
      <AbsoluteFill style={{display:'flex', alignItems:'center', justifyContent:'center'}}>
        <div style={{display:'flex', gap:48, alignItems:'center'}}>
          <svg width={300} height={200} viewBox="0 0 300 200">
            <g transform="translate(60,60)">
              <ControlNode x={0} y={0} state={'recovered'} />
              <g transform={`translate(60,0)`}> 
                <Packet color={'#2fe2c6'} scale={pulse} />
              </g>
            </g>
          </svg>

          <div>
            <h2 style={{fontSize:48}}>{text?.[0]}</h2>
            <p style={{fontSize:26, color:COLORS.muted}}>{text?.[1]}</p>
            <div style={{marginTop:18}}>
              <StatusBadge text={'Fresh measurement received'} tone={'ok'} />
            </div>
          </div>
        </div>
      </AbsoluteFill>
    </BackgroundPattern>
  );
};

export default RecoveryScene;
