import React from 'react';
import { createRoot } from 'react-dom/client';
import AppV2 from './AppV2';
import MvpControls from './MvpControls';
import './index.css';

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AppV2 />
    <MvpControls />
  </React.StrictMode>,
);
