import './Header.css';

export default function Header({ activeSession, onLogoClick }) {
    return (
        <>
            <header className="header">
                <div className="header-logo" onClick={onLogoClick}>
                    <div className="header-logo-icon">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                            <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                            <line x1="12" y1="19" x2="12" y2="23" />
                            <line x1="8" y1="23" x2="16" y2="23" />
                        </svg>
                    </div>
                    <div className="header-logo-text">
                        Form<span>Whisper</span>
                    </div>
                </div>

                <nav className="header-nav">
                    {activeSession && (
                        <button className="btn btn-outline" style={{ fontSize: '0.8rem', padding: '0.4rem 1rem' }}>
                            Log in
                        </button>
                    )}
                    <button className="btn btn-primary">Sign Up</button>
                </nav>
            </header>

            {activeSession && (
                <div className="session-banner">
                    <span className="session-banner-dot"></span>
                    Active Session: {activeSession}
                </div>
            )}
        </>
    );
}
