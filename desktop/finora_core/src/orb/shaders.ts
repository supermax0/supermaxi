/**
 * GLSL for the FINORA CORE orb. Everything animates on the GPU from a few uniforms;
 * the CPU only advances phases and lerps state parameters each frame.
 */

// Ashima Arts / Stefan Gustavson 3D simplex noise (MIT).
const NOISE = /* glsl */ `
vec3 mod289(vec3 x){return x-floor(x*(1.0/289.0))*289.0;}
vec4 mod289(vec4 x){return x-floor(x*(1.0/289.0))*289.0;}
vec4 permute(vec4 x){return mod289(((x*34.0)+1.0)*x);}
vec4 taylorInvSqrt(vec4 r){return 1.79284291400159-0.85373472095314*r;}
float snoise(vec3 v){
  const vec2 C=vec2(1.0/6.0,1.0/3.0);
  const vec4 D=vec4(0.0,0.5,1.0,2.0);
  vec3 i=floor(v+dot(v,C.yyy));
  vec3 x0=v-i+dot(i,C.xxx);
  vec3 g=step(x0.yzx,x0.xyz);
  vec3 l=1.0-g;
  vec3 i1=min(g.xyz,l.zxy);
  vec3 i2=max(g.xyz,l.zxy);
  vec3 x1=x0-i1+C.xxx;
  vec3 x2=x0-i2+C.yyy;
  vec3 x3=x0-D.yyy;
  i=mod289(i);
  vec4 p=permute(permute(permute(i.z+vec4(0.0,i1.z,i2.z,1.0))+i.y+vec4(0.0,i1.y,i2.y,1.0))+i.x+vec4(0.0,i1.x,i2.x,1.0));
  float n_=0.142857142857;
  vec3 ns=n_*D.wyz-D.xzx;
  vec4 j=p-49.0*floor(p*ns.z*ns.z);
  vec4 x_=floor(j*ns.z);
  vec4 y_=floor(j-7.0*x_);
  vec4 x=x_*ns.x+ns.yyyy;
  vec4 y=y_*ns.x+ns.yyyy;
  vec4 h=1.0-abs(x)-abs(y);
  vec4 b0=vec4(x.xy,y.xy);
  vec4 b1=vec4(x.zw,y.zw);
  vec4 s0=floor(b0)*2.0+1.0;
  vec4 s1=floor(b1)*2.0+1.0;
  vec4 sh=-step(h,vec4(0.0));
  vec4 a0=b0.xzyw+s0.xzyw*sh.xxyy;
  vec4 a1=b1.xzyw+s1.xzyw*sh.zzww;
  vec3 p0=vec3(a0.xy,h.x);
  vec3 p1=vec3(a0.zw,h.y);
  vec3 p2=vec3(a1.xy,h.z);
  vec3 p3=vec3(a1.zw,h.w);
  vec4 norm=taylorInvSqrt(vec4(dot(p0,p0),dot(p1,p1),dot(p2,p2),dot(p3,p3)));
  p0*=norm.x;p1*=norm.y;p2*=norm.z;p3*=norm.w;
  vec4 m=max(0.6-vec4(dot(x0,x0),dot(x1,x1),dot(x2,x2),dot(x3,x3)),0.0);
  m=m*m;
  return 42.0*dot(m*m,vec4(dot(p0,x0),dot(p1,x1),dot(p2,x2),dot(p3,x3)));
}`;

const TINT = /* glsl */ `
vec3 applyTint(vec3 c, float tint){
  // tint > 0: warm attention (amber); tint < 0: desaturated (offline)
  vec3 warm = c * vec3(1.08, 0.86, 0.62) + vec3(0.06, 0.03, 0.0);
  float l = dot(c, vec3(0.299, 0.587, 0.114));
  c = mix(c, warm, clamp(tint, 0.0, 1.0) * 0.75);
  c = mix(c, vec3(l), clamp(-tint, 0.0, 1.0) * 0.85);
  return c;
}`;

export const orbVertex = /* glsl */ `
uniform float uPhase;
uniform float uPulse;
varying vec3 vN;
varying vec3 vObj;
void main(){
  float breathe = 1.0 + 0.012 * sin(uPhase * 1.7) + uPulse * 0.028 * sin(uPhase * 6.0);
  vec3 pos = position * breathe;
  vObj = position;
  vN = normalize(normalMatrix * normal);
  gl_Position = projectionMatrix * modelViewMatrix * vec4(pos, 1.0);
}`;

