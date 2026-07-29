import { useCallback, useEffect, useState } from 'react';
import { Route, Routes, useLocation } from 'react-router';
import Navbar from './components/Navbar';
import './App.css';
import Chat from './pages/Chat';
import Lore from './pages/Lore';
import LoreChat from './pages/LoreChat';
import SessionSetup from './pages/SessionSetup';
import Characters from './pages/Characters';
import Campaigns from './pages/Campaigns';
import CampaignDetail from './pages/CampaignDetail';
import CreateCampaign from './pages/CreateCampaign';
import CharacterMemories from './pages/CharacterMemories';
import NPCBuilderChat from './pages/NPCBuilderChat';
import CampaignAdminChat from './pages/CampaignAdminChat';
import CampaignNegotiationChat from './pages/CampaignNegotiationChat';

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
        <Route path="/lore" element={<Lore />} />
        <Route path="/lore-chat" element={<LoreChat />} />
        <Route path="/characters" element={<Characters />} />
        <Route path="/npc-builder" element={<NPCBuilderChat />} />
        <Route path="/campaigns" element={<Campaigns />} />
        <Route path="/campaigns/new" element={<CreateCampaign />} />
        <Route path="/campaigns/:id" element={<CampaignDetail />} />
        <Route path="/campaign-admin" element={<CampaignAdminChat />} />
        <Route path="/campaign-negotiation" element={<CampaignNegotiationChat />} />
        <Route path="/campaigns/:campaignId/npcs/:npcId/memories" element={<CharacterMemories />} />
      </Routes>
    </div>
  );
}

export default App;