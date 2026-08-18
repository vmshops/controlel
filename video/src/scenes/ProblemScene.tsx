import React from 'react';
import {AbsoluteFill, useCurrentFrame, spring} from 'remotion';
import {COLORS} from '../theme';

export const ProblemScene: React.FC<{text:string[]}> = ({text}) => {
  const frame = useCurrentFrame();
  const s = spring({frame, fps:30});
  return (
    <AbsoluteFill style={{background:COLORS.background, color:COLORS.text, display:'flex', alignItems:'center', justifyContent:'center'}}>
      <div style={{textAlign:'center', width:'60%'}}>
        <h2 style={{fontSize:56, color:COLORS.text, margin:0}}>{text?.[0]}</h2>
        <h3 style={{fontSize:40, color:COLORS.accent, marginTop:20, transform:`scale(${1+0.05*s})`}}>{text?.[1]}</h3>
        <p style={{color:COLORS.muted, marginTop:30}}>When measurement freshness is unknown the numeric value alone is unreliable.</p>
      </div>
    </AbsoluteFill>
  );
};

export default ProblemScene;
