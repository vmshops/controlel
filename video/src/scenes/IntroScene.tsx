import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';
import {COLORS, SIZES} from '../theme';

export const IntroScene: React.FC<{text: string[]}> = ({text}) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 10, 20], [0, 1, 1]);
  return (
    <AbsoluteFill style={{background: COLORS.background, color: COLORS.text, display:'flex', alignItems:'center', justifyContent:'center'}}>
      <div style={{textAlign:'center', width: SIZES.width*0.8, opacity}}>
        <h1 style={{fontSize: 72, margin:0}}>{text?.[0]}</h1>
        <p style={{fontSize: 40, marginTop:20}}>{text?.[1]}</p>
      </div>
    </AbsoluteFill>
  );
};

export default IntroScene;
