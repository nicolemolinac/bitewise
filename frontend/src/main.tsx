import React from 'react';
import { createRoot } from 'react-dom/client';
import AppV3 from './AppV3Entry';
import MvpControls from './MvpControls';
import './index.css';

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AppV3 />
    <MvpControls />
  </React.StrictMode>,
);
