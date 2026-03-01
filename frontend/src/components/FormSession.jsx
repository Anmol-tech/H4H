import { useEffect, useRef, useState } from 'react';
import { femaForm } from '../data/mockData';
import './FormSession.css';

// Mock answers for demo purposes
const MOCK_ANSWERS = {
    applicant_name: 'Sid Johnson',
    date_of_birth: 'March 15, 1990',
    ssn: '***-**-1234',
    mailing_address: '1234 Oak Street, Austin, TX 78701',
    phone_number: '(512) 555-0147',
    disaster_type: 'Hurricane',
    damaged_property_address: '1234 Oak Street, Austin, TX 78701',
    has_insurance: 'No',
};

export default function FormSession({ pdfUrl, fileName, liveAnswers, analyzedQuestions, isAnalyzing, analyzeError }) {
    const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';
    const [currentIndex, setCurrentIndex] = useState(0);
    const [answers, setAnswers] = useState({});
    const [phase, setPhase] = useState('asking'); // asking | confirming | complete
    const [isListening, setIsListening] = useState(false);
    const [uploadingAudio, setUploadingAudio] = useState(false);
    const [audioError, setAudioError] = useState('');

    const mediaRecorderRef = useRef(null);
    const chunksRef = useRef([]);

    // Use VLM-analyzed questions when available, fallback to mock FEMA template
    const questions = analyzedQuestions && analyzedQuestions.length > 0
        ? analyzedQuestions.map((q) => ({
            id: q.id,
            label: q.prompt || q.label,
            fieldName: q.field_name,
            type: q.type,
            options: q.options || null, // for checkbox/choice fields
        }))
        : femaForm.questions;

    const current = questions[currentIndex];
    const totalQuestions = questions.length;
    const progress = ((Object.keys(answers).length) / totalQuestions) * 100;

    // Reset when questions change (new analysis result)
    useEffect(() => {
        setCurrentIndex(0);
        setAnswers({});
        setPhase('asking');
    }, [analyzedQuestions]);

    // Merge live answers coming from backend in real time
    useEffect(() => {
        if (!liveAnswers) return;
        setAnswers((prev) => ({ ...prev, ...liveAnswers }));
    }, [liveAnswers]);

    const uploadAudio = async (file) => {
        setUploadingAudio(true);
        setAudioError('');
        try {
            const form = new FormData();
            form.append('file', file);
            const res = await fetch(`${API_BASE}/upload/audio`, {
                method: 'POST',
                body: form,
            });
            if (!res.ok) {
                throw new Error('Upload failed');
            }
            // You can use the returned URL for ASR or storage if needed
            await res.json();
        } catch (err) {
            console.error(err);
            setAudioError('Audio upload failed. Please try again.');
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
                const blob = new Blob(chunksRef.current, { type: 'audio/mpeg' });
                const file = new File([blob], 'recording.mp3', { type: 'audio/mpeg' });
                stream.getTracks().forEach((t) => t.stop());
                setIsListening(false);
                setPhase('confirming');
                await uploadAudio(file);
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
            const mockAnswer = MOCK_ANSWERS[current.fieldName] || 'Sample Answer';
            setAnswers((prev) => ({ ...prev, [current.fieldName]: mockAnswer }));

            if (currentIndex < totalQuestions - 1) {
                setCurrentIndex((prev) => prev + 1);
                setPhase('asking');
            } else {
                setPhase('complete');
            }
        } else {
            // Retry
            setPhase('asking');
        }
    };

    const handleReplay = () => {
        // Would replay the audio question — for now it's a no-op
    };

    const handleNextField = () => {
        if (phase === 'asking') {
            // Simulate answering and go to confirm
            setPhase('confirming');
        }
    };

    const getMockAnswer = () => MOCK_ANSWERS[current?.fieldName] || 'Sample Answer';

    return (
        <div className="form-session">
            {/* Left: PDF Preview */}
            <div className="pdf-preview">
                <div className="pdf-document">
                    <div className="pdf-header">
                        <div className="pdf-agency-logo">{femaForm.agency}</div>
                        <div className="pdf-header-text">
                            <h2>{fileName || femaForm.title}</h2>
                            <p>{fileName ? 'Uploaded PDF' : femaForm.subtitle}</p>
                        </div>
                    </div>
                    {pdfUrl ? (
                        <div className="pdf-iframe-wrapper">
                            <div className="pdf-iframe-bar">
                                <span>Uploaded PDF Preview</span>
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
                    ) : (
                        <p className="pdf-description">
                            The FEMA Disaster Aid application is used to apply for Individual Assistance
                            including housing assistance and other disaster-related needs. Complete all
                            applicable fields. Assistance is available regardless of immigration status.
                        </p>
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
                        <p className="voice-confirmation-value">"{getMockAnswer()}"</p>
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
                            {isListening ? 'Listening...' : 'Speak your answer now'}
                            {uploadingAudio && ' (Uploading...)'}
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
                            <button className="voice-action-btn" onClick={handleReplay}>
                                🔁 Replay Question
                            </button>
                            <button className="voice-action-btn primary" onClick={handleNextField}>
                                Next Field →
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
