import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import MvpControls from './MvpControls';
import './index.css';

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
    <MvpControls />
  </React.StrictMode>,
);
