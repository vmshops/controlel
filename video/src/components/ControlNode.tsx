import React from 'react';

const ControlNode: React.FC<{x?:number,y?:number,state?:'normal'|'waiting'|'fallback'|'recovered'}> = ({x=0,y=0,state='normal'})=>{
  const color = state==='waiting' ? '#ffd07a' : state==='fallback' ? '#ff8a00' : state==='recovered' ? '#2fe2c6' : '#00f0ff';
  return (
    <g transform={`translate(${x},${y})`}>
      <circle cx="0" cy="0" r="34" fill="#07181a" stroke={color} strokeWidth={6} />
      <text x="0" y="6" textAnchor="middle" fontSize={14} fill="#e6f5ff">CTL</text>
    </g>
  );
};

export default ControlNode;
