import { useEffect, useState } from 'react';
import Header from './components/Header';
import HomePage from './components/HomePage';
import FormSession from './components/FormSession';
import Sponsors from './components/Sponsors';
import './App.css';

function App() {
  const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

  const [view, setView] = useState('home'); // home | session
  const [activeTemplate, setActiveTemplate] = useState(null);
  const [uploadedPdf, setUploadedPdf] = useState(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState('');
  const [analyzedQuestions, setAnalyzedQuestions] = useState(null);

  useEffect(() => {
    return () => {
      if (uploadedPdf?.url?.startsWith('blob:')) URL.revokeObjectURL(uploadedPdf.url);
    };
  }, [uploadedPdf]);

  const handleSelectTemplate = (templateId) => {
    setActiveTemplate(templateId);
    setView('session');
  };

  const handlePdfUpload = async (file) => {
    if (!file) return;

    setIsUploading(true);
    setUploadError('');
    setAnalyzeError('');
    setAnalyzedQuestions(null);

    try {
      // 1. Upload the PDF
      const formData = new FormData();
      formData.append('file', file);

      const response = await fetch(`${API_BASE}/upload/pdf`, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(errorText || 'Upload failed');
      }

      const data = await response.json();
      const url = data.url?.startsWith('http') ? data.url : `${API_BASE}${data.url}`;
      const fileId = data.file_id;

      setUploadedPdf({
        name: data.original_filename || file.name,
        url,
        fileId,
      });

      setActiveTemplate(null);
      setView('session');
      setIsUploading(false);

      // 2. Analyze the form with VLM
      setIsAnalyzing(true);
      try {
        const analyzeResp = await fetch(`${API_BASE}/llm/analyze-pdf`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ file_id: fileId }),
        });

        if (!analyzeResp.ok) {
          const errText = await analyzeResp.text();
          throw new Error(errText || 'Form analysis failed');
        }

        const analyzeData = await analyzeResp.json();
        setAnalyzedQuestions(analyzeData.questions);
      } catch (err) {
        console.error('Analyze error:', err);
        setAnalyzeError('Could not analyze the form. Using default questions.');
      } finally {
        setIsAnalyzing(false);
      }
    } catch (err) {
      console.error(err);
      setUploadError('Upload failed. Please try again.');
      setIsUploading(false);
    }
  };

  const handleLogoClick = () => {
    setView('home');
    setActiveTemplate(null);
    setAnalyzedQuestions(null);
    setAnalyzeError('');
    setUploadedPdf((prev) => {
      if (prev?.url?.startsWith('blob:')) URL.revokeObjectURL(prev.url);
      return null;
    });
  };

  const getSessionName = () => {
    if (uploadedPdf?.name) return uploadedPdf.name;
    if (activeTemplate === 'fema-009-0-3') return 'FEMA Form 009-0-3';
    if (activeTemplate === 'housing-app') return 'Housing Application';
    if (activeTemplate === 'medical-intake') return 'Medical Intake Form';
    return null;
  };

  return (
    <>
      <Header
        activeSession={view === 'session' ? getSessionName() : null}
        onLogoClick={handleLogoClick}
      />

      {view === 'home' ? (
        <>
          <HomePage
            onUploadPdf={handlePdfUpload}
            onSelectTemplate={handleSelectTemplate}
            isUploading={isUploading}
            uploadError={uploadError}
          />
          <Sponsors />
        </>
      ) : (
        <FormSession
          pdfUrl={uploadedPdf?.url}
          fileName={uploadedPdf?.name}
          analyzedQuestions={analyzedQuestions}
          isAnalyzing={isAnalyzing}
          analyzeError={analyzeError}
        />
      )}
    </>
  );
}

export default App;
