import React from 'react';

const StatusBadge: React.FC<{x?:number,y?:number, text?:string, tone?:'normal'|'warn'|'ok'}> = ({x=0,y=0,text='OK', tone='normal'})=>{
  const bg = tone==='warn' ? '#ff8a00' : tone==='ok' ? '#2fe2c6' : '#00f0ff';
  return (
    <g transform={`translate(${x},${y})`}>
      <rect x={-8} y={-18} rx={8} width={150} height={36} fill="#07171a" stroke={bg} strokeWidth={2} />
      <text x={70} y={6} textAnchor="middle" fontSize={18} fill="#e6f5ff">{text}</text>
    </g>
  );
};

export default StatusBadge;
