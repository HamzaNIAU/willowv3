"use client"

import { useEffect, useRef } from 'react'
import * as THREE from 'three'

export default function GradientVanilla() {
  const containerRef = useRef<HTMLDivElement>(null)
  const animationRef = useRef<number>(0)

  useEffect(() => {
    if (!containerRef.current) return

    // Create scene, camera, renderer
    const scene = new THREE.Scene()
    const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 10)
    camera.position.z = 1

    const renderer = new THREE.WebGLRenderer({ 
      antialias: true,
      alpha: true 
    })
    renderer.setSize(window.innerWidth, window.innerHeight)
    renderer.setPixelRatio(window.devicePixelRatio)
    containerRef.current.appendChild(renderer.domElement)

    // Create uniforms
    const uniforms = {
      iTime: { value: 0.0 },
      iResolution: { value: new THREE.Vector3(window.innerWidth, window.innerHeight, 1) },
      noiseIntensity: { value: 1.55 },
      noiseScale: { value: 2.0 },
      noiseSpeed: { value: 0.15 },
      waveNoiseIntensity: { value: 1.2 },
      waveNoiseScale1: { value: 0.5 },
      waveNoiseScale2: { value: 0.8 },
      waveNoiseScale3: { value: 1.2 },
      waveNoiseSpeed1: { value: 0.24 },
      waveNoiseSpeed2: { value: 0.2 },
      waveNoiseSpeed3: { value: 0.3 },
    }

    // Create shader material
    const material = new THREE.ShaderMaterial({
      uniforms,
      vertexShader,
      fragmentShader,
      transparent: true
    })

    // Create mesh
    const geometry = new THREE.PlaneGeometry(2, 2)
    const mesh = new THREE.Mesh(geometry, material)
    scene.add(mesh)

    // Animation loop
    const startTime = performance.now()
    const animate = () => {
      animationRef.current = requestAnimationFrame(animate)
      const elapsedTime = (performance.now() - startTime) / 1000
      uniforms.iTime.value = elapsedTime
      renderer.render(scene, camera)
    }
    animate()

    // Handle resize
    const handleResize = () => {
      const width = window.innerWidth
      const height = window.innerHeight
      renderer.setSize(width, height)
      uniforms.iResolution.value.set(width, height, 1)
    }
    window.addEventListener('resize', handleResize)

    // Cleanup
    return () => {
      cancelAnimationFrame(animationRef.current)
      window.removeEventListener('resize', handleResize)
      renderer.dispose()
      geometry.dispose()
      material.dispose()
      if (containerRef.current && renderer.domElement) {
        containerRef.current.removeChild(renderer.domElement)
      }
    }
  }, [])

  return <div ref={containerRef} className="absolute inset-0 w-full h-full" />
}

const vertexShader = `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`

