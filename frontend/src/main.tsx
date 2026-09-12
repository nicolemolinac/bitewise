import React from 'react';
import { createRoot } from 'react-dom/client';
import AppV3 from './AppV3Entry';
import MvpControls from './MvpControls';
import ReweCatalogControl from './ReweCatalogControl';
import './index.css';

if ('serviceWorker' in navigator) {
  if (import.meta.env.PROD) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js').catch(() => undefined);
    });
  } else {
    // Local development must always show the latest Vite bundle. Remove any old
    // production PWA worker that may still be controlling localhost.
    navigator.serviceWorker.getRegistrations()
      .then(registrations => Promise.all(registrations.map(registration => registration.unregister())))
      .catch(() => undefined);
  }
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AppV3 />
    <MvpControls />
    <ReweCatalogControl />
  </React.StrictMode>,
);
