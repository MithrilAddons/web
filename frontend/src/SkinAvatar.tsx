import { useEffect, useState } from "react";
import { loadSkin } from "./skins";

export function SkinAvatar({
  name,
  uuid,
  image,
  className,
}: Readonly<{
  name: string;
  uuid?: string;
  image?: string | null;
  className: string;
}>) {
  const [loaded, setLoaded] = useState<{
    uuid: string;
    image: string | null;
  }>();
  const [failed, setFailed] = useState<string>();
  useEffect(() => {
    if (!uuid || image !== undefined) return;
    let active = true;
    void loadSkin(uuid).then((value) => {
      if (active) setLoaded({ uuid, image: value?.image ?? null });
    });
    return () => {
      active = false;
    };
  }, [uuid, image]);
  const source = image ?? (loaded?.uuid === uuid ? loaded?.image : null);
  return (
    <span className={`${className} skin-avatar`} aria-hidden="true">
      {source && source !== failed ? (
        <>
          <img
            className="skin-face"
            src={source}
            alt=""
            onError={() => setFailed(source)}
          />
          <img className="skin-hat" src={source} alt="" />
        </>
      ) : (
        name.slice(0, 1)
      )}
    </span>
  );
}
