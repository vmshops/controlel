import React from 'react';

const Boiler: React.FC<{x?:number,y?:number,active?:boolean}> = ({x=0,y=0,active=false})=>{
  const color = active ? '#ff8a00' : '#153033';
  return (
    <g transform={`translate(${x},${y})`}>
      <rect x="0" y="0" width="140" height="100" rx="12" fill={color} stroke="#071014" />
      <text x="70" y="56" fill="#071014" fontSize="20" textAnchor="middle">Heat</text>
    </g>
  );
};

export default Boiler;
