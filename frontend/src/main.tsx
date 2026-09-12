import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import AppV3 from './AppV3Entry';
import MvpControls from './MvpControls';
import ReweCatalogControl from './ReweCatalogControl';
import './index.css';

if ('serviceWorker' in navigator && import.meta.env.PROD) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => undefined);
  });
}

function DesktopTools() {
  // Detect laptop/desktop by precise pointer capability, not viewport width.
  // This keeps the tools visible even when the browser window is narrow.
  const query = '(pointer: fine)';
  const [desktop, setDesktop] = useState(() => typeof window !== 'undefined' && window.matchMedia(query).matches);

  useEffect(() => {
    const media = window.matchMedia(query);
    const update = () => setDesktop(media.matches);
    update();
    media.addEventListener?.('change', update);
    return () => media.removeEventListener?.('change', update);
  }, []);

  if (!desktop) return null;
  return (
    <>
      <MvpControls />
      <ReweCatalogControl />
    </>
  );
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AppV3 />
    <DesktopTools />
  </React.StrictMode>,
);
