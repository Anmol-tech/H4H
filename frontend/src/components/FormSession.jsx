import { useEffect, useMemo, useRef, useState } from 'react';
import { femaForm } from '../data/mockData';
import './FormSession.css';

export default function FormSession({ pdfUrl, fileName, liveAnswers, analyzedQuestions, isAnalyzing, analyzeError }) {
    const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';
    const [currentIndex, setCurrentIndex] = useState(0);
    const [answers, setAnswers] = useState({});
    const [phase, setPhase] = useState('asking'); // asking | confirming | complete
    const [isListening, setIsListening] = useState(false);
    const [uploadingAudio, setUploadingAudio] = useState(false);
    const [audioError, setAudioError] = useState('');
    const [lastTranscript, setLastTranscript] = useState('');

    const mediaRecorderRef = useRef(null);
    const chunksRef = useRef([]);
    const audioRef = useRef(null);  // track current TTS audio element

    // Helper: play a question's TTS audio (retries once if file isn't ready yet)
    const playQuestionAudio = (audioUrl, retries = 3) => {
        if (!audioUrl) return;
        if (audioRef.current) {
            audioRef.current.pause();
            audioRef.current.currentTime = 0;
        }
        const audio = new Audio(`${API_BASE}${audioUrl}`);
        audioRef.current = audio;
        audio.onerror = () => {
            // File may still be generating in background — retry after a short delay
            if (retries > 0) {
                setTimeout(() => playQuestionAudio(audioUrl, retries - 1), 2000);
            }
        };
        audio.play().catch(() => { /* autoplay blocked — user gesture required */ });
    };

    // Use VLM-analyzed questions when available, fallback to mock FEMA template
    const questions = useMemo(() =>
        analyzedQuestions && analyzedQuestions.length > 0
            ? analyzedQuestions.map((q) => ({
                id: q.id,
                label: q.prompt || q.label,
                fieldName: q.field_name,
                type: q.type,
                options: q.options || null,
                audioUrl: q.audio_url || null,
            }))
            : femaForm.questions,
        [analyzedQuestions]
    );

    const current = questions[currentIndex];
    const totalQuestions = questions.length;
    const progress = ((Object.keys(answers).length) / totalQuestions) * 100;

    // Auto-play question audio exactly once when the current question changes
    const lastPlayedIndexRef = useRef(-1);
    useEffect(() => {
        const audioUrl = questions[currentIndex]?.audioUrl;
        if (audioUrl && lastPlayedIndexRef.current !== currentIndex) {
            lastPlayedIndexRef.current = currentIndex;
            playQuestionAudio(audioUrl);
        }
    }, [currentIndex, questions]);

    // Stop audio when resetting (new form loaded)
    useEffect(() => {
        lastPlayedIndexRef.current = -1;
        if (audioRef.current) {
            audioRef.current.pause();
            audioRef.current = null;
        }
    }, [analyzedQuestions]);

    // Reset when questions change (new analysis result)
    useEffect(() => {
        setCurrentIndex(0);
        setAnswers({});
        setPhase('asking');
        setLastTranscript('');
    }, [analyzedQuestions]);

    // Merge live answers coming from backend in real time
    useEffect(() => {
        if (!liveAnswers) return;
        setAnswers((prev) => ({ ...prev, ...liveAnswers }));
    }, [liveAnswers]);

    const transcribeAudio = async (file) => {
        setUploadingAudio(true);
        setAudioError('');
        try {
            const form = new FormData();
            form.append('file', file);
            const res = await fetch(`${API_BASE}/upload/transcribe`, {
                method: 'POST',
                body: form,
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || 'Transcription failed');
            }
            const data = await res.json();
            const transcript = data.transcript || '';
            setLastTranscript(transcript);
            setPhase('confirming');
        } catch (err) {
            console.error(err);
            setAudioError(`Transcription failed: ${err.message}`);
            setPhase('asking');
        } finally {
            setUploadingAudio(false);
        }
    };

    const stopRecording = () => {
        if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
            mediaRecorderRef.current.stop();
        }
    };

    const handleMicClick = async () => {
        if (phase !== 'asking') return;

        if (isListening) {
            stopRecording();
            return;
        }

        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            const recorder = new MediaRecorder(stream);
            chunksRef.current = [];
            recorder.ondataavailable = (e) => {
                if (e.data.size > 0) chunksRef.current.push(e.data);
            };
            recorder.onstop = async () => {
                // Use the actual MIME type the recorder produces (usually webm/opus)
                const mimeType = recorder.mimeType || 'audio/webm';
                const ext = mimeType.includes('webm') ? 'webm' : mimeType.includes('mp4') ? 'm4a' : mimeType.includes('ogg') ? 'ogg' : 'webm';
                const blob = new Blob(chunksRef.current, { type: mimeType });
                const file = new File([blob], `recording.${ext}`, { type: mimeType });
                stream.getTracks().forEach((t) => t.stop());
                setIsListening(false);
                await transcribeAudio(file);
            };
            mediaRecorderRef.current = recorder;
            recorder.start();
            setIsListening(true);
        } catch (err) {
            console.error(err);
            setAudioError('Microphone access denied or not available.');
        }
    };

    const handleConfirm = (confirmed) => {
        if (confirmed) {
            setAnswers((prev) => ({ ...prev, [current.fieldName]: lastTranscript }));

            if (currentIndex < totalQuestions - 1) {
                setCurrentIndex((prev) => prev + 1);
                setPhase('asking');
                setLastTranscript('');
            } else {
                setPhase('complete');
            }
        } else {
            // Retry
            setPhase('asking');
            setLastTranscript('');
        }
    };

    const handleReplay = () => {
        if (current && current.audioUrl) {
            playQuestionAudio(current.audioUrl);
        }
    };

    const handlePrevField = () => {
        if (currentIndex > 0) {
            setCurrentIndex((prev) => prev - 1);
            setPhase('asking');
            setLastTranscript('');
            setAudioError('');
        }
    };

    const handleNextField = () => {
        if (phase === 'asking') {
            // Skip this field
            setAnswers((prev) => ({ ...prev, [current.fieldName]: '' }));
            if (currentIndex < totalQuestions - 1) {
                setCurrentIndex((prev) => prev + 1);
            } else {
                setPhase('complete');
            }
        }
    };

    const activeFieldRef = useRef(null);

    // Auto-scroll the active field into view
    useEffect(() => {
        if (activeFieldRef.current) {
            activeFieldRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }, [currentIndex]);

    const getTranscript = () => lastTranscript || '(no speech detected)';

    return (
        <div className="form-session">
            {/* Left: Dynamic Live Form */}
            <div className="pdf-preview">
                <div className="pdf-document">
                    <div className="pdf-header">
                        <div className="pdf-agency-logo">{femaForm.agency}</div>
                        <div className="pdf-header-text">
                            <h2>{fileName || femaForm.title}</h2>
                            <p>{fileName ? 'Uploaded PDF' : femaForm.subtitle}</p>
                        </div>
                    </div>

                    {/* Live form fields */}
                    <div className="live-form">
                        <div className="live-form-header">
                            <span className="live-form-badge">Live Preview</span>
                            <span className="live-form-count">
                                {Object.values(answers).filter(v => v).length} / {totalQuestions} filled
                            </span>
                        </div>
                        <div className="live-form-fields">
                            {questions.map((q, idx) => {
                                const isCurrent = idx === currentIndex && phase !== 'complete';
                                const answer = answers[q.fieldName];
                                const isFilled = answer !== undefined && answer !== '';
                                const isSkipped = answer === '';

                                return (
                                    <div
                                        key={q.id}
                                        ref={isCurrent ? activeFieldRef : null}
                                        className={`live-field ${isCurrent ? 'live-field--active' : ''} ${isFilled ? 'live-field--filled' : ''} ${isSkipped && !isCurrent ? 'live-field--skipped' : ''}`}
                                        onClick={() => {
                                            if (phase !== 'complete') {
                                                setCurrentIndex(idx);
                                                setPhase('asking');
                                                setLastTranscript('');
                                                setAudioError('');
                                            }
                                        }}
                                    >
                                        <div className="live-field-label">
                                            <span className="live-field-num">{q.id}</span>
                                            <span className="live-field-name">{q.label}</span>
                                            {isFilled && <span className="live-field-check">✓</span>}
                                        </div>
                                        <div className={`live-field-value ${isCurrent && isListening ? 'live-field-value--listening' : ''}`}>
                                            {isCurrent && phase === 'confirming'
                                                ? lastTranscript || '...'
                                                : isFilled
                                                    ? answer
                                                    : isCurrent
                                                        ? (isListening ? 'Listening...' : uploadingAudio ? 'Transcribing...' : '—')
                                                        : '—'
                                            }
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </div>

                    {/* Collapsible PDF preview */}
                    {pdfUrl && (
                        <details className="pdf-collapse">
                            <summary className="pdf-collapse-summary">
                                📄 View Original PDF
                            </summary>
                            <div className="pdf-iframe-wrapper">
                                <div className="pdf-iframe-bar">
                                    <span>Uploaded PDF</span>
                                    <a href={pdfUrl} target="_blank" rel="noreferrer" className="pdf-open-link">
                                        Open in new tab ↗
                                    </a>
                                </div>
                                <iframe
                                    title="Uploaded PDF Preview"
                                    src={pdfUrl}
                                    className="pdf-iframe"
                                />
                            </div>
                        </details>
                    )}
                </div>
            </div>

            {/* Right: Voice Panel */}
            <div className="voice-panel">
                {analyzedQuestions && analyzedQuestions.length > 0 && phase === 'asking' && currentIndex === 0 && (
                    <div className="analysis-success-banner">
                        ✓ Found {analyzedQuestions.length} fields in your form
                    </div>
                )}
                {isAnalyzing ? (
                    <div className="voice-analyzing">
                        <div className="analyzing-spinner"></div>
                        <h2 className="analyzing-title">Analyzing your form...</h2>
                        <p className="analyzing-subtitle">
                            Our AI is reading each page and creating simple questions for you.
                        </p>
                    </div>
                ) : analyzeError && (!analyzedQuestions || analyzedQuestions.length === 0) ? (
                    <div className="voice-analyzing">
                        <h2 className="analyzing-title">⚠️ Analysis Issue</h2>
                        <p className="analyzing-subtitle">{analyzeError}</p>
                        <p className="analyzing-subtitle">Using default form questions instead.</p>
                    </div>
                ) : phase === 'complete' ? (
                    <div className="voice-complete">
                        <div className="complete-icon">
                            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                                <polyline points="20 6 9 17 4 12" />
                            </svg>
                        </div>
                        <h2 className="complete-title">Form Complete!</h2>
                        <p className="complete-subtitle">
                            All {totalQuestions} fields have been filled successfully.
                        </p>
                        <button className="download-btn">
                            <span style={{ marginRight: '0.5rem' }}>📄</span>
                            Download Filled PDF
                        </button>
                    </div>
                ) : phase === 'confirming' ? (
                    <div className="voice-confirmation">
                        <p className="voice-confirmation-heard">I heard:</p>
                        <p className="voice-confirmation-value">"{getTranscript()}"</p>
                        {uploadingAudio && <p className="voice-transcribing">Transcribing...</p>}
                        <p className="voice-confirmation-prompt">Is that correct?</p>
                        <div className="confirm-actions">
                            <button className="confirm-btn yes" onClick={() => handleConfirm(true)}>
                                ✓ Yes
                            </button>
                            <button className="confirm-btn no" onClick={() => handleConfirm(false)}>
                                ✗ No
                            </button>
                        </div>
                    </div>
                ) : (
                    <>
                        {/* Avatar */}
                        <div className="voice-avatar">
                            <svg viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.5">
                                <circle cx="12" cy="8" r="4" />
                                <path d="M6 21v-2a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v2" />
                            </svg>
                        </div>

                        <span className="voice-question-number">
                            Question {current.id}:
                        </span>

                        <h2 className="voice-question-text">{current.label}</h2>

                        {current.options && current.options.length > 0 && (
                            <div className="voice-options">
                                <p className="voice-options-label">
                                    {current.type === 'checkbox' ? 'Select all that apply:' : 'Choose one:'}
                                </p>
                                <ul className="voice-options-list">
                                    {current.options.map((opt, idx) => (
                                        <li key={idx}>{opt}</li>
                                    ))}
                                </ul>
                            </div>
                        )}

                        <p className="voice-instruction">
                            {isListening ? 'Listening...' : uploadingAudio ? 'Transcribing your answer...' : 'Speak your answer now'}
                        </p>
                        {audioError && <p className="voice-error">{audioError}</p>}

                        {/* Mic Button */}
                        <div className="mic-button-wrapper">
                            <button
                                className={`mic-button ${isListening ? 'listening' : ''}`}
                                onClick={handleMicClick}
                                aria-label={isListening ? 'Stop recording' : 'Start recording'}
                            >
                                <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                                    <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                                    <line x1="12" y1="19" x2="12" y2="23" />
                                    <line x1="8" y1="23" x2="16" y2="23" />
                                </svg>
                            </button>
                            <div className="mic-pulse-ring"></div>
                            <div className="mic-pulse-ring"></div>
                            <div className="mic-pulse-ring"></div>
                        </div>

                        {/* Actions */}
                        <div className="voice-actions">
                            <button
                                className="voice-action-btn"
                                onClick={handlePrevField}
                                disabled={currentIndex === 0}
                            >
                                ← Previous
                            </button>
                            <button className="voice-action-btn" onClick={handleReplay}>
                                🔁 Replay
                            </button>
                            <button className="voice-action-btn primary" onClick={handleNextField}>
                                Skip →
                            </button>
                        </div>
                    </>
                )}

                {/* Progress bar */}
                <div className="voice-progress">
                    <div className="voice-progress-fill" style={{ width: `${progress}%` }}></div>
                </div>
            </div>
        </div>
    );
}
