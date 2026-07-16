"use client";

import React, { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { getApiUrl } from "@/lib/api";
import { Upload, FileText, ArrowLeft, RefreshCw, AlertCircle, CheckCircle } from "lucide-react";

interface Document {
  id: string;
  filename: string;
  status: "pending" | "processing" | "ready" | "failed";
  created_at: string;
  error_message?: string;
}

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [dragActive, setDragActive] = useState(false);
  const { token, logout } = useAuth();
  const router = useRouter();

  const fetchDocuments = useCallback(async () => {
    if (!token) return;
    try {
      const res = await fetch(getApiUrl("/documents"), {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 401) {
        logout();
        return;
      }
      if (res.ok) {
        const data = await res.json();
        setDocuments(data);
      }
    } catch (err) {
      console.error("Error fetching documents:", err);
    }
  }, [token, logout]);

  // Redirect to login if not authenticated
  useEffect(() => {
    if (!token) {
      router.push("/auth/login");
    } else {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      fetchDocuments();
    }
  }, [token, router, fetchDocuments]);

  // Poll for document status updates while items are not finalized
  useEffect(() => {
    if (!token) return;
    const interval = setInterval(() => {
      const hasUnfinished = documents.some(
        (doc) => doc.status === "pending" || doc.status === "processing"
      );
      if (hasUnfinished || documents.length === 0) {
        fetchDocuments();
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [documents, token, fetchDocuments]);

  const handleUploadFile = async (file: File) => {
    if (!token) return;
    setError("");
    setUploading(true);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch(getApiUrl("/documents/upload"), {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Upload failed");
      }

      await fetchDocuments();
    } catch (err) {
      setError((err as Error).message || "An error occurred during file upload.");
    } finally {
      setUploading(false);
    }
  };

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      handleUploadFile(e.target.files[0]);
    }
  };

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleUploadFile(e.dataTransfer.files[0]);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      {/* Header */}
      <header className="border-b border-slate-800 bg-slate-900/50 backdrop-blur-md px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link href="/chat" className="text-slate-400 hover:text-white flex items-center gap-1 text-sm transition">
              <ArrowLeft size={16} /> Back to Chat
            </Link>
            <h1 className="text-xl font-bold bg-gradient-to-r from-indigo-400 to-violet-400 bg-clip-text text-transparent">
              Knowledge Base
            </h1>
          </div>
          <button onClick={fetchDocuments} className="text-slate-400 hover:text-white p-2 transition">
            <RefreshCw size={18} />
          </button>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-10 space-y-10">
        {/* Error notification */}
        {error && (
          <div className="rounded-lg bg-red-950/50 border border-red-950 p-4 text-sm text-red-400 flex items-start gap-3">
            <AlertCircle className="shrink-0 mt-0.5" size={16} />
            <span>{error}</span>
          </div>
        )}

        {/* Ingestion upload dropzone */}
        <div
          onDragEnter={handleDrag}
          onDragOver={handleDrag}
          onDragLeave={handleDrag}
          onDrop={handleDrop}
          className={`flex flex-col items-center justify-center border-2 border-dashed rounded-xl p-10 transition duration-150 ${
            dragActive
              ? "border-indigo-500 bg-indigo-950/10"
              : "border-slate-800 bg-slate-900/20 hover:border-slate-700"
          }`}
        >
          <Upload className="text-indigo-400 mb-4 animate-bounce" size={40} />
          <h3 className="text-lg font-semibold text-white mb-1">
            {uploading ? "Uploading document..." : "Drag and drop your file here"}
          </h3>
          <p className="text-sm text-slate-400 mb-6 text-center max-w-xs">
            Supports PDF, DOCX, or TXT formats (up to 20MB)
          </p>

          <label className="cursor-pointer rounded-lg bg-indigo-600 hover:bg-indigo-500 px-4 py-2.5 text-sm font-semibold text-white transition duration-150">
            Select File
            <input type="file" accept=".pdf,.docx,.txt" className="hidden" onChange={handleFileInput} disabled={uploading} />
          </label>
        </div>

        {/* Uploaded Documents List */}
        <div className="space-y-4">
          <h2 className="text-lg font-semibold text-white">Your Documents</h2>

          {documents.length === 0 ? (
            <div className="rounded-xl border border-slate-800 bg-slate-900/10 p-8 text-center text-slate-400">
              No documents uploaded yet. Upload a file above to get started.
            </div>
          ) : (
            <div className="divide-y divide-slate-800 rounded-xl border border-slate-800 bg-slate-900/20 overflow-hidden">
              {documents.map((doc) => (
                <div key={doc.id} className="flex items-center justify-between p-4 bg-slate-900/10 hover:bg-slate-900/30 transition">
                  <div className="flex items-center gap-3 min-w-0">
                    <FileText className="text-slate-400 shrink-0" size={20} />
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-white truncate">{doc.filename}</p>
                      <p className="text-xs text-slate-400">
                        Uploaded {new Date(doc.created_at).toLocaleString()}
                      </p>
                      {doc.error_message && (
                        <p className="text-xs text-red-400 mt-1 font-mono">{doc.error_message}</p>
                      )}
                    </div>
                  </div>

                  <div>
                    {doc.status === "ready" && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-green-500/10 px-2.5 py-0.5 text-xs font-medium text-green-400">
                        <CheckCircle size={12} /> Ready
                      </span>
                    )}
                    {doc.status === "failed" && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-red-500/10 px-2.5 py-0.5 text-xs font-medium text-red-400">
                        <AlertCircle size={12} /> Failed
                      </span>
                    )}
                    {(doc.status === "pending" || doc.status === "processing") && (
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-500/10 px-2.5 py-0.5 text-xs font-medium text-amber-400 animate-pulse">
                        <RefreshCw className="animate-spin" size={10} /> {doc.status === "pending" ? "Pending" : "Processing"}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