export const orbFragment = /* glsl */ `
precision highp float;
uniform float uPhase;
uniform float uEnergy;
uniform float uTint;
uniform float uBack;
varying vec3 vN;
varying vec3 vObj;
${NOISE}
${TINT}
void main(){
  vec3 n = normalize(vN);
  if (uBack > 0.5) n = -n;
  float facing = clamp(n.z, 0.0, 1.0);
  float fres = pow(1.0 - facing, 2.0);
  float t = uPhase;

  // Swirl the sample space around a tilted axis so ribbons wrap the sphere.
  vec3 p = vObj;
  float a = t * 0.55 + p.y * 1.35;
  float ca = cos(a), sa = sin(a);
  p.xz = mat2(ca, -sa, sa, ca) * p.xz;

  float n1 = snoise(p * 1.25 + vec3(0.0, t * 0.35, t * 0.12));
  float n2 = snoise(p * 2.3 - vec3(t * 0.22, 0.0, t * 0.31));

  float f1 = dot(p, normalize(vec3(0.55, 1.0, 0.25))) * 2.6 + n1 * 1.7 + t * 0.9;
  float f2 = dot(p, normalize(vec3(-0.85, 0.35, 0.5))) * 2.1 + n2 * 1.3 - t * 0.7;
  float f3 = dot(p, normalize(vec3(0.2, -0.6, 0.9))) * 3.4 + n1 * 0.9 + t * 0.5;
  float r1 = pow(0.5 + 0.5 * sin(f1), 5.0);
  float r2 = pow(0.5 + 0.5 * sin(f2), 7.0);
  float r3 = pow(0.5 + 0.5 * sin(f3), 12.0);

  vec3 burgundy = vec3(0.42, 0.02, 0.16);
  vec3 plum     = vec3(0.55, 0.12, 0.42);
  vec3 rose     = vec3(0.93, 0.42, 0.68);
  vec3 violet   = vec3(0.42, 0.33, 0.93);
  vec3 sky      = vec3(0.40, 0.60, 1.00);
  vec3 c1 = mix(burgundy, rose, 0.25 + 0.45 * (0.5 + 0.5 * n1));
  c1 = mix(c1, plum, 0.35 * (0.5 + 0.5 * n2));
  vec3 c2 = mix(violet, sky, 0.5 + 0.5 * n2);

  // Ribbons are strongest toward the rim, misty-white toward the center (keeps the wordmark readable).
  float rimW = 0.3 + 0.7 * smoothstep(0.05, 0.9, 1.0 - facing * 0.82);
  vec3 col = vec3(0.975, 0.97, 0.99);
  col = mix(col, c2, r2 * rimW * 0.95);
  col = mix(col, c1, r1 * rimW);
  col = mix(col, vec3(1.0, 0.82, 0.93), r3 * 0.4);

  // Inner light + center mist.
  col = mix(col, vec3(1.0), smoothstep(0.72, 1.0, facing) * (0.58 - 0.18 * uEnergy));
  col += vec3(0.06, 0.04, 0.1) * uEnergy * (r1 + r2);

  // Glass: tinted rim light (violet → pink around the edge) and a soft specular highlight.
  vec3 rimCol = mix(vec3(0.58, 0.52, 1.0), vec3(0.95, 0.55, 0.8), 0.5 + 0.5 * sin(atan(n.y, n.x) * 1.5 + t * 0.4));
  col = mix(col, rimCol, fres * 0.45);
  float spec = pow(max(dot(n, normalize(vec3(-0.45, 0.62, 0.65))), 0.0), 38.0);
  col += vec3(1.0) * spec * 0.55;

  col = applyTint(col, uTint);

  float alpha = clamp(0.24 + fres * 0.76 + (r1 + r2) * 0.5 * rimW, 0.0, 1.0);
  if (uBack > 0.5) alpha *= 0.42;
  gl_FragColor = vec4(col, alpha);
}`;

export const haloVertex = /* glsl */ `
varying vec2 vUv;
void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;

export const haloFragment = /* glsl */ `
precision mediump float;
uniform float uEnergy;
uniform float uTint;
uniform float uPhase;
varying vec2 vUv;
${TINT}
void main(){
  vec2 q = vUv * 2.0 - 1.0;
  float r = length(q);
  float ang = atan(q.y, q.x);
  float glow = smoothstep(1.0, 0.38, r) * smoothstep(0.30, 0.42, r);
  vec3 pink = vec3(0.95, 0.55, 0.78);
  vec3 lilac = vec3(0.62, 0.58, 1.0);
  vec3 col = mix(pink, lilac, 0.5 + 0.5 * sin(ang * 2.0 + uPhase * 0.4));
  col = applyTint(col, uTint);
  gl_FragColor = vec4(col, glow * (0.20 + 0.22 * uEnergy));
}`;

export const particleVertex = /* glsl */ `
uniform float uOrbit;
uniform float uPixelRatio;
attribute float aSpeed;
attribute float aSize;
attribute float aSeed;
varying float vAlpha;
varying float vSeed;
void main(){
  float a = uOrbit * aSpeed;
  float c = cos(a), s = sin(a);
  vec3 p = position;
  p.xz = mat2(c, -s, s, c) * p.xz;
  p.y += 0.06 * sin(uOrbit * 2.0 + aSeed * 6.2831);
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = aSize * uPixelRatio * (9.0 / -mv.z);
  vAlpha = 0.35 + 0.65 * fract(aSeed * 13.17 + uOrbit * 0.15);
  vSeed = aSeed;
}`;

export const particleFragment = /* glsl */ `
precision mediump float;
uniform float uTint;
varying float vAlpha;
varying float vSeed;
${TINT}
void main(){
  vec2 q = gl_PointCoord * 2.0 - 1.0;
  float d = dot(q, q);
  if (d > 1.0) discard;
  vec3 col = mix(vec3(0.93, 0.5, 0.74), vec3(0.55, 0.62, 1.0), step(0.5, vSeed));
  col = mix(col, vec3(1.0), 0.35);
  col = applyTint(col, uTint);
  gl_FragColor = vec4(col, (1.0 - d) * vAlpha * 0.85);
}`;

export const waveVertex = /* glsl */ `
uniform float uPhase;
uniform float uAmp;
uniform float uFreq;
uniform float uOffset;
uniform float uY;
varying float vX;
void main(){
  vec3 p = position;
  float env = 0.55 + 0.45 * cos(p.x * 0.22);
  p.y = uY + uAmp * env * sin(p.x * uFreq + uPhase + uOffset) + 0.18 * sin(p.x * 0.35 - uPhase * 0.6 + uOffset);
  vX = p.x;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
}`;

export const waveFragment = /* glsl */ `
precision mediump float;
uniform vec3 uColor;
uniform float uOpacity;
uniform float uHalfWidth;
varying float vX;
void main(){
  float edge = 1.0 - smoothstep(uHalfWidth * 0.55, uHalfWidth, abs(vX));
  gl_FragColor = vec4(uColor, uOpacity * edge);
}`;
