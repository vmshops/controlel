import React from 'react';
import VisualAsset from './VisualAsset';

export const ThermometerVisual: React.FC<{value?:number, state?:string, style?:React.CSSProperties}> = ({value=21.4, state='normal', style})=>{
  return (
    <div style={{display:'flex', alignItems:'center', flexDirection:'column', ...style}}>
      <VisualAsset assetId="thermometer" style={{width:220, height:220}} />
      <div style={{color:'#e6f5ff', fontSize:28, marginTop:8}}>{value?.toFixed(1)} °C</div>
    </div>
  );
}

export default ThermometerVisual;