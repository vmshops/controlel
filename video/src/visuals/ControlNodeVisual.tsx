import React from 'react';
import VisualAsset from './VisualAsset';

export const ControlNodeVisual: React.FC<{state?:string, style?:React.CSSProperties}> = ({state='normal', style})=>{
  return (
    <div style={{display:'flex', alignItems:'center', flexDirection:'column', ...style}}>
      <VisualAsset assetId="controlel_core" style={{width:140, height:140}} />
      <div style={{color:'#9fb4c6', fontSize:16, marginTop:8}}>{state}</div>
    </div>
  );
}

export default ControlNodeVisual;