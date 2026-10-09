import { useCallback, useEffect, useRef, useState, type FC } from "react";
import { useNavigate, useSearch } from "@tanstack/react-router";
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  FileText,
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
import { ToolCallGroup } from "./ToolMessageDisplay";

interface Message {
  role: "user" | "assistant" | "tool";
  content: string;
  tool?: string | null;
}

const WAVEFORM_BARS = 24;

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function getCsrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
  return match?.[1] ? decodeURIComponent(match[1]) : "";
}

function jsonHeaders() {
  return { "Content-Type": "application/json", "X-CSRF-Token": getCsrfToken() };
}

export const AdminFloatingChat: FC<{ onPanelChange?: (state: "closed" | "collapsed" | "open") => void }> = ({ onPanelChange }) => {
  const navigate = useNavigate();
  const { chat: urlChatId, panel: urlPanel } = useSearch({ strict: false }) as { chat?: string; panel?: string };
  const sideExpanded = urlPanel !== "collapsed";

  const [chatStarted, setChatStarted] = useState(!!urlChatId);
  const [mobileExpanded, setMobileExpanded] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [chatId, setChatId] = useState<string | null>(urlChatId ?? null);
  const [pending, setPending] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [recordingTime, setRecordingTime] = useState(0);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [attachmentId, setAttachmentId] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [waveformBars, setWaveformBars] = useState<number[]>(Array(WAVEFORM_BARS).fill(2));

  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const uploadFileRef = useRef<((file: File) => void) | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const recordingChunksRef = useRef<Blob[]>([]);
  const recordingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const wsFallbackRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animFrameRef = useRef<number | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const loadedChatRef = useRef<string | null>(null);

  const collapsePanel = useCallback(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    navigate({ search: ((prev: Record<string, unknown>) => ({ ...prev, panel: "collapsed" })) as any, replace: false });
  }, [navigate]);

  const expandPanel = useCallback(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    navigate({ search: ((prev: Record<string, unknown>) => { const { panel: _, ...rest } = prev; return rest; }) as any, replace: false });
  }, [navigate]);

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

  // ── Eager file upload ───────────────────────────────────────────────────
  const uploadFile = useCallback(async (file: File) => {
    setSelectedFile(file);
    setAttachmentId(null);
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch("/api/upload/", {
        method: "POST",
        credentials: "include",
        headers: { "X-CSRF-Token": getCsrfToken() },
        body: fd,
      });
      if (!res.ok) throw new Error(`upload ${res.status}`);
      const data = await res.json();
      setAttachmentId(data.attachment_id as string);
    } catch (err) {
      toast.error("Erro ao fazer upload do arquivo.");
      setSelectedFile(null);
      console.error(err);
    } finally {
      setUploading(false);
    }
  }, []);
  uploadFileRef.current = uploadFile;

  // ── Full-screen drag & drop ─────────────────────────────────────────────
  useEffect(() => {
    const ACCEPTED = ["application/pdf", "image/jpeg", "image/png"];
    let counter = 0;

    const onDragEnter = (e: DragEvent) => {
      if (e.dataTransfer?.types.includes("Files")) { counter++; setIsDragging(true); }
    };
    const onDragLeave = () => {
      counter--; if (counter <= 0) { counter = 0; setIsDragging(false); }
    };
    const onDragOver = (e: DragEvent) => {
      if (e.dataTransfer?.types.includes("Files")) e.preventDefault();
    };
    const onDrop = (e: DragEvent) => {
      counter = 0; setIsDragging(false); e.preventDefault();
      const file = e.dataTransfer?.files[0];
      if (!file) return;
      if (ACCEPTED.includes(file.type) || file.type.startsWith("audio/")) {
        uploadFileRef.current?.(file);
      } else {
        toast.error("Tipo não suportado. Use PDF, JPG, PNG ou áudio.");
      }
    };

    document.addEventListener("dragenter", onDragEnter);
    document.addEventListener("dragleave", onDragLeave);
    document.addEventListener("dragover", onDragOver);
    document.addEventListener("drop", onDrop);
    return () => {
      document.removeEventListener("dragenter", onDragEnter);
      document.removeEventListener("dragleave", onDragLeave);
      document.removeEventListener("dragover", onDragOver);
      document.removeEventListener("drop", onDrop);
    };
  }, []);

  // ── Load existing chat when URL has ?chat= (reload / tab switch) ────────
  useEffect(() => {
    if (!urlChatId || loadedChatRef.current === urlChatId) return;
    loadedChatRef.current = urlChatId;
    setChatId(urlChatId);
    setChatStarted(true);

    fetch(`/api/chat/${urlChatId}`, { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!data) return;
        const raw: Array<{ role: string; content: string; tool?: string | null }> = data.messages ?? data;
        const hydrated: Message[] = raw
          .filter((m) => m.role === "user" || m.role === "assistant" || m.role === "tool")
          .map((m) => ({ role: m.role as Message["role"], content: m.content, tool: m.tool ?? null }));
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
            if (data.status === "completed" || data.status === "failed" || data.status === "error") {
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
      const fileToUpload = selectedFile;
      const eagerAttachmentId = attachmentId;

      setMessages((prev) => [...prev, { role: "user", content: userMessage || `📎 ${fileToUpload?.name}` }]);
      setInput("");
      setSelectedFile(null);
      setAttachmentId(null);
      if (textareaRef.current) textareaRef.current.style.height = "auto";
      setPending(true);

      if (!chatStarted) {
        setChatStarted(true);
        setMobileExpanded(true);
      }

      try {
        let activeChatId = chatId;

        if (!activeChatId) {
          const res = await fetch("/api/new-chat", {
            method: "POST",
            credentials: "include",
            headers: jsonHeaders(),
            body: JSON.stringify({ chat_name: userMessage.slice(0, 50) || fileToUpload?.name || "Admin", model: "gpt-4o-mini" }),
          });
          if (!res.ok) throw new Error(`new-chat ${res.status}`);
          const data = await res.json();
          activeChatId = data.chat_id as string;
          setChatId(activeChatId);
          loadedChatRef.current = activeChatId;
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          navigate({ search: ((prev: Record<string, unknown>) => { const { panel: _, ...rest } = prev; return { ...rest, chat: activeChatId! }; }) as any, replace: false });
        }

        // Send message (attachment already uploaded eagerly)
        const msgBody: Record<string, unknown> = { message: userMessage || `📎 ${fileToUpload?.name ?? "arquivo"}`, model: "gpt-4o-mini" };
        if (eagerAttachmentId) msgBody["attachment"] = { attachment_type: "file", attachment_id: eagerAttachmentId };

        const msgRes = await fetch(`/api/chat/${activeChatId}/message`, {
          method: "POST",
          credentials: "include",
          headers: jsonHeaders(),
          body: JSON.stringify(msgBody),
        });
        if (!msgRes.ok) throw new Error(`send ${msgRes.status}`);

        openWebSocket(activeChatId);
      } catch (err) {
        setPending(false);
        toast.error("Erro ao enviar mensagem. Tente novamente.");
        console.error(err);
      }
    },
    [chatId, chatStarted, navigate, pending, selectedFile, attachmentId, openWebSocket],
  );

  const closeChat = useCallback(() => {
    wsRef.current?.close();
    setChatStarted(false);
    setMessages([]);
    setChatId(null);
    loadedChatRef.current = null;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    navigate({ search: ((prev: Record<string, unknown>) => { const { chat: _, panel: __, ...rest } = prev; return rest; }) as any, replace: false });
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

  const canSend = (input.trim().length > 0 || selectedFile !== null) && !pending && !uploading;

  const panelOpen = chatStarted && sideExpanded;
  const panelState = !chatStarted ? "closed" : sideExpanded ? "open" : "collapsed";
  useEffect(() => { onPanelChange?.(panelState as "closed" | "collapsed" | "open"); }, [panelState, onPanelChange]);

  // ── Input row ────────────────────────────────────────────────────────────
  const InputRow = (
    <>
      {selectedFile && !isRecording && (
        <div className="mb-1.5 px-1 flex items-center gap-2">
          {selectedFile.type.startsWith("image/") ? (
            <div className="group relative w-16 h-16 rounded-lg overflow-hidden shrink-0">
              <img
                src={URL.createObjectURL(selectedFile)}
                alt={selectedFile.name}
                className="w-full h-full object-cover rounded-lg"
              />
              {uploading && (
                <div className="absolute inset-0 flex items-center justify-center bg-primary/20 rounded-lg">
                  <Loader2 className="size-4 text-primary animate-spin" />
                </div>
              )}
              {!uploading && (
                <button
                  type="button"
                  aria-label="Remover arquivo"
                  className="absolute -top-1.5 -right-1.5 z-20 flex size-5 items-center justify-center rounded-full bg-muted opacity-0 transition-opacity group-hover:opacity-100 hover:bg-muted-foreground/30"
                  onClick={() => { setSelectedFile(null); setAttachmentId(null); }}
                >
                  <X className="size-3" />
                </button>
              )}
            </div>
          ) : (
            <div className="group relative h-16 w-52 shrink-0 rounded-lg border border-border bg-muted p-1">
              {uploading && (
                <div className="absolute inset-0 z-20 flex items-center justify-center gap-1.5 rounded-lg bg-primary/10">
                  <Loader2 className="size-4 text-primary animate-spin" />
                  <span className="text-xs font-medium text-primary">Enviando…</span>
                </div>
              )}
              <div className={cn("flex h-full w-full flex-col items-start justify-center px-2 py-1", uploading && "opacity-40")}>
                <span className="w-full truncate text-sm font-bold leading-tight">{selectedFile.name}</span>
                <div className="mt-1 flex items-center gap-1">
                  <FileText className="size-3.5 text-muted-foreground shrink-0" />
                  <span className="text-xs text-muted-foreground">.{selectedFile.name.split(".").pop()}</span>
                  <span className="text-xs text-muted-foreground">·</span>
                  <span className="text-xs text-muted-foreground">{formatFileSize(selectedFile.size)}</span>
                </div>
              </div>
              {!uploading && (
                <button
                  type="button"
                  aria-label="Remover arquivo"
                  className="absolute -top-2.5 -right-2.5 z-20 flex size-6 items-center justify-center rounded-full bg-muted opacity-0 transition-opacity group-hover:opacity-100 hover:bg-muted-foreground/30"
                  onClick={() => { setSelectedFile(null); setAttachmentId(null); }}
                >
                  <X className="size-3.5" />
                </button>
              )}
            </div>
          )}
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
          <input ref={fileInputRef} type="file" accept="application/pdf,image/jpeg,image/png,audio/*" className="sr-only" aria-hidden tabIndex={-1} onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadFile(f); e.target.value = ""; }} />
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

  // ── Segment messages — consecutive tool messages become one group ─────────
  type MsgSeg =
    | { type: "single"; msg: Message; idx: number }
    | { type: "group"; items: Message[]; startIdx: number };
  const msgSegs: MsgSeg[] = [];
  {
    let grp: Message[] | null = null;
    let grpStart = 0;
    for (let i = 0; i < messages.length; i++) {
      const m = messages[i]!;
      if (m.role === "tool") {
        if (!grp) { grp = []; grpStart = i; }
        grp.push(m);
      } else {
        if (grp) { msgSegs.push({ type: "group", items: grp, startIdx: grpStart }); grp = null; }
        msgSegs.push({ type: "single", msg: m, idx: i });
      }
    }
    if (grp) msgSegs.push({ type: "group", items: grp, startIdx: grpStart });
  }

  // ── Message list ─────────────────────────────────────────────────────────
  const MessageList = (
    <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto p-4 space-y-3">
      {msgSegs.map((seg) => {
          if (seg.type === "group") {
            return (
              <ToolCallGroup
                key={`group-${seg.startIdx}`}
                tools={seg.items.map(m => ({ content: m.content, tool: m.tool ?? null }))}
              />
            );
          }
          const { msg, idx } = seg;
          return (
            <div key={`single-${idx}`} className={cn(
              "rounded-xl px-3 py-2 text-lg",
              msg.role === "user"
                ? "ml-auto max-w-[80%] bg-primary text-primary-foreground whitespace-pre-wrap"
                : "max-w-[85%] text-foreground",
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
                        ? <code className="block rounded bg-muted/60 px-2 py-1 text-xs font-mono whitespace-pre-wrap my-1">{children}</code>
                        : <code className="rounded bg-muted/60 px-1 text-xs font-mono">{children}</code>;
                    },
                    pre: ({ children }) => <pre className="mb-2 overflow-x-auto last:mb-0">{children}</pre>,
                    h1: ({ children }) => <h1 className="mb-2 mt-1 font-semibold text-xl">{children}</h1>,
                    h2: ({ children }) => <h2 className="mb-1.5 mt-1 font-semibold text-lg">{children}</h2>,
                    h3: ({ children }) => <h3 className="mb-1 font-medium">{children}</h3>,
                    a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2 hover:opacity-80">{children}</a>,
                    blockquote: ({ children }) => <blockquote className="border-l-2 border-muted-foreground/40 pl-3 italic text-muted-foreground my-1">{children}</blockquote>,
                    hr: () => <hr className="my-2 border-muted-foreground/20" />,
                    table: ({ children }) => (
                      <div className="my-2 overflow-x-auto rounded-lg border border-border/50">
                        <table className="min-w-full border-collapse text-sm">{children}</table>
                      </div>
                    ),
                    thead: ({ children }) => <thead className="bg-muted/50 border-b border-border/50">{children}</thead>,
                    tbody: ({ children }) => <tbody className="divide-y divide-border/30">{children}</tbody>,
                    tr: ({ children }) => <tr>{children}</tr>,
                    th: ({ children }) => <th className="px-3 py-2 text-left text-base font-bold text-foreground whitespace-nowrap">{children}</th>,
                    td: ({ children }) => <td className="px-3 py-2 text-sm text-foreground/80">{children}</td>,
                  }}
                >
                  {msg.content}
                </ReactMarkdown>
              ) : msg.content}
            </div>
          );
      })}
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
          "hidden lg:flex flex-col fixed right-4 z-30 rounded-2xl overflow-hidden bg-background",
          "bottom-[calc(56px+env(safe-area-inset-bottom)+1rem)]",
          "transition-[width,opacity] duration-300 ease-in-out",
          "shadow-[0_8px_40px_rgba(0,0,0,0.18),0_2px_8px_rgba(0,0,0,0.08)]",
          !chatStarted ? "w-0 opacity-0 pointer-events-none" :
          sideExpanded ? "w-[33vw]" : "w-12",
        )}
        style={{ top: "calc(4rem + 1rem)" }}
        aria-label="Chat — histórico"
      >
        {chatStarted && (sideExpanded ? (
          <div className="flex flex-col h-full overflow-hidden">
            {/* Chevron right — collapses panel, persists in URL */}
            <div className="flex-shrink-0 flex items-center px-3 pt-3 pb-1">
              <button
                onClick={collapsePanel}
                className="cursor-pointer p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
                aria-label="Recolher painel"
              >
                <ChevronRight className="size-4" />
              </button>
            </div>
            {/* Messages */}
            {MessageList}
            {/* Input inside panel */}
            <div className="flex-shrink-0 border-t p-2">
              <div
                className="relative overflow-hidden rounded-xl bg-muted/20 p-1"
                style={{ boxShadow: "0 0 20px oklch(0.29 0.045 195 / 0.2), 0 2px 4px -1px rgba(0,0,0,0.06)" }}
              >
                {isDragging && <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-xl border-2 border-dashed border-primary bg-background/80"><Paperclip className="size-4 text-primary" /><span className="ml-2 text-sm font-medium text-primary">Soltar arquivo</span></div>}
                {InputRow}
              </div>
            </div>
          </div>
        ) : (
          /* Collapsed state — chevron left expands, X closes */
          <div className="flex flex-col items-center pt-3 gap-2">
            <button
              onClick={expandPanel}
              className="cursor-pointer p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
              aria-label="Expandir painel"
            >
              <ChevronLeft className="size-4" />
            </button>
            <button
              onClick={closeChat}
              className="cursor-pointer p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
              aria-label="Fechar conversa"
            >
              <X className="size-4" />
            </button>
          </div>
        ))}
      </aside>

      {/* Desktop bottom input — only shown when panel is NOT open */}
      {!panelOpen && (
        <div className="hidden lg:block fixed inset-x-0 bottom-[calc(3.5rem+env(safe-area-inset-bottom))] z-40 pointer-events-none">
          <div className="mx-auto w-full max-w-3xl px-4 lg:max-w-[46rem] pointer-events-auto">
            <div
              className="relative overflow-hidden rounded-xl border-transparent bg-background p-2"
              style={{ boxShadow: "0 0 30px oklch(0.29 0.045 195 / 0.35), 0 0 60px oklch(0.29 0.045 195 / 0.12), 0 4px 6px -1px rgba(0,0,0,0.08)" }}
            >
              {isDragging && <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-xl border-2 border-dashed border-primary bg-background/80"><Paperclip className="size-4 text-primary" /><span className="ml-2 text-sm font-medium text-primary">Soltar arquivo</span></div>}
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
            className="relative overflow-hidden rounded-xl border-transparent bg-background p-2"
            style={{ boxShadow: "0 0 30px oklch(0.29 0.045 195 / 0.35), 0 0 60px oklch(0.29 0.045 195 / 0.12), 0 4px 6px -1px rgba(0,0,0,0.08)" }}
          >
            {isDragging && <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-xl border-2 border-dashed border-primary bg-background/80"><Paperclip className="size-4 text-primary" /><span className="ml-2 text-sm font-medium text-primary">Soltar arquivo</span></div>}
            {InputRow}
          </div>
        </div>
      </div>
    </>
  );
}