const fragmentShader = `
  uniform vec3 iResolution;
  uniform float iTime;
  uniform float noiseIntensity;
  uniform float noiseScale;
  uniform float noiseSpeed;
  uniform float waveNoiseIntensity;
  uniform float waveNoiseScale1;
  uniform float waveNoiseScale2;
  uniform float waveNoiseScale3;
  uniform float waveNoiseSpeed1;
  uniform float waveNoiseSpeed2;
  uniform float waveNoiseSpeed3;
  varying vec2 vUv;

  #define BLEND_MODE 2
  #define SPEED 2.0
  #define INTENSITY 0.075
  #define MEAN 0.0
  #define VARIANCE 0.5

  vec2 hash(vec2 p) {
    p = vec2(dot(p, vec2(127.1, 311.7)), dot(p, vec2(269.5, 183.3)));
    return -1.0 + 2.0 * fract(sin(p) * 43758.5453123);
  }

  float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(
      mix(dot(hash(i + vec2(0.0, 0.0)), f - vec2(0.0, 0.0)),
          dot(hash(i + vec2(1.0, 0.0)), f - vec2(1.0, 0.0)), u.x),
      mix(dot(hash(i + vec2(0.0, 1.0)), f - vec2(0.0, 1.0)),
          dot(hash(i + vec2(1.0, 1.0)), f - vec2(1.0, 1.0)), u.x),
      u.y
    );
  }

  vec3 mod289(vec3 x) {
    return x - floor(x * (1.0 / 289.0)) * 289.0;
  }

  vec4 mod289(vec4 x) {
    return x - floor(x * (1.0 / 289.0)) * 289.0;
  }

  vec4 permute(vec4 x) {
    return mod289(((x*34.0)+1.0)*x);
  }

  vec4 taylorInvSqrt(vec4 r) {
    return 1.79284291400159 - 0.85373472095314 * r;
  }

  float snoise(vec3 v) { 
    const vec2 C = vec2(1.0/6.0, 1.0/3.0);
    const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
    vec3 i = floor(v + dot(v, C.yyy));
    vec3 x0 = v - i + dot(i, C.xxx);
    vec3 g = step(x0.yzx, x0.xyz);
    vec3 l = 1.0 - g;
    vec3 i1 = min(g.xyz, l.zxy);
    vec3 i2 = max(g.xyz, l.zxy);
    vec3 x1 = x0 - i1 + C.xxx;
    vec3 x2 = x0 - i2 + C.yyy;
    vec3 x3 = x0 - D.yyy;
    i = mod289(i);
    vec4 p = permute(permute(permute(
      i.z + vec4(0.0, i1.z, i2.z, 1.0))
      + i.y + vec4(0.0, i1.y, i2.y, 1.0))
      + i.x + vec4(0.0, i1.x, i2.x, 1.0));
    float n_ = 0.142857142857;
    vec3 ns = n_ * D.wyz - D.xzx;
    vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
    vec4 x_ = floor(j * ns.z);
    vec4 y_ = floor(j - 7.0 * x_);
    vec4 x = x_ * ns.x + ns.yyyy;
    vec4 y = y_ * ns.x + ns.yyyy;
    vec4 h = 1.0 - abs(x) - abs(y);
    vec4 b0 = vec4(x.xy, y.xy);
    vec4 b1 = vec4(x.zw, y.zw);
    vec4 s0 = floor(b0) * 2.0 + 1.0;
    vec4 s1 = floor(b1) * 2.0 + 1.0;
    vec4 sh = -step(h, vec4(0.0));
    vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
    vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;
    vec3 p0 = vec3(a0.xy, h.x);
    vec3 p1 = vec3(a0.zw, h.y);
    vec3 p2 = vec3(a1.xy, h.z);
    vec3 p3 = vec3(a1.zw, h.w);
    vec4 norm = taylorInvSqrt(vec4(dot(p0,p0), dot(p1,p1), dot(p2,p2), dot(p3,p3)));
    p0 *= norm.x;
    p1 *= norm.y;
    p2 *= norm.z;
    p3 *= norm.w;
    vec4 m = max(0.6 - vec4(dot(x0,x0), dot(x1,x1), dot(x2,x2), dot(x3,x3)), 0.0);
    m = m * m;
    return 42.0 * dot(m*m, vec4(dot(p0,x0), dot(p1,x1), dot(p2,x2), dot(p3,x3)));
  }

  vec2 warp(vec2 p) {
    float n1 = noise(p * waveNoiseScale1 + vec2(iTime * waveNoiseSpeed1, 0.0));
    float n2 = noise(p * waveNoiseScale1 + vec2(0.0, iTime * waveNoiseSpeed2));
    float n3 = noise(p * waveNoiseScale2 + vec2(iTime * -waveNoiseSpeed3, iTime * waveNoiseSpeed3)) * 0.5;
    float n4 = noise(p * waveNoiseScale3 + vec2(iTime * waveNoiseSpeed3, -iTime * waveNoiseSpeed3)) * 0.3;
    return p + vec2(n1 + n3, n2 + n4) * waveNoiseIntensity;
  }

  vec3 channel_mix(vec3 a, vec3 b, vec3 w) {
    return vec3(mix(a.r, b.r, w.r), mix(a.g, b.g, w.g), mix(a.b, b.b, w.b));
  }

  float gaussian(float z, float u, float o) {
    return (1.0 / (o * sqrt(2.0 * 3.1415))) * exp(-(((z - u) * (z - u)) / (2.0 * (o * o))));
  }

  vec3 overlay(vec3 a, vec3 b, float w) {
    return mix(a, channel_mix(
      2.0 * a * b,
      vec3(1.0) - 2.0 * (vec3(1.0) - a) * (vec3(1.0) - b),
      step(vec3(0.5), a)
    ), w);
  }

  vec3 hexToRgb(float r, float g, float b) {
    return vec3(r / 255.0, g / 255.0, b / 255.0);
  }

  vec3 multiColorGradient(float t) {
    vec3 colors[7];
    colors[0] = hexToRgb(250.0, 212.0, 251.0);
    colors[1] = hexToRgb(250.0, 200.0, 225.0);
    colors[2] = hexToRgb(250.0, 182.0, 21.0);
    colors[3] = hexToRgb(252.0, 104.0, 30.0);
    colors[4] = hexToRgb(13.0, 93.0, 244.0);
    colors[5] = hexToRgb(11.0, 74.0, 187.0);
    colors[6] = hexToRgb(23.0, 14.0, 7.0);
    
    t = clamp(t, 0.0, 1.0);
    float scaledT = t * 6.0;
    int index = int(floor(scaledT));
    float localT = fract(scaledT);
    
    if (index >= 6) return colors[6];
    
    float smoothT = smoothstep(0.0, 1.0, localT);
    return mix(colors[index], colors[index + 1], smoothT);
  }

  vec3 applyGrain(vec3 color, vec2 uv) {
    float t = iTime * SPEED;
    float seed = dot(uv, vec2(12.9898, 78.233));
    float grainNoise = fract(sin(seed) * 43758.5453 + t);
    grainNoise = gaussian(grainNoise, MEAN, VARIANCE * VARIANCE);
    vec3 grain = vec3(grainNoise) * (1.0 - color);
    float w = INTENSITY;
    return overlay(color, grain, w);
  }

  void main() {
    vec2 fragCoord = vUv * iResolution.xy;
    vec2 uv = (fragCoord - 0.5 * iResolution.xy) / iResolution.y;
    
    vec2 warpedUv = warp(uv);
    float simplexNoise = snoise(vec3(warpedUv * noiseScale, iTime * noiseSpeed)) * noiseIntensity;
    warpedUv += simplexNoise;
    
    float phase1 = iTime * 0.6;
    float phase2 = iTime * 0.4;
    float distanceFromCenter = length(warpedUv - vec2(0.0, 0.0));
    float archFactor = 1.0 - distanceFromCenter * 0.5;
    float wave1 = sin(warpedUv.x * 3.0 + phase1) * 0.5 * archFactor;
    float wave2 = sin(warpedUv.x * 5.0 - phase2) * 0.3 * archFactor;
    float wave3 = sin(warpedUv.y * 4.0 + phase1 * 0.7) * 0.15;
    float parabolicArch = -pow(warpedUv.x, 2.0) * 0.2;
    float breathing = sin(iTime * 0.5) * 0.1 + 0.9;
    float combinedWave = (wave1 + wave2 + wave3 + parabolicArch) * breathing * 0.3;
    
    float gradientPos = (vUv.y + combinedWave * 0.3);
    float smoothGradientPos = smoothstep(0.0, 1.0, clamp(1.0 - gradientPos, 0.0, 1.0));
    vec3 color = multiColorGradient(smoothGradientPos);
    
    gl_FragColor = vec4(applyGrain(color, vUv), 1.0);
  }
`