import { ImageOff } from "lucide-react";
import { memo, useState } from "react";

/** Product image via the finora-media proxy, with a quiet placeholder when missing or broken. */
export const ProductThumb = memo(function ProductThumb({
  src,
  size = 44,
}: {
  src: string | null;
  size?: number;
}) {
  const [failed, setFailed] = useState(false);
  return (
    <span
      className="grid shrink-0 place-items-center overflow-hidden rounded-[10px] bg-surface-sunken ring-1 ring-line/60"
      style={{ width: size * 1.35, height: size }}
    >
      {src && !failed ? (
        <img
          src={src}
          alt=""
          loading="lazy"
          decoding="async"
          className="h-full w-full object-cover"
          onError={() => setFailed(true)}
        />
      ) : (
        <ImageOff size={size * 0.38} className="text-ink-faint" aria-hidden />
      )}
    </span>
  );
});
