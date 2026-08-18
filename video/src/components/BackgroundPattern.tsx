import React from 'react';
import {AbsoluteFill} from 'remotion';
import {COLORS} from '../theme';

const BackgroundPattern: React.FC<{children?: React.ReactNode}> = ({children}) => {
  return (
    <AbsoluteFill style={{background: `linear-gradient(180deg, ${COLORS.background} 0%, #05111a 100%)`, color: COLORS.text}}>
      <svg style={{position:'absolute', inset:0, width:'100%', height:'100%'}} preserveAspectRatio="none">
        <defs>
          <pattern id="grid" width="120" height="120" patternUnits="userSpaceOnUse">
            <path d="M120 0 L0 0 0 120" stroke="#052428" strokeWidth="1" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#grid)" opacity="0.12" />
      </svg>
      <div style={{position:'relative', width:'100%', height:'100%'}}>
        {children}
      </div>
    </AbsoluteFill>
  );
};

export default BackgroundPattern;
