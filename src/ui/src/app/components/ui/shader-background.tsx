/**
 * ShaderBackground
 * ─────────────────────────────────────────────────────────
 * A full-viewport WebGL shader canvas rendered behind the app shell.
 *
 * Renders the oxide ambient shader — a subtle animated gradient
 * pattern that reinforces the dark terminal aesthetic.
 *
 * Design:
 *   - Fixed position, full viewport coverage, z-index -1
 *   - Pauses animation when document is hidden (tab backgrounded)
 *   - Falls back gracefully if WebGL is unavailable (canvas hidden)
 *   - Only renders in dark mode (transparent in light mode to avoid
 *     visual noise against the lighter background)
 *
 * Usage:
 *   <ShaderBackground />  — mount once inside the root layout
 */

import {
  useEffect,
  useRef,
  useCallback,
  type CSSProperties,
} from 'react';

export type ShaderPreset = 'soft' | 'aurora' | 'plasma';

export interface ShaderBackgroundProps {
  opacity?: number;
  speed?: number;
  colorSlots?: number[];
  brightness?: number;
  className?: string;
  style?: CSSProperties;
  preset?: ShaderPreset;
}

// ── Shader source ─────────────────────────────────────────────────────────────

const VERT = `
attribute vec2 a_position;
void main() {
  gl_Position = vec4(a_position, 0.0, 1.0);
}
`.trim();

// ── Preset-specific fragment shader bodies ───────────────────────────────────

const FRAG_COMMON_HEAD = `
precision mediump float;
uniform vec2  u_resolution;
uniform float u_time;
uniform float u_opacity;
uniform float u_speed;
uniform float u_brightness;
uniform vec3  u_color0;
uniform vec3  u_color1;
uniform vec3  u_color2;

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  float a = hash(i);
  float b = hash(i + vec2(1.0, 0.0));
  float c = hash(i + vec2(0.0, 1.0));
  float d = hash(i + vec2(1.0, 1.0));
  return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}
`.trim();

const FRAG_SOFT = `
void main() {
  vec2 uv = gl_FragCoord.xy / u_resolution;
  uv.y = 1.0 - uv.y;

  float t = u_time * 0.08 * u_speed;

  float n = noise(uv * 3.0 + t) * 0.5
          + noise(uv * 6.0 - t * 1.3) * 0.25
          + noise(uv * 12.0 + t * 0.7) * 0.125;
  n /= 0.875;

  vec2 center = uv - 0.5;
  float vignette = 1.0 - dot(center, center) * 1.8;
  vignette = clamp(vignette, 0.0, 1.0);

  vec3 col = mix(u_color0, u_color1, n * vignette * 0.6);
  col *= u_brightness;
  gl_FragColor = vec4(col, u_opacity);
}
`.trim();

const FRAG_AURORA = `
void main() {
  vec2 uv = gl_FragCoord.xy / u_resolution;
  uv.y = 1.0 - uv.y;

  float t = u_time * 0.05 * u_speed;

  // Horizontal aurora bands
  float wave1 = sin(uv.x * 4.0 + t) * 0.5 + 0.5;
  float wave2 = sin(uv.x * 2.5 - t * 0.7 + 1.5) * 0.5 + 0.5;
  float band = noise(vec2(uv.x * 3.0 + t * 0.3, uv.y * 8.0));

  float aurora = wave1 * wave2 * band;
  aurora *= smoothstep(0.7, 0.3, abs(uv.y - 0.3));

  vec3 col = mix(u_color0, u_color1, aurora);
  col = mix(col, u_color2, aurora * aurora * 0.5);
  col *= u_brightness;

  gl_FragColor = vec4(col, u_opacity * (0.6 + aurora * 0.4));
}
`.trim();

const FRAG_PLASMA = `
void main() {
  vec2 uv = gl_FragCoord.xy / u_resolution;
  uv.y = 1.0 - uv.y;

  float t = u_time * 0.12 * u_speed;

  float v1 = sin(uv.x * 10.0 + t);
  float v2 = sin(10.0 * (uv.x * sin(t * 0.5) + uv.y * cos(t * 0.33)) + t);
  float cx = uv.x + 0.5 * sin(t * 0.2);
  float cy = uv.y + 0.5 * cos(t * 0.15);
  float v3 = sin(sqrt(100.0 * (cx * cx + cy * cy)) + t);
  float v = (v1 + v2 + v3) / 3.0;

  float s = v * 0.5 + 0.5;
  vec3 col = mix(u_color0, u_color1, s);
  col = mix(col, u_color2, sin(s * 3.14159) * 0.4);
  col *= u_brightness;

  gl_FragColor = vec4(col, u_opacity * 0.85);
}
`.trim();

const PRESET_FRAGS: Record<ShaderPreset, string> = {
  soft: FRAG_SOFT,
  aurora: FRAG_AURORA,
  plasma: FRAG_PLASMA,
};

function buildFragSource(preset: ShaderPreset): string {
  return FRAG_COMMON_HEAD + '\n' + PRESET_FRAGS[preset];
}

// ── Default color slots (OKLCH-derived, mapped to linear RGB for shader) ─────

