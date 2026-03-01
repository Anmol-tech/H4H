import './Sponsors.css';

export default function Sponsors() {
    return (
        <footer className="sponsors">
            <span className="sponsors-label">Sponsors</span>
            <div className="sponsors-logos">
                <div className="sponsor-item">
                    <span className="sponsor-icon">
                        <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 14H9V8h2v8zm4 0h-2V8h2v8z" /></svg>
                    </span>
                    ElevenLabs
                </div>

                <div className="sponsor-item">
                    <span className="sponsor-icon">
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><path d="M3 3l8 9-8 9h4l8-9-8-9H3zm8 0l8 9-8 9h4l8-9-8-9h-4z" /></svg>
                    </span>
                    AMD
                </div>

            </div>
        </footer>
    );
}
