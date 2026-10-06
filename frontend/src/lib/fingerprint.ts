export function getFingerprint() {
  const nav = navigator;
  const components = {
    user_agent: nav.userAgent,
    language: nav.language,
    platform: nav.platform,
    screen: `${screen.width}x${screen.height}x${screen.colorDepth}`,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    cores: nav.hardwareConcurrency ?? 0,
  };
  const raw = Object.values(components).join("|");
  let hash = 0;
  for (let i = 0; i < raw.length; i++) {
    hash = (Math.imul(31, hash) + raw.charCodeAt(i)) | 0;
  }
  return {
    fingerprint_id: Math.abs(hash).toString(16),
    fingerprint_components: components,
  };
}
