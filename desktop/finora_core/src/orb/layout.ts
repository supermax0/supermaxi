/** Shared geometry between the WebGL orb and the HTML hit-area / morph surface, so both line up exactly. */
export const ORB_FOV = 32;
export const ORB_RADIUS = 1;
/** Orb sits slightly below the stage center, leaving room for the status bubble above it. */
export const ORB_CENTER_Y_RATIO = 0.06;

export interface OrbLayout {
  /** On-screen diameter in CSS px. */
  diameter: number;
  /** Camera distance producing that diameter. */
  cameraZ: number;
  /** Downward offset of the orb center from the stage center, in CSS px. */
  offsetY: number;
}

export function orbLayout(stageWidth: number, stageHeight: number): OrbLayout {
  // Spec §6: 260–360px on desktop, scaled with the stage, never wider than the stage allows.
  const target = Math.min(stageHeight * 0.4, stageWidth * 0.42);
  const diameter = Math.round(Math.max(220, Math.min(360, target)));
  const visibleHeight = (stageHeight * 2 * ORB_RADIUS) / diameter;
  const cameraZ = visibleHeight / 2 / Math.tan(((ORB_FOV / 2) * Math.PI) / 180);
  return { diameter, cameraZ, offsetY: Math.round(stageHeight * ORB_CENTER_Y_RATIO) };
}
