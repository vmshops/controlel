import React from 'react';

const Thermometer: React.FC<{x?:number,y?:number, value?:number, warning?:boolean, pulse?:boolean}> = ({x=0,y=0,value=21.4,warning=false,pulse=false})=>{
  const color = warning ? '#ff8a00' : '#00f0ff';
  return (
    <g transform={`translate(${x},${y})`}>
      <rect x="0" y="0" width="110" height="180" rx="12" fill="#08171a" stroke={color} strokeWidth={pulse?4:2} />
      <circle cx="55" cy="140" r="18" fill={color} />
      <text x="55" y="30" fill="#e6f5ff" fontSize="26" textAnchor="middle">{value?.toFixed(1)}°C</text>
    </g>
  );
};

export default Thermometer;
