import React from 'react';
import {AbsoluteFill, Sequence, useCurrentFrame, interpolate} from 'remotion';
import {ThermometerVisual} from './visuals/ThermometerVisual';
import {RadiatorVisual} from './visuals/RadiatorVisual';
import {ControlNodeVisual} from './visuals/ControlNodeVisual';
import VisualAsset from './visuals/VisualAsset';
import {COLORS} from './theme';

export const VisualTest: React.FC = () => {
  const frame = useCurrentFrame();
  const fps = 30;
  // timeline 0-3s normal, 3-6s stale, 6-9 waiting, 9-12 recovered
  const t = frame / fps;
  const state = t < 3 ? 'normal' : t < 6 ? 'stale' : t < 9 ? 'waiting' : 'recovered';

  const packetX = interpolate(frame, [0, 90, 270, 360], [700, 520, 300, 120], {extrapolateRight: 'clamp'});

  return (
    <AbsoluteFill style={{background: COLORS.background}}>
      <div style={{display:'flex', justifyContent:'center', alignItems:'center', height:'100%'}}>
        <div style={{display:'flex', gap:60, alignItems:'center'}}>
          <div>
            <ThermometerVisual value={21.4} state={state} />
          </div>
          <div style={{width:640, height:360}}>
            <VisualAsset assetId="living_room" style={{width:640, height:360}} />
            {/* packet anim */}
            <div style={{position:'relative', left:packetX}}>
              <VisualAsset assetId="packet" style={{width:40, height:40}} />
            </div>
          </div>
          <div>
            <RadiatorVisual state={state === 'stale' ? 'idle' : 'heating_low'} />
            <ControlNodeVisual state={state === 'waiting' ? 'waiting' : state === 'stale' ? 'evaluating' : state} />
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
}

export default VisualTest;