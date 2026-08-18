import React from 'react';
import {useCurrentFrame, AbsoluteFill, Sequence} from 'remotion';
import {ProjectModel} from './types';
import {IntroScene} from './scenes/IntroScene';
import {SensorScene} from './scenes/SensorScene';
import {ProblemScene} from './scenes/ProblemScene';
import {GraceScene} from './scenes/GraceScene';
import {SafeFallbackScene} from './scenes/SafeFallbackScene';
import {RecoveryScene} from './scenes/RecoveryScene';
import {OutroScene} from './scenes/OutroScene';

export const ControlelVideo: React.FC<{project: ProjectModel}> = ({project}) => {
  const totalFrames = Math.round(project.duration_seconds * project.fps);
  // calculate frame ranges from scene durations
  let cursor = 0;
  return (
    <AbsoluteFill style={{background:'#0b1220'}}>
      {project.scenes.map((s, idx) => {
        const durationFrames = Math.round((s.duration || 5) * project.fps);
        const start = cursor;
        cursor += durationFrames;
        const key = `${s.id}-${idx}`;
        switch (s.type) {
          case 'Intro':
            return <Sequence key={key} from={start} durationInFrames={durationFrames}><IntroScene text={s.text} /></Sequence>;
          case 'Sensor':
            return <Sequence key={key} from={start} durationInFrames={durationFrames}><SensorScene def={s} fps={project.fps} /></Sequence>;
          case 'Problem':
            return <Sequence key={key} from={start} durationInFrames={durationFrames}><ProblemScene text={s.text} /></Sequence>;
          case 'Grace':
            return <Sequence key={key} from={start} durationInFrames={durationFrames}><GraceScene text={s.text} fps={project.fps} /></Sequence>;
          case 'SafeFallback':
            return <Sequence key={key} from={start} durationInFrames={durationFrames}><SafeFallbackScene text={s.text} /></Sequence>;
          case 'Recovery':
            return <Sequence key={key} from={start} durationInFrames={durationFrames}><RecoveryScene text={s.text} /></Sequence>;
          case 'Outro':
            return <Sequence key={key} from={start} durationInFrames={durationFrames}><OutroScene text={s.text} /></Sequence>;
          default:
            return null;
        }
      })}
    </AbsoluteFill>
  );
};

export default ControlelVideo;
