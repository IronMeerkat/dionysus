import { useCallback, useEffect, useRef, useState } from "react";
import LocationModal from "./LocationModal";
import StoryBackgroundModal from "./StoryBackgroundModal";
import "./Navbar.css";
import { useNavigate } from "react-router";


interface NavbarProps {
  onToggleSidebar?: () => void;
  sidebarOpen?: boolean;
}

interface NavbarLink {
  label: string;
  onClick: () => void;
  onKeyDown: () => void;
}

const Navbar = ({ onToggleSidebar, sidebarOpen }: NavbarProps) => {
  const navigate = useNavigate();
  const [storyModalOpen, setStoryModalOpen] = useState(false);
  const [locationModalOpen, setLocationModalOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  const links: NavbarLink[] = [
    { label: "Story Background", onClick: () => setStoryModalOpen(true), onKeyDown: () => setStoryModalOpen(true) },
    { label: "Location", onClick: () => setLocationModalOpen(true), onKeyDown: () => setLocationModalOpen(true) },
    { label: "Session Setup", onClick: () => navigate("/session-setup"), onKeyDown: () => navigate("/session-setup") },
  ];

  const toPhoneLink = (link: NavbarLink) => {
    return (
      <a
        className="navbar-dropdown-item"
        role="button"
        tabIndex={0}
        onClick={() => { link.onClick(); closeMenu(); }}
        onKeyDown={(e) => { if (e.key === "Enter") { link.onClick(); closeMenu(); } }}
      >
        {link.label}
      </a>
    );
  };

  const toDesktopLink = (link: NavbarLink) => {
    return (
      <a
        className="navbar-link"
        role="button"
        tabIndex={0}
        onClick={link.onClick}
        onKeyDown={(e) => { if (e.key === "Enter") { link.onClick(); } }}
      >
        {link.label}
      </a>
    );
  };

  const closeMenu = useCallback(() => setMenuOpen(false), []);

  useEffect(() => {
    if (!menuOpen) return;
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        closeMenu();
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [menuOpen, closeMenu]);

  return (
    <>
      <nav className="navbar">
        <div className="navbar-left">
          {onToggleSidebar && (
            <button
              type="button"
              className="navbar-sidebar-toggle"
              aria-label={sidebarOpen ? "Close sidebar" : "Open sidebar"}
              onClick={onToggleSidebar}
            >
              {sidebarOpen ? "✕" : "☰"}
            </button>
          )}
          <h1 className="navbar-title">Dionysus</h1>
        </div>

        <div className="navbar-links-desktop">
          {links.map(toDesktopLink)}
        </div>

        <div className="navbar-menu-mobile" ref={menuRef}>
          <button
            type="button"
            className="navbar-hamburger"
            aria-label={menuOpen ? "Close menu" : "Open menu"}
            onClick={() => setMenuOpen((v) => !v)}
          >
            {menuOpen ? "✕" : "⋮"}
          </button>

          {menuOpen && (
            <div className="navbar-dropdown">
              {links.map(toPhoneLink)}
            </div>
          )}
        </div>
      </nav>

      <StoryBackgroundModal
        open={storyModalOpen}
        onClose={() => setStoryModalOpen(false)}
      />
      <LocationModal
        open={locationModalOpen}
        onClose={() => setLocationModalOpen(false)}
      />
    </>
  );
};

export default Navbar;
