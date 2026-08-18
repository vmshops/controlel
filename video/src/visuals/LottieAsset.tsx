import React from 'react';
import {Lottie} from '@remotion/lottie';

const LottieAsset: React.FC<{animationData:any, style?:React.CSSProperties, className?:string}> = ({animationData, style})=>{
  return (
    <div style={style}>
      <Lottie animationData={animationData} />
    </div>
  );
}

export default LottieAsset;
