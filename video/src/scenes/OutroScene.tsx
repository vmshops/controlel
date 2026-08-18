import React from 'react';
import {AbsoluteFill} from 'remotion';
import {COLORS} from '../theme';

export const OutroScene: React.FC<{text:string[]}> = ({text}) => {
  return (
    <AbsoluteFill style={{background:COLORS.background, color:COLORS.text, display:'flex', alignItems:'center', justifyContent:'center'}}>
      <div style={{textAlign:'center'}}>
        <h1 style={{fontSize:72, margin:0}}>{text?.[0]}</h1>
        <h2 style={{fontSize:36, marginTop:20}}>{text?.[1]}</h2>
        <p style={{marginTop:30, color:COLORS.muted}}>{text?.[2]}</p>
      </div>
    </AbsoluteFill>
  );
};

export default OutroScene;
