import { useEffect, useRef, useState } from "react";
import type { SkinViewer } from "skinview3d";
import { loadSkin } from "./skins";

export function SkinPreview({ name, uuid }: { name: string; uuid: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const container = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<SkinViewer | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "failed">("loading");

  useEffect(() => {
    let active = true;
    let viewer: SkinViewer | undefined;
    let observer: ResizeObserver | undefined;
    const render = () => {
      if (active && viewer && !document.hidden) viewer.render();
    };
    const release = () => {
      viewer?.controls.removeEventListener("change", render);
      viewer?.dispose();
      viewer?.composer.dispose();
      viewer?.renderer.forceContextLoss();
    };
    async function load() {
      try {
        const skin = await loadSkin(uuid);
        if (!skin) throw new Error("Skin unavailable");
        if (!active) return;
        const { SkinViewer } = await import("skinview3d");
        if (!active || !canvas.current || !container.current) return;
        viewer = new SkinViewer({
          canvas: canvas.current,
          width: container.current.clientWidth,
          height: 250,
          pixelRatio: Math.min(window.devicePixelRatio || 1, 2),
          renderPaused: true,
          preserveDrawingBuffer: true,
          zoom: 0.8,
        });
        viewerRef.current = viewer;
        viewer.controls.enablePan = false;
        viewer.controls.enableDamping = false;
        viewer.controls.minDistance = 35;
        viewer.controls.maxDistance = 100;
        viewer.controls.minPolarAngle = Math.PI / 5;
        viewer.controls.maxPolarAngle = (Math.PI * 4) / 5;
        viewer.playerObject.rotation.y = 0.35;
        viewer.controls.addEventListener("change", render);
        await viewer.loadSkin(skin.image, { model: skin.model });
        // loadSkin resolves asynchronously; if unmounted, release any late texture as well.
        if (!active) {
          viewer.resetSkin();
          return;
        }
        observer = new ResizeObserver(() => {
          if (active && container.current && viewer) {
            viewer.setSize(container.current.clientWidth, 250);
            render();
          }
        });
        observer.observe(container.current);
        document.addEventListener("visibilitychange", render);
        setState("ready");
        render();
      } catch {
        if (active) {
          release();
          viewer = undefined;
          viewerRef.current = null;
          setState("failed");
        }
      }
    }
    void load();
    return () => {
      active = false;
      observer?.disconnect();
      document.removeEventListener("visibilitychange", render);
      release();
      viewerRef.current = null;
    };
  }, [uuid]);

  function reset() {
    const viewer = viewerRef.current;
    if (!viewer) return;
    viewer.playerObject.rotation.y = 0.35;
    viewer.playerObject.rotation.x = 0;
    viewer.zoom = 0.8;
    viewer.resetCameraPose();
    viewer.controls.update();
    viewer.render();
  }

  return (
    <div className="skin-preview">
      <div className="skin-canvas-container" ref={container}>
        <canvas
          ref={canvas}
          className={state === "ready" ? "" : "skin-hidden"}
          tabIndex={state === "ready" ? 0 : -1}
          role="img"
          aria-label={`3D skin of ${name}. Drag to rotate, scroll to zoom. Arrow keys rotate; plus and minus zoom; Home resets.`}
          onKeyDown={(event) => {
            const viewer = viewerRef.current;
            if (!viewer) return;
            if (event.key === "Home") {
              event.preventDefault();
              reset();
              return;
            }
            if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
              event.preventDefault();
              viewer.playerObject.rotation.y +=
                event.key === "ArrowLeft" ? -0.2 : 0.2;
            } else if (event.key === "ArrowUp" || event.key === "ArrowDown") {
              event.preventDefault();
              viewer.playerObject.rotation.x = Math.max(
                -0.5,
                Math.min(
                  0.5,
                  viewer.playerObject.rotation.x +
                    (event.key === "ArrowUp" ? -0.1 : 0.1),
                ),
              );
            } else if (["+", "=", "-"].includes(event.key)) {
              event.preventDefault();
              viewer.zoom = Math.min(
                1.3,
                Math.max(0.55, viewer.zoom + (event.key === "-" ? -0.1 : 0.1)),
              );
            } else return;
            viewer.render();
          }}
        />
        {state !== "ready" && (
          <p className="skin-message" role="status">
            {state === "loading"
              ? "Loading skin…"
              : "Skin preview unavailable."}
          </p>
        )}
      </div>
    </div>
  );
}
