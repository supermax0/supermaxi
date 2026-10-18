import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import type { AgentState } from "../data/schemas";
import type { AnimationQuality } from "../state/ui";
import { ORB_FOV, type OrbLayout } from "./layout";
import { ORB_VISUALS } from "./orbMachine";
import {
  haloFragment,
  haloVertex,
  orbFragment,
  orbVertex,
  particleFragment,
  particleVertex,
  waveFragment,
  waveVertex,
} from "./shaders";

interface Props {
  state: AgentState;
  layout: OrbLayout;
  quality: AnimationQuality;
  /** false → render loop stops completely (workspace open, window hidden). */
  running: boolean;
  /** Reduced motion: render on demand only (static frame per state change). */
  reducedMotion: boolean;
}

const QUALITY = {
  high: { dpr: [1, 1.75] as [number, number], particles: 220, segments: 96, waves: 6 },
  balanced: { dpr: [1, 1.25] as [number, number], particles: 120, segments: 64, waves: 4 },
  low: { dpr: [1, 1] as [number, number], particles: 50, segments: 48, waves: 2 },
};

/** Live uniforms shared by every orb layer; CPU lerps them toward the target state each frame. */
function useSharedUniforms() {
  return useMemo(
    () => ({
      uPhase: { value: 0 },
      uOrbit: { value: 0 },
      uEnergy: { value: ORB_VISUALS.idle.energy },
      uPulse: { value: 0 },
      uTint: { value: 0 },
      uPixelRatio: { value: 1 },
    }),
    [],
  );
}

type Shared = ReturnType<typeof useSharedUniforms>;

function Driver({
  state,
  shared,
  reducedMotion,
}: {
  state: AgentState;
  shared: Shared;
  reducedMotion: boolean;
}) {
  const cur = useRef({ ...ORB_VISUALS.idle });
  const invalidate = useThree((s) => s.invalidate);
  const dpr = useThree((s) => s.viewport.dpr);

  useEffect(() => {
    shared.uPixelRatio.value = dpr;
  }, [dpr, shared]);

  useEffect(() => {
    if (!reducedMotion) return;
    // Static rendering: snap to the target and draw one frame.
    const t = ORB_VISUALS[state];
    Object.assign(cur.current, t);
    shared.uEnergy.value = t.energy;
    shared.uPulse.value = 0;
    shared.uTint.value = t.tint;
    invalidate();
  }, [state, reducedMotion, shared, invalidate]);

  useFrame((_, rawDt) => {
    if (reducedMotion) return;
    const dt = Math.min(rawDt, 1 / 20); // avoid jumps after a stall
    const target = ORB_VISUALS[state];
    const k = 1 - Math.exp(-dt * 2.6);
    const c = cur.current;
    c.speed += (target.speed - c.speed) * k;
    c.energy += (target.energy - c.energy) * k;
    c.pulse += (target.pulse - c.pulse) * k;
    c.tint += (target.tint - c.tint) * k;
    c.orbit += (target.orbit - c.orbit) * k;
    shared.uPhase.value += dt * c.speed * 2.2;
    shared.uOrbit.value += dt * c.orbit * 2.0;
    shared.uEnergy.value = c.energy;
    shared.uPulse.value = c.pulse;
    shared.uTint.value = c.tint;
  });
  return null;
}

function CameraRig({ layout }: { layout: OrbLayout }) {
  const camera = useThree((s) => s.camera);
  const invalidate = useThree((s) => s.invalidate);
  useEffect(() => {
    camera.position.set(0, 0, layout.cameraZ);
    camera.updateProjectionMatrix();
    invalidate();
  }, [camera, layout.cameraZ, invalidate]);
  return null;
}

