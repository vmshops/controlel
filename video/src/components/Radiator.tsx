import React from 'react';

const Radiator: React.FC<{x?:number,y?:number, active?:boolean}> = ({x=0,y=0, active=false}) => {
  const fill = active ? '#ffb88c' : '#23333a';
  return (
    <g transform={`translate(${x},${y})`}>
      <rect x="0" y="0" width="220" height="60" rx="8" fill={fill} stroke="#0b1012" />
      <g transform="translate(10,10)">
        {[0,1,2,3,4].map((i)=> <rect key={i} x={i*38} y={0} width={28} height={40} rx={4} fill="#0b1012" opacity={0.08} />)}
      </g>
    </g>
  );
};

export default Radiator;