const DEFAULT_COLORS: Record<ShaderPreset, [number[], number[], number[]]> = {
  soft: [
    [0.035, 0.038, 0.045], // near-black base
    [0.055, 0.070, 0.095], // subtle blue-grey
    [0.045, 0.055, 0.075], // mid tone
  ],
  aurora: [
    [0.02, 0.025, 0.04],   // deep dark
    [0.04, 0.12, 0.10],    // teal-green glow
    [0.06, 0.05, 0.14],    // violet accent
  ],
  plasma: [
    [0.06, 0.02, 0.08],    // deep purple
    [0.02, 0.06, 0.10],    // cyan
    [0.08, 0.04, 0.02],    // amber
  ],
};

// ── WebGL helpers ─────────────────────────────────────────────────────────────

function compileShader(gl: WebGLRenderingContext, type: number, source: string): WebGLShader | null {
  const shader = gl.createShader(type);
  if (!shader) return null;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}

function buildProgram(gl: WebGLRenderingContext, preset: ShaderPreset): WebGLProgram | null {
  const vert = compileShader(gl, gl.VERTEX_SHADER, VERT);
  const frag = compileShader(gl, gl.FRAGMENT_SHADER, buildFragSource(preset));
  if (!vert || !frag) return null;

  const prog = gl.createProgram();
  if (!prog) return null;

  gl.attachShader(prog, vert);
  gl.attachShader(prog, frag);
  gl.linkProgram(prog);

  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
    gl.deleteProgram(prog);
    return null;
  }

  return prog;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function ShaderBackground({
  opacity = 0.92,
  speed = 1.0,
  brightness = 1.0,
  className,
  style,
  preset = 'soft',
}: ShaderBackgroundProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const presetRef = useRef(preset);
  presetRef.current = preset;

  const getColors = useCallback((): [number[], number[], number[]] => {
    return DEFAULT_COLORS[presetRef.current];
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const gl = canvas.getContext('webgl', {
      alpha: true,
      antialias: false,
      depth: false,
      stencil: false,
      premultipliedAlpha: false,
    });

    if (!gl) {
      canvas.style.display = 'none';
      return;
    }

    const prog = buildProgram(gl, preset);
    if (!prog) {
      canvas.style.display = 'none';
      return;
    }

    gl.useProgram(prog);

    // Full-screen quad
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]),
      gl.STATIC_DRAW,
    );

    const posLoc = gl.getAttribLocation(prog, 'a_position');
    gl.enableVertexAttribArray(posLoc);
    gl.vertexAttribPointer(posLoc, 2, gl.FLOAT, false, 0, 0);

    const uRes    = gl.getUniformLocation(prog, 'u_resolution');
    const uTime   = gl.getUniformLocation(prog, 'u_time');
    const uOpac   = gl.getUniformLocation(prog, 'u_opacity');
    const uSpeed  = gl.getUniformLocation(prog, 'u_speed');
    const uBright = gl.getUniformLocation(prog, 'u_brightness');
    const uColor0 = gl.getUniformLocation(prog, 'u_color0');
    const uColor1 = gl.getUniformLocation(prog, 'u_color1');
    const uColor2 = gl.getUniformLocation(prog, 'u_color2');

    // Set static uniforms
    const [c0, c1, c2] = getColors();
    gl.uniform1f(uOpac, opacity);
    gl.uniform1f(uSpeed, speed);
    gl.uniform1f(uBright, brightness);
    gl.uniform3f(uColor0, c0[0], c0[1], c0[2]);
    gl.uniform3f(uColor1, c1[0], c1[1], c1[2]);
    gl.uniform3f(uColor2, c2[0], c2[1], c2[2]);

    let rafId = 0;
    let start = performance.now();
    let paused = false;

    function resize() {
      const dpr = window.devicePixelRatio || 1;
      const w = window.innerWidth;
      const h = window.innerHeight;
      canvas!.width  = Math.round(w * dpr);
      canvas!.height = Math.round(h * dpr);
      gl!.viewport(0, 0, canvas!.width, canvas!.height);
    }

    function render(now: number) {
      if (paused) return;
      const t = (now - start) / 1000;
      gl!.uniform2f(uRes, canvas!.width, canvas!.height);
      gl!.uniform1f(uTime, t);
      gl!.drawArrays(gl!.TRIANGLES, 0, 6);
      rafId = requestAnimationFrame(render);
    }

    function onVisibility() {
      paused = document.hidden;
      if (!paused) {
        start = performance.now() - (rafId ? 0 : 0);
        rafId = requestAnimationFrame(render);
      }
    }

    resize();
    window.addEventListener('resize', resize);
    document.addEventListener('visibilitychange', onVisibility);
    rafId = requestAnimationFrame(render);

    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener('resize', resize);
      document.removeEventListener('visibilitychange', onVisibility);
      gl.deleteProgram(prog);
      gl.deleteBuffer(buf);
    };
  }, [preset, opacity, speed, brightness, getColors]);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className={className ?? 'fixed inset-0 -z-10 h-full w-full pointer-events-none dark:opacity-100 opacity-0 transition-opacity duration-500'}
      style={style}
    />
  );
}