function Orb({ shared, segments }: { shared: Shared; segments: number }) {
  const geometry = useMemo(() => new THREE.SphereGeometry(1, segments, segments), [segments]);
  const back = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: orbVertex,
        fragmentShader: orbFragment,
        uniforms: { ...shared, uBack: { value: 1 } },
        transparent: true,
        depthWrite: false,
        side: THREE.BackSide,
      }),
    [shared],
  );
  const front = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: orbVertex,
        fragmentShader: orbFragment,
        uniforms: { ...shared, uBack: { value: 0 } },
        transparent: true,
        depthWrite: false,
        side: THREE.FrontSide,
      }),
    [shared],
  );
  const group = useRef<THREE.Group>(null);
  useFrame(() => {
    if (group.current) group.current.rotation.y = shared.uPhase.value * 0.08;
  });
  useEffect(() => () => [geometry, back, front].forEach((d) => d.dispose()), [geometry, back, front]);
  return (
    <group ref={group} rotation={[0.18, 0, -0.12]}>
      <mesh geometry={geometry} material={back} renderOrder={2} />
      <mesh geometry={geometry} material={front} renderOrder={3} />
    </group>
  );
}

function Halo({ shared }: { shared: Shared }) {
  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: haloVertex,
        fragmentShader: haloFragment,
        uniforms: shared,
        transparent: true,
        depthWrite: false,
      }),
    [shared],
  );
  useEffect(() => () => material.dispose(), [material]);
  return (
    <mesh position={[0, 0, -0.6]} material={material} renderOrder={1}>
      <planeGeometry args={[3.6, 3.6]} />
    </mesh>
  );
}

function Particles({ shared, count }: { shared: Shared; count: number }) {
  const geometry = useMemo(() => {
    // Deterministic distribution (stable screenshots).
    let seed = 7;
    const rnd = () => ((seed = (seed * 16807) % 2147483647) - 1) / 2147483646;
    const pos = new Float32Array(count * 3);
    const speed = new Float32Array(count);
    const size = new Float32Array(count);
    const seeds = new Float32Array(count);
    for (let i = 0; i < count; i++) {
      const r = 1.12 + rnd() * 1.1;
      const theta = rnd() * Math.PI * 2;
      const y = (rnd() - 0.5) * 1.5;
      pos[i * 3] = Math.cos(theta) * r;
      pos[i * 3 + 1] = y;
      pos[i * 3 + 2] = Math.sin(theta) * r;
      speed[i] = 0.4 + rnd() * 0.9;
      size[i] = 1.4 + rnd() * 2.6;
      seeds[i] = rnd();
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    g.setAttribute("aSpeed", new THREE.BufferAttribute(speed, 1));
    g.setAttribute("aSize", new THREE.BufferAttribute(size, 1));
    g.setAttribute("aSeed", new THREE.BufferAttribute(seeds, 1));
    return g;
  }, [count]);
  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: particleVertex,
        fragmentShader: particleFragment,
        uniforms: shared,
        transparent: true,
        depthWrite: false,
      }),
    [shared],
  );
  useEffect(() => () => [geometry, material].forEach((d) => d.dispose()), [geometry, material]);
  return <points geometry={geometry} material={material} renderOrder={4} />;
}

const WAVE_DEFS = [
  { y: 0.35, amp: 0.55, freq: 0.62, offset: 0.0, color: "#c9a7e8", opacity: 0.55 },
  { y: 0.05, amp: 0.7, freq: 0.48, offset: 1.7, color: "#a9c4f5", opacity: 0.5 },
  { y: -0.25, amp: 0.45, freq: 0.75, offset: 3.1, color: "#e9a3c4", opacity: 0.45 },
  { y: 0.6, amp: 0.38, freq: 0.9, offset: 4.4, color: "#b8b2f2", opacity: 0.35 },
  { y: -0.5, amp: 0.6, freq: 0.4, offset: 5.2, color: "#cfdcf7", opacity: 0.4 },
  { y: 0.15, amp: 0.85, freq: 0.33, offset: 2.4, color: "#d9b8e6", opacity: 0.3 },
];

