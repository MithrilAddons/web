import { useEffect, useRef, useState } from "react";

// Minecraft's panorama order (front, right, back, left, up, down) as three.js wants its cube
// faces (+x, -x, +y, -y, +z, -z). three.js mirrors cube backgrounds along x, so the right face
// fills -x and the left +x; the camera starts out looking along -z, at the front.
export const CUBE_ORDER = [3, 1, 4, 5, 2, 0] as const;
// The up and down screenshots come out turned half way round against the cube's axes.
const TURNED = new Set([4, 5]);
const DRAG = 0.005;
const PITCH = Math.PI / 2 - 0.01;

/** Turns a drag into a new view; looking up and down stops just short of straight. */
export function look(
  view: { yaw: number; pitch: number },
  dx: number,
  dy: number,
) {
  return {
    yaw: view.yaw + dx * DRAG,
    pitch: Math.max(-PITCH, Math.min(PITCH, view.pitch + dy * DRAG)),
  };
}

/** Cuts the round's image (three faces across, two down) into six square canvases. */
export function sliceFaces(image: HTMLImageElement) {
  const size = image.naturalWidth / 3;
  return Array.from({ length: 6 }, (_, face) => {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = size;
    const context = canvas.getContext("2d");
    if (context && TURNED.has(face)) {
      context.translate(size, size);
      context.rotate(Math.PI);
    }
    context?.drawImage(
      image,
      (face % 3) * size,
      Math.floor(face / 3) * size,
      size,
      size,
      0,
      0,
      size,
      size,
    );
    return canvas;
  });
}

/** A 360° view to drag around; no zoom, so a far-off detail stays far off. */
export function Panorama({
  src,
  onReady,
}: Readonly<{ src: string; onReady: () => void }>) {
  const host = useRef<HTMLElement>(null);
  const ready = useRef(onReady);
  const [failed, setFailed] = useState(false);
  ready.current = onReady;

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    let disposed = false;
    let cleanup = () => undefined as void;
    void (async () => {
      const three = await import("three");
      const image = new Image();
      image.src = src;
      try {
        await image.decode();
      } catch {
        if (!disposed) setFailed(true);
        return;
      }
      if (disposed) return;
      const renderer = new three.WebGLRenderer({ antialias: true });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      const camera = new three.PerspectiveCamera(75, 1, 0.1, 10);
      camera.rotation.order = "YXZ";
      const scene = new three.Scene();
      const faces = sliceFaces(image);
      const texture = new three.CubeTexture(CUBE_ORDER.map((n) => faces[n]));
      texture.colorSpace = three.SRGBColorSpace;
      texture.needsUpdate = true;
      scene.background = texture;
      // Each round opens facing a random way.
      const turn = crypto.getRandomValues(new Uint32Array(1))[0]! / 2 ** 32;
      let view = { yaw: turn * Math.PI * 2, pitch: 0 };
      const draw = () => {
        camera.rotation.set(view.pitch, view.yaw, 0);
        renderer.render(scene, camera);
      };
      const resize = () => {
        const { clientWidth: width, clientHeight: height } = element;
        if (!width || !height) return;
        renderer.setSize(width, height, false);
        camera.aspect = width / height;
        camera.updateProjectionMatrix();
        draw();
      };
      let last: { x: number; y: number } | null = null;
      const down = (event: PointerEvent) => {
        last = { x: event.clientX, y: event.clientY };
        renderer.domElement.setPointerCapture?.(event.pointerId);
      };
      const move = (event: PointerEvent) => {
        if (!last) return;
        view = look(view, event.clientX - last.x, event.clientY - last.y);
        last = { x: event.clientX, y: event.clientY };
        draw();
      };
      const up = () => {
        last = null;
      };
      const canvas = renderer.domElement;
      canvas.addEventListener("pointerdown", down);
      canvas.addEventListener("pointermove", move);
      canvas.addEventListener("pointerup", up);
      canvas.addEventListener("pointercancel", up);
      element.replaceChildren(canvas);
      const observer = new ResizeObserver(resize);
      observer.observe(element);
      resize();
      cleanup = () => {
        observer.disconnect();
        texture.dispose();
        renderer.dispose();
        canvas.remove();
      };
      ready.current();
    })();
    return () => {
      disposed = true;
      cleanup();
    };
  }, [src]);

  return failed ? (
    <p role="alert" className="panorama panorama-failed">
      The panorama couldn’t be loaded.
    </p>
  ) : (
    <figure
      className="panorama"
      ref={host}
      aria-label="Panorama of the location. Drag to look around."
    />
  );
}
