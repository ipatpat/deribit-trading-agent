import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import PageContextProvider from './contexts/PageContextProvider';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <PageContextProvider>
        <App />
      </PageContextProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