function Waves({ shared, count }: { shared: Shared; count: number }) {
  const viewport = useThree((s) => s.viewport);
  const halfWidth = viewport.width / 2 + 0.5;
  const geometry = useMemo(() => {
    const n = 220;
    const pts = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) pts[i * 3] = -halfWidth + (2 * halfWidth * i) / (n - 1);
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(pts, 3));
    return g;
  }, [halfWidth]);
  const lines = useMemo(
    () =>
      WAVE_DEFS.slice(0, count).map((w) => {
        const material = new THREE.ShaderMaterial({
          vertexShader: waveVertex,
          fragmentShader: waveFragment,
          uniforms: {
            uPhase: shared.uPhase,
            uAmp: { value: w.amp },
            uFreq: { value: w.freq },
            uOffset: { value: w.offset },
            uY: { value: w.y },
            uColor: { value: new THREE.Color(w.color) },
            uOpacity: { value: w.opacity },
            uHalfWidth: { value: halfWidth },
          },
          transparent: true,
          depthWrite: false,
        });
        const line = new THREE.Line(geometry, material);
        line.position.z = -1.4;
        line.renderOrder = 0;
        return line;
      }),
    [count, geometry, halfWidth, shared.uPhase],
  );
  useEffect(
    () => () => {
      geometry.dispose();
      lines.forEach((l) => (l.material as THREE.Material).dispose());
    },
    [geometry, lines],
  );
  return (
    <group>
      {lines.map((l, i) => (
        <primitive key={i} object={l} />
      ))}
    </group>
  );
}

function Rings() {
  const rings = useMemo(
    () =>
      [1.3, 1.78, 2.4].map((r, i) => {
        const curve = new THREE.EllipseCurve(0, 0, r, r, 0, Math.PI * 2);
        const g = new THREE.BufferGeometry().setFromPoints(curve.getPoints(160));
        const m = new THREE.LineBasicMaterial({
          color: i === 1 ? "#c8b9f0" : "#d6dcf3",
          transparent: true,
          opacity: 0.75 - i * 0.22,
          depthWrite: false,
        });
        const loop = new THREE.LineLoop(g, m);
        loop.rotation.x = -Math.PI / 2.08;
        loop.position.y = -1.16;
        return loop;
      }),
    [],
  );
  useEffect(
    () => () =>
      rings.forEach((l) => {
        l.geometry.dispose();
        (l.material as THREE.Material).dispose();
      }),
    [rings],
  );
  return (
    <group>
      {rings.map((l, i) => (
        <primitive key={i} object={l} />
      ))}
    </group>
  );
}

export default function OrbCanvas({ state, layout, quality, running, reducedMotion }: Props) {
  const shared = useSharedUniforms();
  const q = QUALITY[quality];
  const orbY = -(layout.offsetY * 2) / layout.diameter;
  return (
    <Canvas
      className="orb-canvas"
      dpr={q.dpr}
      // offsetSize: measure layout size, not getBoundingClientRect. The stage scales this canvas during the
      // morph; a transformed measurement would resize the canvas to the scaled box and shift the orb.
      resize={{ offsetSize: true, scroll: false }}
      frameloop={!running ? "never" : reducedMotion ? "demand" : "always"}
      camera={{ fov: ORB_FOV, near: 0.1, far: 100, position: [0, 0, layout.cameraZ] }}
      gl={{ antialias: true, alpha: true, powerPreference: "high-performance", stencil: false }}
      aria-hidden="true"
    >
      <CameraRig layout={layout} />
      <Driver state={state} shared={shared} reducedMotion={reducedMotion} />
      <Waves shared={shared} count={q.waves} />
      <group position={[0, orbY, 0]}>
        <Rings />
        <Halo shared={shared} />
        <Orb shared={shared} segments={q.segments} />
        <Particles shared={shared} count={q.particles} />
      </group>
    </Canvas>
  );
}
