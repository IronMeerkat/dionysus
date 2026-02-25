import { useCallback, useEffect, useState } from 'react';
import { Route, Routes, useLocation } from 'react-router';
import Navbar from './components/Navbar';
import './App.css';
import Chat from './pages/Chat';
import SessionSetup from './pages/SessionSetup';

async function loadFlyonUI() {
  return import('flyonui/flyonui');
}

function App() {
  const location = useLocation();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const toggleSidebar = useCallback(() => setSidebarOpen((v) => !v), []);

  useEffect(() => {
    const initFlyonUI = async () => {
      await loadFlyonUI();
    };
    initFlyonUI();
  }, []);

  useEffect(() => {
    setTimeout(() => {
      if (
        window.HSStaticMethods &&
        typeof window.HSStaticMethods.autoInit === 'function'
      ) {
        window.HSStaticMethods.autoInit();
      }
    }, 100);
  }, [location.pathname]);

  return (
    <div className="app-layout">
      <Navbar onToggleSidebar={toggleSidebar} sidebarOpen={sidebarOpen} />
      <Routes>
        <Route path="/" element={<Chat sidebarOpen={sidebarOpen} onToggleSidebar={toggleSidebar} />} />
        <Route path="/session-setup" element={<SessionSetup sidebarOpen={sidebarOpen} onToggleSidebar={toggleSidebar} />}/>
      </Routes>
    </div>
  );
}

export default App;