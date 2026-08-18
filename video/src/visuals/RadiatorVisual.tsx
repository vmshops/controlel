import React from 'react';
import VisualAsset from './VisualAsset';

export const RadiatorVisual: React.FC<{state?:string, style?:React.CSSProperties}> = ({state='idle', style})=>{
  return (
    <div style={{display:'flex', alignItems:'center', flexDirection:'column', ...style}}>
      <VisualAsset assetId="radiator" style={{width:320, height:120}} />
      <div style={{color:'#9fb4c6', fontSize:16, marginTop:8}}>{state}</div>
    </div>
  );
}

export default RadiatorVisual;