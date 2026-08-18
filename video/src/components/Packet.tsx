import React from 'react';

const Packet: React.FC<{x?:number,y?:number, color?:string, opacity?:number, scale?:number}> = ({x=0,y=0,color='#00f0ff',opacity=1,scale=1})=>{
  return (
    <g transform={`translate(${x},${y}) scale(${scale})`} opacity={opacity}>
      <circle cx="0" cy="0" r="8" fill={color} />
      <path d="M-6 -4 L6 0 L-6 4 Z" fill={color} opacity={0.8} />
    </g>
  );
};

export default Packet;
