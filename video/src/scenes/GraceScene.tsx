import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import {COLORS} from '../theme';
import BackgroundPattern from '../components/BackgroundPattern';
import ControlNode from '../components/ControlNode';
import Countdown from '../components/Countdown';

export const GraceScene: React.FC<{text:string[], fps:number}> = ({text, fps=30}) => {
  const frame = useCurrentFrame();
  const totalFrames = fps * 12; // example protected duration
  return (
    <BackgroundPattern>
      <AbsoluteFill style={{display:'flex', alignItems:'center', justifyContent:'center'}}>
        <div style={{display:'flex', gap:40, alignItems:'center'}}>
          <div style={{width:220, height:220}}>
            <svg width={220} height={220} viewBox="-120 -120 240 240">
              <g>
                <ControlNode x={0} y={0} state={'waiting'} />
              </g>
            </svg>
          </div>
          <div style={{maxWidth:760}}>
            <h2 style={{fontSize:48}}>{text?.[0]}</h2>
            <p style={{fontSize:26, color:COLORS.muted}}>{text?.[1]}</p>
            <div style={{marginTop:18}}>
              <Countdown durationFrames={totalFrames} label={'Protection period'} />
            </div>
          </div>
        </div>
      </AbsoluteFill>
    </BackgroundPattern>
  );
};

export default GraceScene;
