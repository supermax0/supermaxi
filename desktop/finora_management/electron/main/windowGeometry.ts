export function windowGeometry(area: { width: number; height: number }) {
  const width = Math.max(1, Math.floor(area.width));
  const height = Math.max(1, Math.floor(area.height));
  return {
    width: Math.min(1440, width),
    height: Math.min(900, height),
    minWidth: Math.min(760, width),
    minHeight: Math.min(480, height),
  };
}
