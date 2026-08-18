import React from 'react';
import {AbsoluteFill} from 'remotion';
import {COLORS} from '../theme';
import BackgroundPattern from '../components/BackgroundPattern';
import Boiler from '../components/Boiler';
import ControlNode from '../components/ControlNode';
import StatusBadge from '../components/StatusBadge';

export const SafeFallbackScene: React.FC<{text:string[]}> = ({text}) => {
  return (
    <BackgroundPattern>
      <AbsoluteFill style={{display:'flex', alignItems:'center', justifyContent:'center'}}>
        <div style={{display:'flex', gap:60, alignItems:'center'}}>
          <div style={{width:360}}>
            <svg width={360} height={220} viewBox="0 0 360 220">
              <g transform="translate(40,40)">
                <Boiler x={0} y={0} active={false} />
                <g transform="translate(180,30)">
                  <ControlNode x={0} y={0} state={'fallback'} />
                </g>
              </g>
            </svg>
          </div>

          <div style={{maxWidth:760}}>
            <h2 style={{fontSize:48}}>{text?.[0]}</h2>
            <p style={{fontSize:26, color:COLORS.muted, marginTop:8}}>{text?.[1]}</p>
            <div style={{marginTop:18}}>
              <StatusBadge text={'Safe fallback requested'} tone={'warn'} />
            </div>
          </div>
        </div>
      </AbsoluteFill>
    </BackgroundPattern>
  );
};

export default SafeFallbackScene;
