import React from 'react';
import {assets as manifest} from '../generated/assets-manifest';

export const VisualAsset: React.FC<{assetId:string, style?:React.CSSProperties, className?:string}> = ({assetId, style, className})=>{
  const entry = (manifest as any)[assetId];
  if (!entry) return null;
  const file = (entry as any).file;
  const format = (entry as any).format;
  if (format === 'svg' || format === 'png' || format === 'jpg'){
    return <img src={file} style={style} className={className} alt={assetId} />;
  }
  if (format === 'lottie'){
    const LottiePlayer = require('./LottieAsset').default;
    return <LottiePlayer animationData={file} style={style} className={className} />;
  }
  return null;
}

export default VisualAsset;
