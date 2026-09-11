import React from 'react';
import { createRoot } from 'react-dom/client';
import AppV3 from './AppV3Entry';
import ReweCatalogControl from './ReweCatalogControl';
import './index.css';

if ('serviceWorker' in navigator && import.meta.env.PROD) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => undefined);
  });
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AppV3 />
    <ReweCatalogControl />
  </React.StrictMode>,
);
