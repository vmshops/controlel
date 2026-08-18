import React from 'react';
import {useCurrentFrame} from 'remotion';

const Countdown: React.FC<{durationFrames:number, label?:string}> = ({durationFrames, label='Waiting'})=>{
  const frame = useCurrentFrame();
  const remaining = Math.max(0, durationFrames - frame);
  const seconds = Math.ceil(remaining / 30);
  return (
    <g>
      <text x={0} y={0} fontSize={48} fill="#e6f5ff">{label}</text>
      <text x={0} y={52} fontSize={56} fill="#00f0ff">{seconds}s</text>
    </g>
  );
};

export default Countdown;
