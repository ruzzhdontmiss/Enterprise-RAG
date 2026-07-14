"use client";

import React, { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { Send, FileText, LogOut, ArrowRight, User as UserIcon } from "lucide-react";

interface Citation {
  document_id: string;
  filename: string;
  page_or_section: string;
  chunk_text_snippet: string;
}

interface Message {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  loading?: boolean;
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const { token, user, logout } = useAuth();
  const router = useRouter();
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Redirect to login if not authenticated
  useEffect(() => {
    if (!token) {
      router.push("/auth/login");
    }
  }, [token, router]);

  // Scroll to the bottom of the chat list on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading || !token) return;

    const userQuestion = input.trim();
    setInput("");
    setLoading(true);

    // Append user question
    const updatedMessages: Message[] = [...messages, { role: "user", content: userQuestion }];
    // Append loading bubble
    setMessages([...updatedMessages, { role: "assistant", content: "", loading: true }]);

    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

    try {
      const res = await fetch(`${apiUrl}/query`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ question: userQuestion }),
      });

      if (res.status === 401) {
        logout();
        return;
      }

      if (!res.ok) {
        throw new Error("Failed to fetch query response.");
      }

      const data = await res.json();
      
      // Update assistant response bubble
      setMessages([
        ...updatedMessages,
        {
          role: "assistant",
          content: data.answer,
          citations: data.citations || [],
        },
      ]);
    } catch (err: any) {
      setMessages([
        ...updatedMessages,
        {
          role: "assistant",
          content: "Sorry, I encountered an error processing that request. Please try again.",
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-screen bg-slate-950 text-slate-100 overflow-hidden">
      {/* Sidebar Panel */}
      <aside className="w-64 border-r border-slate-800 bg-slate-900/50 backdrop-blur-md flex flex-col justify-between p-6 shrink-0 hidden md:flex">
        <div className="space-y-6">
          <h2 className="text-xl font-bold bg-gradient-to-r from-indigo-400 to-violet-400 bg-clip-text text-transparent">
            EnterpriseRAG
          </h2>
          
          <Link href="/documents" className="flex items-center justify-between rounded-lg bg-slate-800 hover:bg-slate-700 px-4 py-3 text-sm font-semibold text-white transition">
            <span className="flex items-center gap-2">
              <FileText size={18} /> Documents
            </span>
            <ArrowRight size={16} />
          </Link>
        </div>

        <div className="border-t border-slate-800 pt-6 space-y-4">
          {user && (
            <div className="flex items-center gap-3">
              <div className="rounded-full bg-indigo-500/20 p-2 text-indigo-400">
                <UserIcon size={18} />
              </div>
              <div className="min-w-0">
                <p className="text-xs font-semibold text-white truncate">{user.email}</p>
                <p className="text-[10px] text-slate-400 uppercase tracking-widest">{user.role}</p>
              </div>
            </div>
          )}
          <button onClick={logout} className="w-full flex items-center justify-center gap-2 rounded-lg border border-slate-800 hover:bg-slate-800 px-4 py-2.5 text-sm font-semibold text-slate-400 hover:text-white transition">
            <LogOut size={16} /> Sign Out
          </button>
        </div>
      </aside>

      {/* Main Chat Workspace */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Mobile Header */}
        <header className="border-b border-slate-800 bg-slate-900/50 backdrop-blur-md px-6 py-4 flex items-center justify-between md:hidden shrink-0">
          <h1 className="text-lg font-bold text-white">EnterpriseRAG</h1>
          <div className="flex gap-4">
            <Link href="/documents" className="text-indigo-400 hover:text-indigo-300 text-sm font-semibold">
              Docs
            </Link>
            <button onClick={logout} className="text-slate-400 hover:text-white">
              <LogOut size={18} />
            </button>
          </div>
        </header>

        {/* Chat Logs Window */}
        <div className="flex-1 overflow-y-auto px-6 py-8 space-y-6">
          {messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center space-y-4 max-w-md mx-auto">
              <div className="rounded-2xl bg-indigo-500/10 p-4 text-indigo-400 mb-2">
                <FileText size={32} />
              </div>
              <h3 className="text-lg font-bold text-white">Ask your Knowledge Base</h3>
              <p className="text-sm text-slate-400">
                Submit questions regarding your uploaded document policies, benefits, guidelines, and compliance rules.
              </p>
            </div>
          ) : (
            <div className="max-w-3xl mx-auto space-y-6">
              {messages.map((msg, index) => (
                <div key={index} className={`flex flex-col ${msg.role === "user" ? "items-end" : "items-start"}`}>
                  <div className={`max-w-[85%] rounded-2xl px-5 py-3.5 text-sm shadow-md leading-relaxed ${
                    msg.role === "user"
                      ? "bg-indigo-600 text-white rounded-br-none"
                      : "bg-slate-900 border border-slate-800 text-slate-100 rounded-bl-none"
                  }`}>
                    {msg.loading ? (
                      <div className="flex gap-1 py-1.5 justify-center items-center">
                        <span className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce"></span>
                        <span className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce [animation-delay:0.2s]"></span>
                        <span className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce [animation-delay:0.4s]"></span>
                      </div>
                    ) : (
                      <p className="whitespace-pre-wrap">{msg.content}</p>
                    )}
                  </div>

                  {/* Grounding Citations */}
                  {msg.citations && msg.citations.length > 0 && (
                    <div className="max-w-3xl w-full mt-3 bg-slate-900/50 border border-slate-800/80 rounded-xl p-4 space-y-3">
                      <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">Grounding Citations</p>
                      <div className="grid grid-cols-1 gap-2.5">
                        {msg.citations.map((cite, cIdx) => (
                          <div key={cIdx} className="rounded-lg bg-slate-950/60 border border-slate-800/50 p-3 text-xs">
                            <div className="flex items-center justify-between mb-1">
                              <span className="font-semibold text-indigo-400">[{cIdx + 1}] {cite.filename}</span>
                              <span className="text-[10px] text-slate-400 uppercase font-medium">{cite.page_or_section}</span>
                            </div>
                            <p className="text-slate-300 italic leading-relaxed font-mono">
                              &ldquo;{cite.chunk_text_snippet}&rdquo;
                            </p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* Input Bar */}
        <div className="border-t border-slate-800 bg-slate-900/30 px-6 py-4 shrink-0">
          <form onSubmit={handleSendMessage} className="max-w-3xl mx-auto flex items-center gap-3">
            <input
              type="text"
              required
              disabled={loading}
              className="flex-1 rounded-xl border border-slate-800 bg-slate-950 px-4 py-3 text-sm text-white placeholder-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-indigo-500 disabled:opacity-50"
              placeholder="Ask a question..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
            />
            <button
              type="submit"
              disabled={loading || !input.trim()}
              className="rounded-xl bg-indigo-600 hover:bg-indigo-500 p-3 text-white disabled:opacity-50 transition"
            >
              <Send size={18} />
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
