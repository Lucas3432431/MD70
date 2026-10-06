import { useCallback, useEffect, useRef, useState, type FC } from "react";
import { useNavigate, useSearch } from "@tanstack/react-router";
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  FolderOpen,
  Loader2,
  Mic,
  Paperclip,
  Send,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface Message {
  role: "user" | "assistant";
  content: string;
}

const WAVEFORM_BARS = 24;

function getCsrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
  return match?.[1] ? decodeURIComponent(match[1]) : "";
}

function jsonHeaders() {
  return { "Content-Type": "application/json", "X-CSRF-Token": getCsrfToken() };
}

export const AdminFloatingChat: FC<{ onPanelChange?: (open: boolean) => void }> = ({ onPanelChange }) => {
  const navigate = useNavigate();
  const { chat: urlChatId } = useSearch({ strict: false }) as { chat?: string };

  const [chatStarted, setChatStarted] = useState(!!urlChatId);
  const [sideExpanded, setSideExpanded] = useState(true);
  const [mobileExpanded, setMobileExpanded] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [chatId, setChatId] = useState<string | null>(urlChatId ?? null);
  const [pending, setPending] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [recordingTime, setRecordingTime] = useState(0);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [waveformBars, setWaveformBars] = useState<number[]>(Array(WAVEFORM_BARS).fill(2));

  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const recordingChunksRef = useRef<Blob[]>([]);
  const recordingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const wsFallbackRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animFrameRef = useRef<number | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const loadedChatRef = useRef<string | null>(null);

  // ── Scroll to bottom ────────────────────────────────────────────────────
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, pending]);

  // ── Cleanup on unmount ──────────────────────────────────────────────────
  useEffect(() => {
    return () => {
      wsRef.current?.close();
      if (wsFallbackRef.current) clearTimeout(wsFallbackRef.current);
      if (mediaRecorderRef.current?.state !== "inactive") mediaRecorderRef.current?.stop();
      if (recordingTimerRef.current) clearInterval(recordingTimerRef.current);
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      audioCtxRef.current?.close();
    };
  }, []);

  // ── Load existing chat when URL has ?chat= (reload / tab switch) ────────
  useEffect(() => {
    if (!urlChatId || loadedChatRef.current === urlChatId) return;
    loadedChatRef.current = urlChatId;
    setChatId(urlChatId);
    setChatStarted(true);
    setSideExpanded(true);

    fetch(`/api/chat/${urlChatId}`, { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!data) return;
        const raw: Array<{ role: string; content: string }> = data.messages ?? data;
        const hydrated: Message[] = raw
          .filter((m) => m.role === "user" || m.role === "assistant")
          .map((m) => ({ role: m.role as "user" | "assistant", content: m.content }));
        setMessages(hydrated);
      })
      .catch(() => {/* silent */});
  }, [urlChatId]);

  const formatTime = (s: number) =>
    `${Math.floor(s / 60).toString().padStart(2, "0")}:${(s % 60).toString().padStart(2, "0")}`;

  // ── WebSocket ───────────────────────────────────────────────────────────
  const fetchAndAppendAssistantMessage = useCallback(async (id: string) => {
    try {
      const res = await fetch(`/api/chat/${id}`, { credentials: "include" });
      if (!res.ok) return;
      const data = await res.json();
      const msgs: Array<{ role: string; content: string }> = data.messages ?? data;
      const last = [...msgs].reverse().find((m) => m.role === "assistant");
      if (last) setMessages((prev) => [...prev, { role: "assistant", content: last.content }]);
    } catch {
      // silent
    } finally {
      setPending(false);
    }
  }, []);

  const openWebSocket = useCallback(
    (id: string) => {
      wsRef.current?.close();
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(`${proto}//${window.location.host}/api/ws/${id}`);
      wsRef.current = ws;

      wsFallbackRef.current = setTimeout(() => {
        ws.close();
        fetchAndAppendAssistantMessage(id);
      }, 90_000);

      ws.onmessage = async (event) => {
        try {
          const data = JSON.parse(event.data as string);
          if (data.type === "job_status") {
            if (data.status === "completed" || data.status === "failed") {
              if (wsFallbackRef.current) clearTimeout(wsFallbackRef.current);
              ws.close();
              if (data.status === "completed") await fetchAndAppendAssistantMessage(id);
              else setPending(false);
            }
          }
        } catch { /* ignore */ }
      };

      ws.onerror = () => {
        if (wsFallbackRef.current) clearTimeout(wsFallbackRef.current);
        ws.close();
        fetchAndAppendAssistantMessage(id);
      };
    },
    [fetchAndAppendAssistantMessage],
  );

  // ── Send message ────────────────────────────────────────────────────────
  const sendMessage = useCallback(
    async (text: string) => {
      if (!text.trim() && !selectedFile) return;
      if (pending) return;

      const userMessage = text.trim();
      setMessages((prev) => [...prev, { role: "user", content: userMessage }]);
      setInput("");
      setSelectedFile(null);
      if (textareaRef.current) textareaRef.current.style.height = "auto";
      setPending(true);

      if (!chatStarted) {
        setChatStarted(true);
        setSideExpanded(true);
        setMobileExpanded(true);
      }

      try {
        let activeChatId = chatId;

        if (!activeChatId) {
          const res = await fetch("/api/new-chat", {
            method: "POST",
            credentials: "include",
            headers: jsonHeaders(),
            body: JSON.stringify({ chat_name: userMessage.slice(0, 50) || "Admin", model: "gpt-4o-mini" }),
          });
          if (!res.ok) throw new Error(`new-chat ${res.status}`);
          const data = await res.json();
          activeChatId = data.chat_id as string;
          setChatId(activeChatId);
          // Mark as loaded BEFORE navigate so the URL-change useEffect skips the re-fetch
          loadedChatRef.current = activeChatId;
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          navigate({ search: ((prev: Record<string, unknown>) => ({ ...prev, chat: activeChatId! })) as any, replace: false });
        }

        // Send the actual message (new or existing chat)
        const msgRes = await fetch(`/api/chat/${activeChatId}/message`, {
          method: "POST",
          credentials: "include",
          headers: jsonHeaders(),
          body: JSON.stringify({ message: userMessage, model: "gpt-4o-mini" }),
        });
        if (!msgRes.ok) throw new Error(`send ${msgRes.status}`);

        openWebSocket(activeChatId);
      } catch (err) {
        setPending(false);
        toast.error("Erro ao enviar mensagem. Tente novamente.");
        console.error(err);
      }
    },
    [chatId, chatStarted, navigate, pending, selectedFile, openWebSocket],
  );

  const closeChat = useCallback(() => {
    wsRef.current?.close();
    setChatStarted(false);
    setMessages([]);
    setChatId(null);
    loadedChatRef.current = null;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    navigate({ search: ((prev: Record<string, unknown>) => { const { chat: _, ...rest } = prev; return rest; }) as any, replace: false });
  }, [navigate]);

  // ── Recording helpers ───────────────────────────────────────────────────
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(input); }
  };
  const handleInput = (e: React.FormEvent<HTMLTextAreaElement>) => {
    const el = e.currentTarget; el.style.height = "auto"; el.style.height = `${el.scrollHeight}px`;
  };

  const stopWaveformAnimation = useCallback(() => {
    if (animFrameRef.current) { cancelAnimationFrame(animFrameRef.current); animFrameRef.current = null; }
    if (audioCtxRef.current) { audioCtxRef.current.close(); audioCtxRef.current = null; }
    analyserRef.current = null;
    setWaveformBars(Array(WAVEFORM_BARS).fill(2));
  }, []);

  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      recordingChunksRef.current = [];
      recorder.ondataavailable = (e) => { if (e.data.size > 0) recordingChunksRef.current.push(e.data); };
      const audioCtx = new AudioContext();
      audioCtxRef.current = audioCtx;
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 64;
      analyserRef.current = analyser;
      audioCtx.createMediaStreamSource(stream).connect(analyser);
      const arr = new Uint8Array(analyser.frequencyBinCount);
      const animate = () => {
        analyser.getByteFrequencyData(arr);
        setWaveformBars(Array.from({ length: WAVEFORM_BARS }, (_, i) =>
          Math.max(2, Math.round(((arr[Math.floor((i / WAVEFORM_BARS) * arr.length)] ?? 0) / 255) * 28)),
        ));
        animFrameRef.current = requestAnimationFrame(animate);
      };
      animFrameRef.current = requestAnimationFrame(animate);
      recorder.start();
      mediaRecorderRef.current = recorder;
      setIsRecording(true);
      setRecordingTime(0);
      recordingTimerRef.current = setInterval(() => setRecordingTime((t) => t + 1), 1000);
    } catch { toast.error("Microfone não disponível."); }
  }, []);

  const cancelRecording = useCallback(() => {
    stopWaveformAnimation();
    if (recordingTimerRef.current) { clearInterval(recordingTimerRef.current); recordingTimerRef.current = null; }
    const r = mediaRecorderRef.current;
    if (r) {
      r.ondataavailable = null; r.onstop = null;
      if (r.state !== "inactive") { r.stop(); r.stream.getTracks().forEach((t) => t.stop()); }
    }
    recordingChunksRef.current = [];
    setIsRecording(false); setRecordingTime(0);
  }, [stopWaveformAnimation]);

  const stopAndTranscribe = useCallback(() => {
    stopWaveformAnimation();
    if (recordingTimerRef.current) { clearInterval(recordingTimerRef.current); recordingTimerRef.current = null; }
    const r = mediaRecorderRef.current;
    if (r && r.state !== "inactive") {
      r.onstop = async () => {
        r.stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(recordingChunksRef.current, { type: "audio/webm" });
        try {
          const fd = new FormData();
          fd.append("audio", blob, "recording.webm");
          const res = await fetch("/api/audio/transcribe", {
            method: "POST", credentials: "include",
            headers: { "X-CSRF-Token": getCsrfToken() },
            body: fd,
          });
          if (res.ok) setInput((await res.json()).text ?? "");
          else toast.error("Erro ao transcrever áudio.");
        } catch { toast.error("Erro ao transcrever áudio."); }
      };
      r.stop();
    }
    setIsRecording(false); setRecordingTime(0);
  }, [stopWaveformAnimation]);

  const canSend = (input.trim().length > 0 || selectedFile !== null) && !pending;

  const panelOpen = chatStarted && sideExpanded;
  useEffect(() => { onPanelChange?.(panelOpen); }, [panelOpen, onPanelChange]);

  // ── Input row ────────────────────────────────────────────────────────────
  const InputRow = (
    <>
      {selectedFile && !isRecording && (
        <div className="mb-1.5 px-1 flex items-center gap-1">
          <div className="flex items-center gap-1.5 rounded-xl bg-muted px-2 py-1 text-xs text-foreground max-w-[200px]">
            <Paperclip className="size-3 shrink-0" />
            <span className="truncate">{selectedFile.name}</span>
            <button type="button" aria-label="Remover arquivo" className="ml-0.5 text-muted-foreground hover:text-foreground" onClick={() => setSelectedFile(null)}>
              <X className="size-3" />
            </button>
          </div>
        </div>
      )}
      {isRecording ? (
        <div className="flex items-center gap-2 px-1">
          <Button variant="ghost" size="icon" type="button" aria-label="Cancelar gravação" onClick={cancelRecording} className="size-11 rounded-xl bg-white border border-border shrink-0">
            <X className="size-6" />
          </Button>
          <div className="flex flex-1 items-center gap-2 px-2 overflow-hidden">
            <span className="text-sm text-muted-foreground tabular-nums shrink-0">{formatTime(recordingTime)}</span>
            <div className="flex flex-1 items-end justify-center gap-px h-7 overflow-hidden">
              {waveformBars.map((h, i) => <div key={i} className="w-[2px] rounded-full bg-destructive transition-all duration-75" style={{ height: `${h}px` }} />)}
            </div>
          </div>
          <Button variant="ghost" size="icon" type="button" aria-label="Enviar áudio" onClick={stopAndTranscribe} className="size-11 rounded-xl bg-white border border-border shrink-0">
            <Send className="size-6" />
          </Button>
        </div>
      ) : (
        <div className="flex items-end gap-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="size-11 rounded-xl bg-white border border-border shrink-0 text-muted-foreground hover:text-foreground" aria-label="Anexar arquivo">
                <Paperclip className="size-6" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" side="top" className="w-44">
              <DropdownMenuItem onSelect={() => toast.info("Google Drive em breve.")} className="gap-2 cursor-pointer">
                <FolderOpen className="size-4" />Google Drive
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => fileInputRef.current?.click()} className="gap-2 cursor-pointer">
                <Paperclip className="size-4" />Arquivo local
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <input ref={fileInputRef} type="file" className="sr-only" aria-hidden tabIndex={-1} onChange={(e) => { setSelectedFile(e.target.files?.[0] ?? null); e.target.value = ""; }} />
          <Textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            onInput={handleInput}
            placeholder="Como posso te ajudar?"
            rows={1}
            className="min-h-[44px] max-h-48 resize-none overflow-y-auto rounded-xl border-0 bg-transparent px-2 py-2.5 text-lg focus:outline-none focus-visible:ring-0 focus-visible:ring-offset-0"
            aria-label="Mensagem"
          />
          <Button variant="ghost" size="icon" type="button" aria-label="Gravar áudio" onClick={startRecording} className="size-11 rounded-xl bg-white border border-border shrink-0 text-muted-foreground hover:text-foreground">
            <Mic className="size-6" />
          </Button>
          <Button variant="ghost" size="icon" type="button" aria-label="Enviar" disabled={!canSend} onClick={() => sendMessage(input)} className="size-11 rounded-xl bg-white border border-border shrink-0 text-muted-foreground hover:text-foreground disabled:opacity-40">
            {pending ? <Loader2 className="size-6 animate-spin" /> : <Send className="size-6" />}
          </Button>
        </div>
      )}
    </>
  );

  // ── Message list ─────────────────────────────────────────────────────────
  const MessageList = (
    <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto p-4 space-y-3">
      {messages.map((msg, i) => (
        <div key={i} className={cn(
          "rounded-xl px-3 py-2 text-sm",
          msg.role === "user"
            ? "ml-auto max-w-[80%] bg-primary text-primary-foreground whitespace-pre-wrap"
            : "max-w-[80%] bg-muted text-foreground",
        )}>
          {msg.role === "assistant" ? (
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                ul: ({ children }) => <ul className="mb-2 ml-4 list-disc space-y-0.5 last:mb-0">{children}</ul>,
                ol: ({ children }) => <ol className="mb-2 ml-4 list-decimal space-y-0.5 last:mb-0">{children}</ol>,
                li: ({ children }) => <li>{children}</li>,
                strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
                em: ({ children }) => <em className="italic">{children}</em>,
                code: ({ children, className }) => {
                  const isBlock = className?.includes("language-");
                  return isBlock
                    ? <code className="block rounded bg-background/60 px-2 py-1 text-xs font-mono whitespace-pre-wrap my-1">{children}</code>
                    : <code className="rounded bg-background/60 px-1 text-xs font-mono">{children}</code>;
                },
                pre: ({ children }) => <pre className="mb-2 overflow-x-auto last:mb-0">{children}</pre>,
                h1: ({ children }) => <h1 className="mb-1 font-semibold text-base">{children}</h1>,
                h2: ({ children }) => <h2 className="mb-1 font-semibold">{children}</h2>,
                h3: ({ children }) => <h3 className="mb-1 font-medium">{children}</h3>,
                a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2 hover:opacity-80">{children}</a>,
                blockquote: ({ children }) => <blockquote className="border-l-2 border-muted-foreground/40 pl-2 italic text-muted-foreground">{children}</blockquote>,
                hr: () => <hr className="my-2 border-muted-foreground/20" />,
              }}
            >
              {msg.content}
            </ReactMarkdown>
          ) : msg.content}
        </div>
      ))}
      {pending && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /><span>Gerando resposta…</span>
        </div>
      )}
    </div>
  );

  return (
    <>
      {/* ══════════════════════════════════════════════════
          DESKTOP — right side panel (33% width)
      ══════════════════════════════════════════════════ */}

      <aside
        className={cn(
          "hidden lg:flex flex-col fixed right-0 top-16 z-30 bg-background border-l",
          "bottom-[calc(44px+env(safe-area-inset-bottom))]",
          "transition-[width] duration-300 ease-in-out overflow-hidden",
          chatStarted
            ? sideExpanded ? "w-[33vw]" : "w-[52px]"
            : "w-0 border-l-0",
        )}
        aria-label="Chat — histórico"
      >
        {chatStarted && (
          <>
            {/* Collapse/expand chevron */}
            <button
              onClick={() => setSideExpanded((v) => !v)}
              className="absolute -left-[17px] top-1/2 -translate-y-1/2 z-10 flex h-8 w-[17px] items-center justify-center rounded-l-lg border border-r-0 bg-background hover:bg-muted transition-colors"
              aria-label={sideExpanded ? "Recolher" : "Expandir"}
            >
              {sideExpanded ? <ChevronRight className="size-3" /> : <ChevronLeft className="size-3" />}
            </button>

            {sideExpanded ? (
              <div className="flex flex-col h-full overflow-hidden">
                {/* Header */}
                <div className="flex-shrink-0 flex items-center justify-between px-3 py-2.5 border-b">
                  <span className="font-semibold text-sm">Assistente MD70</span>
                  <Button variant="ghost" size="icon" className="size-7 rounded-lg" onClick={closeChat} aria-label="Fechar conversa">
                    <X className="size-3.5" />
                  </Button>
                </div>
                {/* Messages */}
                {MessageList}
                {/* Input inside panel */}
                <div className="flex-shrink-0 border-t p-2">
                  <div
                    className="rounded-xl bg-background p-1"
                    style={{ boxShadow: "0 0 20px oklch(0.29 0.045 195 / 0.2), 0 2px 4px -1px rgba(0,0,0,0.06)" }}
                  >
                    {InputRow}
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex flex-col h-full items-center justify-center">
                <Button variant="ghost" size="icon" className="size-9 rounded-xl" onClick={closeChat} aria-label="Fechar conversa">
                  <X className="size-4 text-muted-foreground" />
                </Button>
              </div>
            )}
          </>
        )}
      </aside>

      {/* Desktop bottom input — only shown when panel is NOT open */}
      {!panelOpen && (
        <div className="hidden lg:block fixed inset-x-0 bottom-[calc(3.5rem+env(safe-area-inset-bottom))] z-40 pointer-events-none">
          <div className="mx-auto w-full max-w-3xl px-4 lg:max-w-[46rem] pointer-events-auto">
            <div
              className="rounded-xl border-transparent bg-background p-2"
              style={{ boxShadow: "0 0 30px oklch(0.29 0.045 195 / 0.35), 0 0 60px oklch(0.29 0.045 195 / 0.12), 0 4px 6px -1px rgba(0,0,0,0.08)" }}
            >
              {InputRow}
            </div>
          </div>
        </div>
      )}

      {/* ══════════════════════════════════════════════════
          MOBILE — input always at bottom, messages slide up above it
      ══════════════════════════════════════════════════ */}

      {chatStarted && mobileExpanded && (
        <div
          className="lg:hidden fixed inset-0 z-30 bg-black/40 backdrop-blur-sm"
          style={{ bottom: "calc(44px + env(safe-area-inset-bottom))" }}
          onClick={() => setMobileExpanded(false)}
        />
      )}

      {chatStarted && (
        <div
          className={cn(
            "lg:hidden fixed inset-x-0 z-40 flex flex-col bg-background rounded-t-2xl border-t",
            "shadow-[0_-4px_30px_rgba(0,0,0,0.12)] overflow-hidden",
            "transition-[height] duration-300 ease-in-out",
          )}
          style={{
            bottom: `calc(4.5rem + env(safe-area-inset-bottom))`,
            height: mobileExpanded ? "55vh" : "48px",
          }}
        >
          <button
            className="flex-shrink-0 flex items-center justify-between px-4 h-12 border-b"
            onClick={() => setMobileExpanded((v) => !v)}
          >
            <span className="text-sm font-semibold">Assistente MD70</span>
            <div className="flex items-center gap-1">
              {mobileExpanded && (
                <Button
                  variant="ghost" size="icon" className="size-7 rounded-lg"
                  onClick={(e) => { e.stopPropagation(); closeChat(); }}
                  aria-label="Fechar"
                >
                  <X className="size-3.5" />
                </Button>
              )}
              {mobileExpanded
                ? <ChevronDown className="size-4 text-muted-foreground" />
                : <ChevronUp className="size-4 text-muted-foreground" />}
            </div>
          </button>

          {mobileExpanded && MessageList}
        </div>
      )}

      {/* Mobile bottom input — always visible */}
      <div
        className="lg:hidden fixed inset-x-0 z-40"
        style={{ bottom: "calc(3.5rem + env(safe-area-inset-bottom))" }}
      >
        <div className="mx-auto w-full max-w-3xl px-4">
          <div
            className="rounded-xl border-transparent bg-background p-2"
            style={{ boxShadow: "0 0 30px oklch(0.29 0.045 195 / 0.35), 0 0 60px oklch(0.29 0.045 195 / 0.12), 0 4px 6px -1px rgba(0,0,0,0.08)" }}
          >
            {InputRow}
          </div>
        </div>
      </div>
    </>
  );
}
