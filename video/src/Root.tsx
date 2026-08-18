import React from 'react';
import {Composition} from 'remotion';
import {loadProject} from './project-loader';
import {ControlelVideo} from './ControlelVideo';
import VisualTest from './VisualTest';

const project = loadProject('CTL-EDU-001');

export const Root: React.FC = () => {
  return (
    <>
      <Composition
        id={project.id}
        component={ControlelVideo}
        durationInFrames={Math.round(project.duration_seconds * project.fps)}
        fps={project.fps}
        width={1920}
        height={1080}
        defaultProps={{project}}
      />
      <Composition
        id={'CTL-VIS-001'}
        component={VisualTest}
        durationInFrames={12 * 30}
        fps={30}
        width={1920}
        height={1080}
      />
    </>
  );
};

export default Root;
