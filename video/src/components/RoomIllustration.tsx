import React from 'react';

export const RoomIllustration: React.FC<{width?:number, height?:number, children?:React.ReactNode}> = ({width=700, height=420, children})=>{
  return (
    <svg width={width} height={height} viewBox="0 0 700 420" xmlns="http://www.w3.org/2000/svg">
      <rect x="0" y="0" width="700" height="420" rx="18" fill="#0f1720" />
      {/* floor */}
      <rect x="0" y="320" width="700" height="100" fill="#071318" rx="18" />
      {/* left wall */}
      <rect x="24" y="40" width="220" height="200" rx="8" fill="#0e1b22" />
      {/* radiator area placeholder */}
      <g transform="translate(48,100)">{/* children like radiator, thermometer will be placed by scenes */}</g>
      <g transform="translate(360,40)">{children}</g>
    </svg>
  );
};

export default RoomIllustration;
